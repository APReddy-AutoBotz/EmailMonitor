-- Empty authority structures only. No LOGIN, password, membership assignment,
-- principal registration, tenant grant or historical-work enrollment is performed.
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='emailmonitor_worker') THEN
 CREATE ROLE emailmonitor_worker NOLOGIN NOSUPERUSER NOBYPASSRLS;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='emailmonitor_publisher') THEN
 CREATE ROLE emailmonitor_publisher NOLOGIN NOSUPERUSER NOBYPASSRLS;
 END IF;
 IF EXISTS(SELECT 1 FROM pg_roles
 WHERE rolname IN ('emailmonitor_worker','emailmonitor_publisher')
 AND (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication)) THEN
 RAISE EXCEPTION 'UNSAFE_SERVICE_ROLE'; END IF;
END $$;
GRANT USAGE ON SCHEMA emailmonitor TO emailmonitor_worker,emailmonitor_publisher;
SET ROLE emailmonitor_owner;

CREATE TABLE emailmonitor.service_principals (
 id uuid PRIMARY KEY,
 organization_id uuid NOT NULL REFERENCES emailmonitor.organizations(id),
 login_oid oid NOT NULL UNIQUE, login_name name NOT NULL UNIQUE,
 kind text NOT NULL CHECK(kind IN ('worker','publisher')),
 active boolean NOT NULL DEFAULT false,
 revision bigint NOT NULL DEFAULT 1 CHECK(revision>0),
 UNIQUE(organization_id,id)
);
CREATE TABLE emailmonitor.service_delegations (
 organization_id uuid NOT NULL,
 id uuid NOT NULL,
 principal_id uuid NOT NULL, principal_revision bigint NOT NULL CHECK(principal_revision>0),
 purpose text NOT NULL CHECK(purpose IN ('extraction','export')),
 resource_id uuid NOT NULL, generation bigint NOT NULL CHECK(generation>0),
 deletion_generation bigint NOT NULL CHECK(deletion_generation>0),
 initiator_id uuid NOT NULL REFERENCES emailmonitor.identities(id),
 permission_revision bigint NOT NULL CHECK(permission_revision>0),
 membership_revision bigint NOT NULL CHECK(membership_revision>0),
 origin_session_hash text NOT NULL REFERENCES emailmonitor.sessions(token_hash),
 source_id text NOT NULL, policy_version bigint NOT NULL,
 issued_at timestamptz NOT NULL, deadline timestamptz NOT NULL,
 revoked_at timestamptz,
 PRIMARY KEY(organization_id,id),
 UNIQUE(organization_id,principal_id,purpose,resource_id,generation),
 FOREIGN KEY(organization_id,principal_id)
 REFERENCES emailmonitor.service_principals(organization_id,id),
 FOREIGN KEY(organization_id,initiator_id)
 REFERENCES emailmonitor.memberships(organization_id,identity_id),
 FOREIGN KEY(organization_id,source_id,policy_version)
 REFERENCES emailmonitor.source_policies(organization_id,source_id,version),
 CHECK(deadline>issued_at AND deadline<=issued_at+interval '6 hours')
);
CREATE TABLE emailmonitor.service_audit (
 organization_id uuid NOT NULL, id uuid NOT NULL,
 principal_id uuid NOT NULL, delegation_id uuid NOT NULL,
 action text NOT NULL CHECK(action IN ('delegated','revoked','transaction')),
 occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(organization_id,id),
 FOREIGN KEY(organization_id,principal_id)
 REFERENCES emailmonitor.service_principals(organization_id,id),
 FOREIGN KEY(organization_id,delegation_id)
 REFERENCES emailmonitor.service_delegations(organization_id,id)
);
ALTER TABLE emailmonitor.service_principals ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.service_principals FORCE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.service_delegations ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.service_delegations FORCE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.service_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.service_audit FORCE ROW LEVEL SECURITY;
CREATE POLICY service_principal_owner ON emailmonitor.service_principals
 TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY service_delegation_owner ON emailmonitor.service_delegations
 TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY service_audit_owner ON emailmonitor.service_audit
 TO emailmonitor_owner USING(true) WITH CHECK(true);

CREATE FUNCTION emailmonitor.guard_service_principal() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF (NEW.id,NEW.organization_id,NEW.login_oid,NEW.login_name,NEW.kind)
 IS DISTINCT FROM (OLD.id,OLD.organization_id,OLD.login_oid,OLD.login_name,OLD.kind)
 OR NEW.revision<>OLD.revision THEN
 RAISE EXCEPTION 'SERVICE_PRINCIPAL_IMMUTABLE' USING ERRCODE='EM017'; END IF;
 -- Disable/re-enable never revives a previously issued delegation.
 NEW.revision:=OLD.revision+1;
 RETURN NEW;
END $$;
CREATE TRIGGER service_principal_revision BEFORE UPDATE ON emailmonitor.service_principals
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_service_principal();

-- Shared entrypoints must not accept a stolen/copied human hash from a service
-- login. SECURITY DEFINER current_user is the owner; authenticate session_user.
CREATE FUNCTION emailmonitor.human_work_tenant_allowed(p_org uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(EXISTS(SELECT 1 FROM pg_roles login WHERE login.rolname=session_user
 AND NOT login.rolsuper AND NOT login.rolbypassrls
 AND pg_has_role(login.oid,'emailmonitor_runtime','MEMBER')
 AND NOT pg_has_role(login.oid,'emailmonitor_worker','MEMBER')
 AND NOT pg_has_role(login.oid,'emailmonitor_publisher','MEMBER')
 AND NOT pg_has_role(login.oid,'emailmonitor_owner','MEMBER')
 AND NOT pg_has_role(login.oid,'emailmonitor_authenticator','MEMBER'))
 AND emailmonitor.tenant_allowed(p_org),false)
$$;

-- A service login cannot retain an indirect administrative or session-minting
-- path. MEMBER is deliberately conservative: even SET FALSE plus ADMIN TRUE
-- must not permit later regranting a privileged path while a pool is open.
CREATE FUNCTION emailmonitor.service_login_safe(p_login oid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT EXISTS(SELECT 1 FROM pg_roles WHERE oid=p_login AND rolcanlogin)
 AND NOT EXISTS(SELECT 1 FROM pg_roles reachable
 WHERE pg_has_role(p_login,reachable.oid,'MEMBER') AND
 (reachable.rolsuper OR reachable.rolbypassrls OR reachable.rolcreaterole
 OR reachable.rolcreatedb OR reachable.rolreplication OR has_function_privilege(
 reachable.oid,'emailmonitor.establish_session(text,text,text,text)','EXECUTE')))
$$;

-- Stored-row validity is independent of the connection that inspects it. Fair
-- admission must be able to discard stale tickets for any principal. This
-- function is private: validity is NOT proof of caller authentication.
CREATE FUNCTION emailmonitor.service_delegation_current(p_org uuid,p_id uuid)
 RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(EXISTS(
 SELECT 1 FROM emailmonitor.service_delegations d
 JOIN emailmonitor.service_principals sp
 ON sp.organization_id=d.organization_id AND sp.id=d.principal_id
 JOIN pg_roles login ON login.oid=sp.login_oid AND login.rolname=sp.login_name
 JOIN emailmonitor.organizations o ON o.id=d.organization_id
 JOIN emailmonitor.identities i ON i.id=d.initiator_id
 JOIN emailmonitor.memberships m
 ON m.organization_id=d.organization_id AND m.identity_id=d.initiator_id
 JOIN emailmonitor.sessions s ON s.token_hash=d.origin_session_hash
 AND s.identity_id=d.initiator_id
 JOIN emailmonitor.source_policy_heads h
 ON h.organization_id=d.organization_id AND h.source_id=d.source_id
 AND h.current_version=d.policy_version
 JOIN emailmonitor.source_policies p
 ON p.organization_id=h.organization_id AND p.source_id=h.source_id
 AND p.version=h.current_version
 JOIN emailmonitor.source_catalog catalog ON catalog.source_id=d.source_id
 WHERE d.organization_id=p_org AND d.id=p_id
 AND sp.active AND sp.revision=d.principal_revision
 AND emailmonitor.service_login_safe(login.oid)
 AND login.rolcanlogin AND NOT login.rolsuper AND NOT login.rolbypassrls
 AND NOT login.rolcreaterole AND NOT login.rolcreatedb AND NOT login.rolreplication
 AND NOT has_function_privilege(login.oid,
 'emailmonitor.establish_session(text,text,text,text)','EXECUTE')
 AND NOT pg_has_role(login.oid,'emailmonitor_owner','MEMBER')
 AND NOT pg_has_role(login.oid,'emailmonitor_owner','SET')
 AND NOT pg_has_role(login.oid,'emailmonitor_runtime','MEMBER')
 AND NOT pg_has_role(login.oid,'emailmonitor_runtime','SET')
 AND NOT pg_has_role(login.oid,'emailmonitor_authenticator','MEMBER')
 AND NOT pg_has_role(login.oid,'emailmonitor_authenticator','SET')
 AND pg_has_role(login.oid,
 CASE sp.kind WHEN 'worker' THEN 'emailmonitor_worker' ELSE 'emailmonitor_publisher' END,'MEMBER')
 AND NOT pg_has_role(login.oid,
 CASE sp.kind WHEN 'worker' THEN 'emailmonitor_publisher' ELSE 'emailmonitor_worker' END,'MEMBER')
 AND o.status='active' AND o.deletion_generation=d.deletion_generation
 AND i.active AND i.permission_revision=d.permission_revision
 AND s.permission_revision=d.permission_revision AND s.revoked_at IS NULL
 -- Natural session expiry is deliberately not a service-work deadline.
 AND m.status='active' AND m.row_version=d.membership_revision
 AND d.revoked_at IS NULL AND d.deadline>clock_timestamp()
 AND p.state='approved' AND p.valid_until>clock_timestamp()
 AND p.policy->>'purpose'='academic_contact_research' AND catalog.enabled
 AND catalog.execution_mode='fixture'
 AND p.policy->'allowed_operations' ? 'extract_contacts'
 AND 'extract_contacts'=ANY(catalog.allowed_operations)
 AND ((d.purpose='extraction' AND m.role IN ('owner','admin','data_steward','operator')
 AND EXISTS(SELECT 1 FROM emailmonitor.jobs j
 JOIN emailmonitor.execution_runs e ON e.organization_id=j.organization_id AND e.job_id=j.id
 WHERE j.organization_id=d.organization_id AND j.id=d.resource_id
 AND j.generation=d.generation AND e.source_id=d.source_id
 AND e.policy_version=d.policy_version AND e.deletion_generation=d.deletion_generation
 AND j.request->>'purpose'='academic_contact_research'
 AND j.state IN ('queued','running','completed','completed_partial','failed')
 AND (m.role<>'operator' OR j.created_by=d.initiator_id)))
 OR (d.purpose='export' AND m.role IN ('owner','admin','data_steward')
 AND p.policy->'allowed_operations' ? 'export_contacts'
 AND COALESCE((p.policy->>'export_contacts_allowed')::boolean,false)
 AND 'export_contacts'=ANY(catalog.allowed_operations)
 AND EXISTS(SELECT 1 FROM emailmonitor.exports e
 WHERE e.organization_id=d.organization_id AND e.id=d.resource_id
 AND e.requested_by=d.initiator_id AND e.generation=d.generation
 AND e.deletion_generation=d.deletion_generation AND e.policy_version=d.policy_version
 AND e.state IN ('queued','running','ready','failed') AND e.expires_at>clock_timestamp())))
 ),false)
$$;

-- Authenticate the actual login as well as the independently stored scope.
CREATE FUNCTION emailmonitor.service_caller_allowed(p_org uuid,p_id uuid,p_kind text)
 RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(EXISTS(
 SELECT 1 FROM emailmonitor.service_delegations d
 JOIN emailmonitor.service_principals sp
 ON sp.organization_id=d.organization_id AND sp.id=d.principal_id
 JOIN pg_roles login ON login.oid=sp.login_oid AND login.rolname=sp.login_name
 WHERE d.organization_id=p_org AND d.id=p_id AND sp.kind=p_kind
 AND login.rolname=session_user
 AND emailmonitor.service_delegation_current(p_org,p_id)),false)
$$;

-- Immutable scope and deadline. Revocation cannot be undone; no UPDATE can
-- silently renew a grant, change its actor, or move it to another work item.
CREATE FUNCTION emailmonitor.guard_service_delegation() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF (to_jsonb(NEW)-'revoked_at') IS DISTINCT FROM (to_jsonb(OLD)-'revoked_at')
 OR OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL
 THEN RAISE EXCEPTION 'SERVICE_AUTHORITY_IMMUTABLE' USING ERRCODE='EM017'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER service_delegation_immutable BEFORE UPDATE ON emailmonitor.service_delegations
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_service_delegation();

CREATE FUNCTION emailmonitor.delegate_service_work(p_org uuid,p_principal uuid,
 p_resource uuid,p_purpose text,p_seconds integer) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE actor uuid; sp emailmonitor.service_principals; member emailmonitor.memberships;
 original emailmonitor.sessions; identity_row emailmonitor.identities;
 job emailmonitor.jobs; run emailmonitor.execution_runs; artifact emailmonitor.exports;
 policy emailmonitor.source_policies; previous emailmonitor.service_delegations;
gen bigint; epoch bigint; v_source text; v_version bigint; started timestamptz;
 resource_expiry timestamptz; wall timestamptz; prior_wall timestamptz;
 stamp timestamptz:=clock_timestamp(); identifier uuid:=gen_random_uuid();
BEGIN
 IF p_seconds IS NULL OR p_seconds NOT BETWEEN 1 AND 21600
 OR p_purpose IS NULL OR p_purpose NOT IN ('extraction','export')
 OR NOT COALESCE(emailmonitor.human_work_tenant_allowed(p_org),false)
 THEN RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 actor:=emailmonitor.job_actor();
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE NOWAIT;
 SELECT * INTO member FROM emailmonitor.memberships
 WHERE organization_id=p_org AND identity_id=actor FOR SHARE NOWAIT;
 SELECT * INTO identity_row FROM emailmonitor.identities WHERE id=actor FOR SHARE NOWAIT;
 SELECT * INTO original FROM emailmonitor.sessions
 WHERE token_hash=current_setting('emailmonitor.session_hash',true) FOR SHARE NOWAIT;
 SELECT * INTO sp FROM emailmonitor.service_principals
 WHERE organization_id=p_org AND id=p_principal FOR SHARE NOWAIT;
 IF sp.id IS NULL OR NOT sp.active OR original.identity_id IS DISTINCT FROM actor
 OR original.revoked_at IS NOT NULL OR original.expires_at<=clock_timestamp()
 OR NOT identity_row.active OR original.permission_revision<>identity_row.permission_revision
 OR member.status<>'active' THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 IF p_purpose='extraction' THEN
 PERFORM emailmonitor.job_permission_fence(p_org,p_resource);
 SELECT * INTO job FROM emailmonitor.jobs
 WHERE organization_id=p_org AND id=p_resource FOR UPDATE;
 SELECT * INTO run FROM emailmonitor.execution_runs
 WHERE organization_id=p_org AND job_id=p_resource;
 IF job.id IS NULL OR run.job_id IS NULL OR job.state NOT IN ('queued','running')
 THEN RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 gen:=job.generation; epoch:=run.deletion_generation; v_source:=run.source_id;
 v_version:=run.policy_version; started:=run.created_at; resource_expiry:=run.expires_at;
 ELSE
 PERFORM emailmonitor.results_fence(p_org,true,actor);
 SELECT * INTO artifact FROM emailmonitor.exports
 WHERE organization_id=p_org AND id=p_resource FOR UPDATE;
 IF artifact.id IS NULL OR artifact.requested_by<>actor OR artifact.state NOT IN ('queued','running')
 THEN RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 gen:=artifact.generation; epoch:=artifact.deletion_generation;
 v_source:='synthetic-publisher'; v_version:=artifact.policy_version;
 started:=artifact.created_at; resource_expiry:=artifact.expires_at;
 END IF;
 SELECT * INTO policy FROM emailmonitor.source_policies
 WHERE organization_id=p_org AND source_id=v_source AND source_policies.version=v_version
 FOR SHARE NOWAIT;
 SELECT * INTO previous FROM emailmonitor.service_delegations
 WHERE organization_id=p_org AND principal_id=p_principal
 AND purpose=p_purpose AND resource_id=p_resource AND generation=gen;
 IF previous.id IS NOT NULL THEN
 IF previous.initiator_id IS DISTINCT FROM actor OR previous.revoked_at IS NOT NULL
 OR NOT emailmonitor.service_delegation_current(p_org,previous.id)
 THEN RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 RETURN previous.id;
 END IF;
 IF p_purpose='export' AND artifact.state<>'queued' THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 -- A generation change on pause/resume cannot renew the original job's wall.
 SELECT min(deadline) INTO prior_wall FROM emailmonitor.service_delegations
 WHERE organization_id=p_org AND purpose=p_purpose AND resource_id=p_resource;
 wall:=LEAST(started+make_interval(secs=>p_seconds),policy.valid_until,resource_expiry,
 COALESCE(prior_wall,'infinity'::timestamptz));
 IF wall IS NULL OR wall<=stamp THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_EXPIRED' USING ERRCODE='EM017'; END IF;
 INSERT INTO emailmonitor.service_delegations VALUES
 (p_org,identifier,p_principal,sp.revision,p_purpose,p_resource,gen,epoch,actor,
 identity_row.permission_revision,member.row_version,original.token_hash,
 v_source,v_version,stamp,wall,NULL);
 IF NOT emailmonitor.service_delegation_current(p_org,identifier) THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 INSERT INTO emailmonitor.service_audit(organization_id,id,principal_id,delegation_id,action)
 VALUES(p_org,gen_random_uuid(),p_principal,identifier,'delegated');
 RETURN identifier;
END $$;

CREATE FUNCTION emailmonitor.revoke_service_work(p_org uuid,p_id uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE delegation emailmonitor.service_delegations;
BEGIN
 IF NOT COALESCE(emailmonitor.human_work_tenant_allowed(p_org),false) THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 SELECT * INTO delegation FROM emailmonitor.service_delegations
 WHERE organization_id=p_org AND id=p_id FOR UPDATE;
 IF delegation.id IS NULL OR (delegation.initiator_id IS DISTINCT FROM emailmonitor.job_actor()
 AND emailmonitor.session_role(p_org) IS DISTINCT FROM 'owner') THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 IF delegation.revoked_at IS NOT NULL THEN RETURN; END IF;
 UPDATE emailmonitor.service_delegations SET revoked_at=clock_timestamp()
 WHERE organization_id=p_org AND id=p_id;
 INSERT INTO emailmonitor.service_audit(organization_id,id,principal_id,delegation_id,action)
 VALUES(p_org,gen_random_uuid(),delegation.principal_id,p_id,'revoked');
END $$;

-- Locks are held only for a short transaction, never across source acquisition.
-- An explicit logout waits for earlier authorized transactions; after it commits,
-- every later protected release/commit sees the retained anchor revoked.
CREATE FUNCTION emailmonitor.service_authority_fence(p_org uuid,p_id uuid,p_kind text)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
DECLARE delegation emailmonitor.service_delegations;
BEGIN
 IF NOT emailmonitor.service_schema_ready()
 OR NOT emailmonitor.service_caller_allowed(p_org,p_id,p_kind) THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 SELECT * INTO delegation FROM emailmonitor.service_delegations
 WHERE organization_id=p_org AND id=p_id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.service_principals
 WHERE organization_id=p_org AND id=delegation.principal_id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.memberships
 WHERE organization_id=p_org AND identity_id=delegation.initiator_id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.identities WHERE id=delegation.initiator_id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.sessions
 WHERE token_hash=delegation.origin_session_hash FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.source_catalog WHERE source_id=delegation.source_id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.source_policy_heads
 WHERE organization_id=p_org AND source_id=delegation.source_id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.source_policies
 WHERE organization_id=p_org AND source_id=delegation.source_id
 AND version=delegation.policy_version FOR SHARE NOWAIT;
 IF NOT emailmonitor.service_caller_allowed(p_org,p_id,p_kind) THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
END $$;

CREATE FUNCTION emailmonitor.service_begin(p_org uuid,p_resource uuid,p_purpose text,
 p_generation bigint,p_kind text,p_principal uuid) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE identifier uuid;
BEGIN
 -- The caller cannot carry human authentication into a service transaction.
 PERFORM set_config('emailmonitor.session_hash','',true);
 PERFORM set_config('emailmonitor.lifecycle_recovery','false',true);
 PERFORM set_config('emailmonitor.service_delegation','',true);
 PERFORM set_config('emailmonitor.service_kind','',true);
 PERFORM set_config('emailmonitor.organization_id','',true);
 SELECT d.id INTO identifier FROM emailmonitor.service_delegations d
 WHERE d.organization_id=p_org AND d.resource_id=p_resource AND d.purpose=p_purpose
 AND d.generation=p_generation AND d.principal_id=p_principal;
 IF identifier IS NULL THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 PERFORM emailmonitor.service_authority_fence(p_org,identifier,p_kind);
 PERFORM set_config('emailmonitor.organization_id',p_org::text,true);
 PERFORM set_config('emailmonitor.service_delegation',identifier::text,true);
 PERFORM set_config('emailmonitor.service_kind',p_kind,true);
 INSERT INTO emailmonitor.service_audit(organization_id,id,principal_id,delegation_id,action)
 VALUES(p_org,gen_random_uuid(),p_principal,identifier,'transaction');
 RETURN identifier;
END $$;

CREATE FUNCTION emailmonitor.service_scope_allowed(p_org uuid,p_resource uuid,
 p_purpose text,p_kind text DEFAULT 'worker') RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(
 current_setting('emailmonitor.organization_id',true)=p_org::text
 AND COALESCE(current_setting('emailmonitor.session_hash',true),'')=''
 AND current_setting('emailmonitor.service_kind',true)=p_kind
 AND EXISTS(SELECT 1 FROM emailmonitor.service_delegations d
 WHERE d.organization_id=p_org AND d.id=
 nullif(current_setting('emailmonitor.service_delegation',true),'')::uuid
 AND d.resource_id=p_resource AND d.purpose=p_purpose
 AND emailmonitor.service_caller_allowed(p_org,d.id,p_kind)),false)
$$;

CREATE FUNCTION emailmonitor.service_end(p_org uuid,p_resource uuid,p_purpose text,
 p_kind text) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE identifier uuid;
BEGIN
 IF NOT emailmonitor.service_scope_allowed(p_org,p_resource,p_purpose,p_kind) THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 identifier:=nullif(current_setting('emailmonitor.service_delegation',true),'')::uuid;
 PERFORM emailmonitor.service_authority_fence(p_org,identifier,p_kind);
END $$;

-- These helpers do not turn service principals into human tenant roles.
CREATE FUNCTION emailmonitor.service_selected(p_org uuid,p_kind text DEFAULT 'worker')
 RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(current_setting('emailmonitor.organization_id',true)=p_org::text
 AND COALESCE(current_setting('emailmonitor.session_hash',true),'')=''
 AND current_setting('emailmonitor.service_kind',true)=p_kind
 AND emailmonitor.service_caller_allowed(p_org,
 nullif(current_setting('emailmonitor.service_delegation',true),'')::uuid,p_kind),false)
$$;
CREATE FUNCTION emailmonitor.service_job_visible(p_org uuid,p_job uuid)
 RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.service_selected(p_org) AND EXISTS(
 SELECT 1 FROM emailmonitor.service_delegations d
 WHERE d.organization_id=p_org AND d.id=
 nullif(current_setting('emailmonitor.service_delegation',true),'')::uuid
 AND ((d.purpose='extraction' AND d.resource_id=p_job)
 OR (d.purpose='export' AND (
 EXISTS(SELECT 1 FROM emailmonitor.export_outcomes e WHERE e.organization_id=p_org
 AND e.export_id=d.resource_id AND e.job_id=p_job)
 OR EXISTS(SELECT 1 FROM emailmonitor.export_members e
 JOIN emailmonitor.association_batches b
 ON b.organization_id=e.organization_id AND b.id=e.batch_id
 WHERE e.organization_id=p_org AND e.export_id=d.resource_id AND b.job_id=p_job)))))
$$;
CREATE FUNCTION emailmonitor.service_batch_visible(p_org uuid,p_batch uuid)
 RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.service_selected(p_org) AND EXISTS(
 SELECT 1 FROM emailmonitor.service_delegations d
 JOIN emailmonitor.association_batches b ON b.organization_id=d.organization_id
 WHERE d.organization_id=p_org AND b.id=p_batch AND d.id=
 nullif(current_setting('emailmonitor.service_delegation',true),'')::uuid
 AND ((d.purpose='extraction' AND d.resource_id=b.job_id)
 OR (d.purpose='export' AND EXISTS(SELECT 1 FROM emailmonitor.export_members e
 WHERE e.organization_id=p_org AND e.export_id=d.resource_id AND e.batch_id=b.id))))
$$;
CREATE FUNCTION emailmonitor.work_tenant_allowed(p_org uuid)
 RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(emailmonitor.human_work_tenant_allowed(p_org),false)
 OR emailmonitor.service_selected(p_org)
$$;
CREATE FUNCTION emailmonitor.work_actor(p_org uuid)
 RETURNS uuid LANGUAGE sql VOLATILE SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
 SELECT CASE WHEN emailmonitor.service_selected(p_org) THEN
 (SELECT initiator_id FROM emailmonitor.service_delegations
 WHERE organization_id=p_org AND id=
 nullif(current_setting('emailmonitor.service_delegation',true),'')::uuid)
 ELSE emailmonitor.job_actor() END
$$;
CREATE FUNCTION emailmonitor.work_authority_current(p_org uuid)
 RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.service_selected(p_org) OR (emailmonitor.human_work_tenant_allowed(p_org) AND EXISTS(
 SELECT 1 FROM emailmonitor.sessions s JOIN emailmonitor.identities i ON i.id=s.identity_id
 WHERE s.token_hash=current_setting('emailmonitor.session_hash',true)
 AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp()
 AND i.active AND i.permission_revision=s.permission_revision))
$$;
CREATE FUNCTION emailmonitor.work_authority_fence(p_org uuid)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF emailmonitor.service_selected(p_org) THEN
 PERFORM emailmonitor.service_authority_fence(p_org,
 nullif(current_setting('emailmonitor.service_delegation',true),'')::uuid,'worker');
 ELSE
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.memberships WHERE organization_id=p_org
 AND identity_id=emailmonitor.job_actor() FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.identities WHERE id=emailmonitor.job_actor() FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.sessions
 WHERE token_hash=current_setting('emailmonitor.session_hash',true) FOR SHARE NOWAIT;
 END IF;
 IF NOT emailmonitor.work_tenant_allowed(p_org)
 OR NOT emailmonitor.work_authority_current(p_org) THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
END $$;


ALTER TABLE emailmonitor.admission_requests ALTER COLUMN session_hash DROP NOT NULL;
ALTER TABLE emailmonitor.admission_requests ADD COLUMN service_delegation uuid;
ALTER TABLE emailmonitor.admission_requests ADD CONSTRAINT admission_authority_xor
 CHECK((session_hash IS NULL)<>(service_delegation IS NULL));
ALTER TABLE emailmonitor.admission_requests ADD CONSTRAINT admission_service_scope
 FOREIGN KEY(organization_id,service_delegation)
 REFERENCES emailmonitor.service_delegations(organization_id,id);
ALTER TABLE emailmonitor.source_resource_requests ALTER COLUMN session_hash DROP NOT NULL;
ALTER TABLE emailmonitor.source_resource_requests ADD COLUMN service_delegation uuid;
ALTER TABLE emailmonitor.source_resource_requests ADD CONSTRAINT source_resource_authority_xor
 CHECK((session_hash IS NULL)<>(service_delegation IS NULL));
ALTER TABLE emailmonitor.source_resource_requests ADD CONSTRAINT source_resource_service_scope
 FOREIGN KEY(organization_id,service_delegation)
 REFERENCES emailmonitor.service_delegations(organization_id,id);

CREATE FUNCTION emailmonitor.authority_row_current(p_org uuid,p_actor uuid,p_session text,p_grant uuid)
 RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
 SELECT CASE WHEN p_grant IS NULL THEN p_session IS NOT NULL AND EXISTS(
 SELECT 1 FROM emailmonitor.memberships m JOIN emailmonitor.identities i ON i.id=m.identity_id
 JOIN emailmonitor.sessions s ON s.identity_id=i.id AND s.token_hash=p_session
 JOIN emailmonitor.organizations o ON o.id=m.organization_id
 WHERE m.organization_id=p_org AND m.identity_id=p_actor AND m.status='active'
 AND m.role IN ('owner','admin','data_steward','operator') AND i.active AND o.status='active'
 AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp()
 AND s.permission_revision=i.permission_revision)
 ELSE p_session IS NULL AND emailmonitor.service_delegation_current(p_org,p_grant)
 AND EXISTS(SELECT 1 FROM emailmonitor.service_delegations d
 JOIN emailmonitor.service_principals sp ON sp.organization_id=d.organization_id AND sp.id=d.principal_id
 WHERE d.organization_id=p_org AND d.id=p_grant AND d.initiator_id=p_actor AND sp.kind='worker') END
$$;
CREATE FUNCTION emailmonitor.admission_authority_current(a emailmonitor.admission_requests)
 RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.authority_row_current(a.organization_id,a.actor_id,a.session_hash,a.service_delegation)
 AND (a.pool<>'export' OR EXISTS(SELECT 1 FROM emailmonitor.memberships m
 WHERE m.organization_id=a.organization_id AND m.identity_id=a.actor_id
 AND m.status='active' AND m.role IN ('owner','admin','data_steward')))
 AND (a.service_delegation IS NULL OR EXISTS(
 SELECT 1 FROM emailmonitor.service_delegations d
 WHERE d.organization_id=a.organization_id AND d.id=a.service_delegation AND d.generation=a.generation
 AND ((a.pool='export' AND d.purpose='export' AND d.resource_id=a.reference_id AND a.job_id IS NULL)
 OR (a.pool<>'export' AND d.purpose='extraction' AND d.resource_id=a.job_id))))
$$;
CREATE FUNCTION emailmonitor.work_ticket_owned(p_org uuid,p_actor uuid,p_session text,p_grant uuid)
 RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
 SELECT CASE WHEN p_grant IS NULL THEN
 p_session=current_setting('emailmonitor.session_hash',true) AND p_actor=emailmonitor.job_actor()
 ELSE p_session IS NULL AND emailmonitor.service_selected(p_org)
 AND p_grant=nullif(current_setting('emailmonitor.service_delegation',true),'')::uuid
 AND p_actor=emailmonitor.work_actor(p_org) END
$$;
CREATE FUNCTION emailmonitor.work_admission_scope(p_org uuid,p_job uuid,p_reference uuid,p_pool text)
 RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(emailmonitor.human_work_tenant_allowed(p_org),false) OR CASE WHEN p_pool='export'
 THEN p_job IS NULL AND emailmonitor.service_scope_allowed(p_org,p_reference,'export')
 ELSE p_job IS NOT NULL AND emailmonitor.service_scope_allowed(p_org,p_job,'extraction') END
$$;

-- Existing policy/provenance predicates preserved; only explicit authority
-- alternatives are added. Human authentication helpers remain unchanged.
CREATE OR REPLACE FUNCTION emailmonitor.privacy_source_allowed(p_org uuid) RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(emailmonitor.work_tenant_allowed(p_org),false) AND NOT EXISTS(SELECT 1 FROM emailmonitor.deletion_tombstones WHERE organization_id=p_org AND job_id IS NULL)
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.privacy_suppressions WHERE organization_id=p_org AND active AND kind='source'
 AND digest=emailmonitor.privacy_digest(p_org,'source','synthetic-publisher'))
$$;

CREATE OR REPLACE FUNCTION emailmonitor.privacy_excerpt_allowed(p_org uuid,p_observed timestamptz,p_document jsonb) RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(emailmonitor.work_tenant_allowed(p_org),false) AND NOT EXISTS(SELECT 1 FROM emailmonitor.lifecycle_configuration c
 WHERE c.organization_id=p_org AND jsonb_path_exists(p_document,'$.**.excerpt ? (@ != "")')
 AND p_observed+make_interval(days=>(c.retention->>'excerpt_days')::integer)<=clock_timestamp())
$$;

CREATE OR REPLACE FUNCTION emailmonitor.job_write_allowed(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.privacy_job_allowed(p_org,p_job) AND (emailmonitor.service_scope_allowed(p_org,p_job,'extraction') OR (emailmonitor.human_work_tenant_allowed(p_org) AND EXISTS(SELECT 1 FROM emailmonitor.jobs j
 WHERE j.organization_id=p_org AND j.id=p_job AND
 (emailmonitor.session_role(p_org) IN ('owner','admin','data_steward') OR
  (emailmonitor.session_role(p_org)='operator' AND j.created_by=emailmonitor.job_actor())))))
$$;

CREATE OR REPLACE FUNCTION emailmonitor.job_permission_fence(p_org uuid,p_job uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE actor uuid; source text;
BEGIN
 IF NOT emailmonitor.privacy_job_allowed(p_org,p_job) THEN RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 IF NOT COALESCE(emailmonitor.job_write_allowed(p_org,p_job),false) THEN
 RAISE EXCEPTION 'JOB_UNAVAILABLE'; END IF;
 PERFORM emailmonitor.work_authority_fence(p_org);
 actor=emailmonitor.work_actor(p_org);
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE;
 PERFORM 1 FROM emailmonitor.memberships WHERE organization_id=p_org AND identity_id=actor FOR SHARE;
 PERFORM 1 FROM emailmonitor.identities WHERE id=actor FOR SHARE;
 PERFORM 1 FROM emailmonitor.sessions WHERE token_hash=current_setting('emailmonitor.session_hash',true) FOR SHARE;
 SELECT source_id INTO source FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 IF source IS NOT NULL THEN
 PERFORM 1 FROM emailmonitor.source_catalog WHERE source_id=source FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policy_heads WHERE organization_id=p_org AND source_id=source FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policies p JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
 WHERE p.organization_id=p_org AND p.source_id=source AND p.version=h.current_version FOR SHARE OF p;
 END IF;
 IF NOT COALESCE(emailmonitor.job_write_allowed(p_org,p_job),false) OR NOT emailmonitor.work_authority_current(p_org) THEN RAISE EXCEPTION 'JOB_UNAVAILABLE'; END IF;
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.execution_read_allowed(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT (COALESCE(emailmonitor.human_work_tenant_allowed(p_org),false) OR emailmonitor.service_job_visible(p_org,p_job)) AND emailmonitor.privacy_job_allowed(p_org,p_job) AND COALESCE(emailmonitor.work_tenant_allowed(p_org),false) AND EXISTS(
 SELECT 1 FROM emailmonitor.jobs j JOIN emailmonitor.discovery d
 ON d.organization_id=j.organization_id AND d.job_id=j.id
 JOIN emailmonitor.organizations o ON o.id=j.organization_id
 JOIN emailmonitor.source_policy_heads h ON h.organization_id=d.organization_id AND h.source_id=d.source_id
 JOIN emailmonitor.source_policies p ON p.organization_id=h.organization_id AND p.source_id=h.source_id AND p.version=h.current_version
 JOIN emailmonitor.source_catalog s ON s.source_id=p.source_id
 LEFT JOIN emailmonitor.execution_runs r ON r.organization_id=j.organization_id AND r.job_id=j.id
 WHERE j.organization_id=p_org AND j.id=p_job AND j.kind='extraction' AND o.status='active'
 AND d.deletion_generation=o.deletion_generation AND p.version=d.policy_version
 AND (r.job_id IS NULL OR (r.policy_version=p.version AND r.deletion_generation=o.deletion_generation AND r.expires_at>statement_timestamp()))
 AND p.state='approved' AND p.valid_until>statement_timestamp() AND s.enabled
 AND j.request->>'purpose'=p.policy->>'purpose'
 AND p.policy->'allowed_operations' ? emailmonitor.fixture_acquisition_operation(d.plan->>'start_url') AND p.policy->'allowed_operations' ? 'extract_contacts'
 AND emailmonitor.fixture_acquisition_operation(d.plan->>'start_url')=ANY(s.allowed_operations) AND 'extract_contacts'=ANY(s.allowed_operations)
 AND 'synthetic.publisher.example'=ANY(s.allowed_hosts) AND p.policy->'allowed_hosts' ? 'synthetic.publisher.example'
 AND (p.policy->'retention'->>'contact_days')::integer>0) AND emailmonitor.work_authority_current(p_org)
$$;

CREATE OR REPLACE FUNCTION emailmonitor.association_visible(p_org uuid,p_batch uuid) RETURNS boolean
 LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE b emailmonitor.association_batches;
BEGIN
 IF NOT COALESCE(emailmonitor.human_work_tenant_allowed(p_org),false) AND NOT emailmonitor.service_batch_visible(p_org,p_batch) THEN RETURN false; END IF;
 IF NOT emailmonitor.privacy_job_allowed(p_org,(SELECT job_id FROM emailmonitor.association_batches WHERE organization_id=p_org AND id=p_batch)) THEN RETURN false; END IF;
 IF NOT COALESCE(emailmonitor.work_tenant_allowed(p_org),false) THEN RETURN false; END IF;
 SELECT * INTO b FROM emailmonitor.association_batches WHERE organization_id=p_org AND id=p_batch;
 RETURN b.id IS NOT NULL AND EXISTS(SELECT 1 FROM emailmonitor.article_observations a WHERE a.organization_id=p_org AND a.job_id=b.job_id AND a.article_url=b.article_url AND emailmonitor.privacy_payload_allowed(p_org,a.observation) AND NOT EXISTS(SELECT 1 FROM emailmonitor.lifecycle_configuration c WHERE c.organization_id=p_org AND jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")') AND a.observed_at+make_interval(days=>(c.retention->>'excerpt_days')::integer)<=clock_timestamp())) AND b.sealed AND b.expires_at>statement_timestamp() AND emailmonitor.work_authority_current(p_org) AND EXISTS(
 SELECT 1 FROM emailmonitor.article_observations a JOIN emailmonitor.jobs j ON j.organization_id=a.organization_id AND j.id=a.job_id
 JOIN emailmonitor.organizations o ON o.id=a.organization_id
 JOIN emailmonitor.source_policy_heads h ON h.organization_id=a.organization_id AND h.source_id=a.source_id
 JOIN emailmonitor.source_policies p ON p.organization_id=h.organization_id AND p.source_id=h.source_id AND p.version=h.current_version
 JOIN emailmonitor.source_catalog s ON s.source_id=p.source_id
 WHERE a.organization_id=p_org AND a.job_id=b.job_id AND a.article_url=b.article_url
 AND a.revision=b.source_revision AND a.policy_version=b.policy_version
 AND a.generation=b.generation AND j.kind='extraction' AND j.kind='extraction'
 AND a.deletion_generation=b.deletion_generation AND o.deletion_generation=b.deletion_generation AND o.status='active'
 AND a.expires_at>statement_timestamp() AND s.enabled AND p.state='approved' AND p.valid_until>statement_timestamp()
 AND p.version=b.policy_version AND a.policy_version=b.policy_version
 AND j.request->>'purpose'=p.policy->>'purpose' AND p.policy->'allowed_operations' ? 'extract_contacts'
 AND 'extract_contacts'=ANY(s.allowed_operations) AND 'synthetic.publisher.example'=ANY(s.allowed_hosts)
 AND p.policy->'allowed_hosts' ? 'synthetic.publisher.example'
 AND s.support->'routes_by_operation'->'extract_contacts' ? replace(b.article_url,'https://synthetic.publisher.example','')
 AND (p.policy->'retention'->>'contact_days')::integer>0
 AND (a.observation->>'route'<>'article_xml' OR (p.policy->'allowed_operations' ? 'fetch_xml' AND 'fetch_xml'=ANY(s.allowed_operations)))
 AND (a.observation->>'route'<>'browser_dom' OR (p.policy->'allowed_operations' ? 'browser' AND 'browser'=ANY(s.allowed_operations)))
 AND (NOT jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")') OR (
 p.policy->'allowed_operations' ? 'retain_excerpt' AND 'retain_excerpt'=ANY(s.allowed_operations) AND (p.policy->'retention'->>'excerpt_days')::integer>0)));
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.execution_read_fence(p_org uuid,p_job uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE actor uuid;
BEGIN
 IF NOT COALESCE(emailmonitor.execution_read_allowed(p_org,p_job),false) THEN
 RAISE EXCEPTION 'EXECUTION_SCOPE_DENIED' USING ERRCODE='EM010'; END IF;
 PERFORM emailmonitor.work_authority_fence(p_org);
 actor:=emailmonitor.work_actor(p_org);
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE;
 PERFORM 1 FROM emailmonitor.identities WHERE id=actor FOR SHARE;
 PERFORM 1 FROM emailmonitor.sessions WHERE token_hash=current_setting('emailmonitor.session_hash',true) FOR SHARE;
 PERFORM 1 FROM emailmonitor.memberships WHERE organization_id=p_org AND identity_id=actor FOR SHARE;
 PERFORM 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR SHARE;
 PERFORM 1 FROM emailmonitor.execution_runs WHERE organization_id=p_org AND job_id=p_job FOR SHARE;
 PERFORM 1 FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_catalog WHERE source_id='synthetic-publisher' FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policy_heads WHERE organization_id=p_org AND source_id='synthetic-publisher' FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policies p JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
 WHERE p.organization_id=p_org AND p.source_id='synthetic-publisher' AND p.version=h.current_version FOR SHARE OF p;
 IF NOT COALESCE(emailmonitor.execution_read_allowed(p_org,p_job),false) OR NOT emailmonitor.work_authority_current(p_org) THEN
 RAISE EXCEPTION 'EXECUTION_SCOPE_DENIED' USING ERRCODE='EM010'; END IF;
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.association_parent_fence(p_org uuid,p_job uuid,p_url text,p_revision bigint,p_write boolean DEFAULT false)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE o emailmonitor.organizations; j emailmonitor.jobs; a emailmonitor.article_observations;
 p emailmonitor.source_policies; h emailmonitor.source_policy_heads; s emailmonitor.source_catalog;
 session_row emailmonitor.sessions; identity_row emailmonitor.identities;
BEGIN
 IF NOT COALESCE(emailmonitor.human_work_tenant_allowed(p_org),false) AND
 NOT emailmonitor.service_job_visible(p_org,p_job) THEN
 RAISE EXCEPTION 'ASSOCIATION_DENIED' USING ERRCODE='EM009'; END IF;
 PERFORM emailmonitor.work_authority_fence(p_org);
 SELECT * INTO o FROM emailmonitor.organizations WHERE id=p_org FOR SHARE;
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR SHARE;
 SELECT * INTO s FROM emailmonitor.source_catalog WHERE source_id='synthetic-publisher' FOR SHARE;
 SELECT * INTO h FROM emailmonitor.source_policy_heads WHERE organization_id=p_org AND source_id='synthetic-publisher' FOR SHARE;
 SELECT * INTO p FROM emailmonitor.source_policies WHERE organization_id=p_org AND source_id='synthetic-publisher' AND version=h.current_version FOR SHARE;
 SELECT * INTO a FROM emailmonitor.article_observations WHERE organization_id=p_org AND job_id=p_job AND article_url=p_url FOR SHARE;
 IF o.status IS DISTINCT FROM 'active' OR j.id IS NULL OR a.article_url IS NULL
 OR j.kind<>'extraction'
 OR (p_write AND (NOT COALESCE(emailmonitor.execution_write_allowed(p_org,p_job),false)
 OR (j.state='draft' AND j.generation<>a.generation)
 OR (j.state='running' AND NOT EXISTS(SELECT 1 FROM emailmonitor.execution_items i
 WHERE i.organization_id=p_org AND i.job_id=p_job AND i.work_kind='article' AND i.input_url=p_url
 AND i.id::text=current_setting('emailmonitor.execution_item',true)))))
 OR a.deletion_generation<>o.deletion_generation
 OR a.revision<>p_revision OR a.expires_at<=clock_timestamp()
 OR NOT COALESCE(s.enabled,false) OR p.state IS DISTINCT FROM 'approved'
 OR p.valid_until<=clock_timestamp() OR p.version<>a.policy_version
 OR j.request->>'purpose' IS DISTINCT FROM p.policy->>'purpose'
 OR NOT COALESCE(p.policy->'allowed_operations' ? 'extract_contacts',false)
 OR NOT COALESCE('extract_contacts'=ANY(s.allowed_operations),false)
 OR NOT COALESCE('synthetic.publisher.example'=ANY(s.allowed_hosts),false)
 OR NOT COALESCE(p.policy->'allowed_hosts' ? 'synthetic.publisher.example',false)
 OR COALESCE((p.policy->'retention'->>'contact_days')::integer,0)<=0
 OR NOT COALESCE(s.support->'routes_by_operation'->'extract_contacts' ? replace(p_url,'https://synthetic.publisher.example',''),false)
 OR (a.observation->>'route'='browser_dom' AND (NOT COALESCE(p.policy->'allowed_operations' ? 'browser',false) OR NOT COALESCE('browser'=ANY(s.allowed_operations),false)))
 OR (jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")') AND (
 NOT COALESCE(p.policy->'allowed_operations' ? 'retain_excerpt',false) OR NOT COALESCE('retain_excerpt'=ANY(s.allowed_operations),false) OR COALESCE((p.policy->'retention'->>'excerpt_days')::integer,0)<=0))
 THEN RAISE EXCEPTION 'ASSOCIATION_DENIED' USING ERRCODE='EM009'; END IF;
END $$;


-- Admission retains shared fairness/entitlement logic and discriminates stored
-- authority from the caller-specific ticket ownership check.
CREATE OR REPLACE FUNCTION emailmonitor.admission_cleanup() RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE stamp timestamptz:=clock_timestamp();
BEGIN
 -- Caller owns the short shared mutex. Expiry never authorizes a stale work commit.
 DELETE FROM emailmonitor.admission_requests a WHERE a.expires_at<=stamp
 OR (a.state='active' AND a.lease_until<=stamp)
 OR NOT emailmonitor.admission_authority_current(a)
 OR (a.job_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM emailmonitor.jobs j
 WHERE j.organization_id=a.organization_id AND j.id=a.job_id AND j.generation=a.generation
 AND j.state IN ('draft','queued','running')));
 UPDATE emailmonitor.source_resource_requests SET state='finished',nonce=NULL,lease_until=NULL,
 outcome='network_failure' WHERE state='active' AND lease_until<=stamp;
 DELETE FROM emailmonitor.source_resource_requests WHERE expires_at<=stamp AND state<>'active';
 UPDATE emailmonitor.resolution_accounts r SET state='released' WHERE r.state='reserved'
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.execution_items i JOIN emailmonitor.jobs j
 ON j.organization_id=i.organization_id AND j.id=i.job_id WHERE i.organization_id=r.organization_id
 AND i.job_id=r.job_id AND (i.id=r.item_id OR (r.item_id IS NULL
 AND md5(r.organization_id::text||':'||r.root_job_id::text||':article:'||i.input_url)::uuid=r.unit_id))
 AND j.state IN ('queued','running','paused')
 AND i.state IN ('pending','running','retry_wait'))
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.article_observations a JOIN emailmonitor.jobs j
 ON j.organization_id=a.organization_id AND j.id=a.job_id WHERE a.organization_id=r.organization_id
 AND a.job_id=r.job_id AND j.state='draft' AND a.expires_at>stamp
 AND md5(a.organization_id::text||':'||r.root_job_id::text||':article:'||a.article_url)::uuid=r.unit_id);
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.admission_try(p_org uuid,p_job uuid,p_reference uuid,p_pool text,p_generation bigint,p_nonce uuid,p_seconds integer)
 RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE stamp timestamptz:=clock_timestamp(); conf jsonb; saved jsonb; slots integer; active integer;
 pool_state emailmonitor.admission_pools; mine emailmonitor.admission_requests; chosen uuid; ticket uuid;
BEGIN
 IF NOT COALESCE(emailmonitor.work_admission_scope(p_org,p_job,p_reference,p_pool),false) OR p_nonce IS NULL OR p_reference IS NULL
 OR p_generation IS NULL OR p_generation<1 OR p_seconds IS NULL OR p_seconds NOT BETWEEN 1 AND 120
 OR p_pool NOT IN ('fixture_io','parse','export','browser','http') THEN
 RAISE EXCEPTION 'ADMISSION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 PERFORM emailmonitor.work_authority_fence(p_org);
 -- One mutex order serializes metadata admission, not the bounded work itself.
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 stamp:=clock_timestamp();
 PERFORM emailmonitor.admission_cleanup();
 SELECT configuration->'entitlements' INTO conf FROM emailmonitor.tenant_configuration
 WHERE organization_id=p_org FOR SHARE;
 SELECT entitlements INTO saved FROM emailmonitor.job_entitlements WHERE organization_id=p_org AND job_id=p_job;
 IF p_job IS NOT NULL AND saved IS NULL THEN RETURN false; END IF;
 saved:=COALESCE(saved,conf);
 slots:=CASE p_pool WHEN 'export' THEN least((conf->>'max_parallel_export')::integer,(saved->>'max_parallel_export')::integer)
 WHEN 'browser' THEN least((conf->>'max_parallel_browser')::integer,(saved->>'max_parallel_browser')::integer)
 ELSE least((conf->>'max_parallel_parse')::integer,(saved->>'max_parallel_parse')::integer) END;
 IF slots IS NULL OR slots=0 OR (p_pool='export' AND NOT ((conf->>'exports_enabled')::boolean AND (saved->>'exports_enabled')::boolean))
 OR (p_pool='browser' AND NOT ((conf->>'browser_enabled')::boolean AND (saved->>'browser_enabled')::boolean)) THEN RETURN false; END IF;
 SELECT * INTO pool_state FROM emailmonitor.admission_pools WHERE admission_pools.pool=p_pool FOR UPDATE;
 ticket:=md5(p_org::text||':'||p_pool||':'||p_reference::text||':'||p_generation::text)::uuid;
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.admission_requests WHERE organization_id=p_org AND id=ticket)
 AND ((SELECT count(*) FROM emailmonitor.admission_requests WHERE organization_id=p_org)>=500
 OR (SELECT count(*) FROM emailmonitor.admission_requests)>=10000) THEN RETURN false; END IF;
 INSERT INTO emailmonitor.admission_requests(organization_id,id,pool,actor_id,session_hash,service_delegation,job_id,reference_id,generation,expires_at,state)
 VALUES(p_org,ticket,p_pool,emailmonitor.work_actor(p_org),nullif(current_setting('emailmonitor.session_hash',true),''),nullif(current_setting('emailmonitor.service_delegation',true),'')::uuid,p_job,p_reference,p_generation,stamp+interval '120 seconds','waiting')
 ON CONFLICT(organization_id,pool,reference_id,generation) DO UPDATE SET heartbeat_at=stamp,actor_id=EXCLUDED.actor_id,session_hash=EXCLUDED.session_hash,service_delegation=EXCLUDED.service_delegation
 WHERE admission_requests.state='waiting' AND admission_requests.service_delegation IS NOT DISTINCT FROM EXCLUDED.service_delegation;
 SELECT * INTO mine FROM emailmonitor.admission_requests WHERE organization_id=p_org AND id=ticket;
 IF mine.state<>'waiting' OR NOT emailmonitor.work_ticket_owned(p_org,mine.actor_id,mine.session_hash,mine.service_delegation) THEN RETURN false; END IF;
 SELECT count(*) INTO active FROM emailmonitor.admission_requests WHERE admission_requests.pool=p_pool AND state='active';
 IF active>=pool_state.maximum OR (SELECT count(*) FROM emailmonitor.admission_requests
 WHERE organization_id=p_org AND admission_requests.pool=p_pool AND state='active')>=slots THEN RETURN false; END IF;
 SELECT a.id INTO chosen FROM emailmonitor.admission_requests a
 JOIN emailmonitor.organizations o ON o.id=a.organization_id AND o.status='active'
 JOIN emailmonitor.tenant_configuration c ON c.organization_id=a.organization_id
 LEFT JOIN emailmonitor.job_entitlements captured ON captured.organization_id=a.organization_id AND captured.job_id=a.job_id
 LEFT JOIN emailmonitor.export_entitlements exported ON p_pool='export' AND exported.organization_id=a.organization_id AND exported.export_id=a.reference_id
 WHERE a.pool=p_pool AND a.state='waiting' AND a.expires_at>stamp
 AND emailmonitor.admission_authority_current(a)
 AND a.heartbeat_at>=stamp-interval '5 seconds'
 AND (a.job_id IS NULL OR captured.job_id IS NOT NULL)
 AND (p_pool<>'export' OR ((c.configuration->'entitlements'->>'exports_enabled')::boolean
 AND (COALESCE(exported.entitlements,captured.entitlements,c.configuration->'entitlements')->>'exports_enabled')::boolean))
 AND (p_pool<>'browser' OR ((c.configuration->'entitlements'->>'browser_enabled')::boolean
 AND (COALESCE(captured.entitlements,c.configuration->'entitlements')->>'browser_enabled')::boolean))
 AND (a.job_id IS NULL OR EXISTS(SELECT 1 FROM emailmonitor.jobs j
 JOIN emailmonitor.discovery d ON d.organization_id=j.organization_id AND d.job_id=j.id
 LEFT JOIN emailmonitor.execution_runs r ON r.organization_id=j.organization_id AND r.job_id=j.id
 JOIN emailmonitor.source_policy_heads h ON h.organization_id=d.organization_id AND h.source_id=d.source_id
 JOIN emailmonitor.source_policies policy ON policy.organization_id=h.organization_id AND policy.source_id=h.source_id AND policy.version=h.current_version
 JOIN emailmonitor.memberships membership ON membership.organization_id=j.organization_id AND membership.identity_id=a.actor_id
 JOIN emailmonitor.identities actor ON actor.id=membership.identity_id
 JOIN emailmonitor.source_catalog catalog ON catalog.source_id=d.source_id
 WHERE j.organization_id=a.organization_id AND j.id=a.job_id AND j.generation=a.generation
 AND j.state IN ('draft','queued','running') AND membership.status='active' AND actor.active
 AND catalog.enabled AND policy.policy->'allowed_operations' ? emailmonitor.fixture_acquisition_operation(d.plan->>'start_url')
 AND (p_pool IN ('fixture_io','http') OR policy.policy->'allowed_operations' ? 'extract_contacts')
 AND j.request->>'purpose'=policy.policy->>'purpose'
 AND membership.role IN ('owner','admin','data_steward','operator')
 AND policy.state='approved' AND policy.valid_until>stamp AND policy.version=d.policy_version
 AND (r.job_id IS NULL OR r.policy_version=d.policy_version)))
 AND (SELECT count(*) FROM emailmonitor.admission_requests live WHERE live.organization_id=a.organization_id
 AND live.pool=p_pool AND live.state='active')<CASE p_pool WHEN 'export' THEN least((c.configuration->'entitlements'->>'max_parallel_export')::integer,
 (COALESCE(exported.entitlements,captured.entitlements,c.configuration->'entitlements')->>'max_parallel_export')::integer)
 WHEN 'browser' THEN least((c.configuration->'entitlements'->>'max_parallel_browser')::integer,
 (COALESCE(captured.entitlements,c.configuration->'entitlements')->>'max_parallel_browser')::integer)
 ELSE least((c.configuration->'entitlements'->>'max_parallel_parse')::integer,
 (COALESCE(captured.entitlements,c.configuration->'entitlements')->>'max_parallel_parse')::integer) END
 ORDER BY (a.organization_id IS NOT DISTINCT FROM pool_state.last_organization),a.ordinal LIMIT 1;
 IF chosen IS DISTINCT FROM ticket THEN RETURN false; END IF;
 stamp:=clock_timestamp();
 PERFORM emailmonitor.work_authority_fence(p_org);
 UPDATE emailmonitor.admission_requests SET state='active',nonce=p_nonce,
 lease_until=stamp+make_interval(secs=>p_seconds) WHERE organization_id=p_org AND id=ticket;
 UPDATE emailmonitor.admission_pools SET last_organization=p_org WHERE admission_pools.pool=p_pool;
 UPDATE emailmonitor.admission_mutex SET acquired=acquired+1 WHERE id;
 RETURN true;
END $$;


-- Resource and persistence paths keep their policy, quota, generation, lease
-- and provenance predicates; stored service tickets are not human sessions.
CREATE FUNCTION emailmonitor.work_execution_allowed(p_org uuid,p_job uuid)
 RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT (COALESCE(emailmonitor.human_work_tenant_allowed(p_org),false) AND COALESCE(emailmonitor.session_role(p_org)
 IN ('owner','admin','data_steward','operator'),false))
 OR (p_job IS NOT NULL AND emailmonitor.service_scope_allowed(p_org,p_job,'extraction'))
$$;

CREATE OR REPLACE FUNCTION emailmonitor.privacy_source_state(p_org uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT NOT EXISTS(SELECT 1 FROM emailmonitor.deletion_tombstones WHERE organization_id=p_org AND job_id IS NULL)
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.privacy_suppressions WHERE organization_id=p_org AND active AND kind='source'
 AND digest=emailmonitor.privacy_digest(p_org,'source','synthetic-publisher'))
$$;

CREATE OR REPLACE FUNCTION emailmonitor.privacy_job_state(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.privacy_source_state(p_org) AND NOT EXISTS(SELECT 1 FROM emailmonitor.lifecycle_job_deadlines d WHERE d.organization_id=p_org AND d.job_id=p_job
 AND (d.contact_deadline<=clock_timestamp() OR (d.excerpt_deadline<=clock_timestamp() AND EXISTS(SELECT 1 FROM emailmonitor.article_observations a WHERE a.organization_id=p_org AND a.job_id=p_job AND jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")'))))) AND NOT EXISTS(
 SELECT 1 FROM emailmonitor.deletion_tombstones WHERE organization_id=p_org AND job_id=p_job)
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.article_observations a JOIN emailmonitor.lifecycle_configuration c ON c.organization_id=a.organization_id
 JOIN emailmonitor.source_policies pp ON pp.organization_id=a.organization_id AND pp.source_id=a.source_id AND pp.version=a.policy_version
 WHERE a.organization_id=p_org AND a.job_id=p_job AND jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")')
 AND a.observed_at+make_interval(days=>LEAST((c.retention->>'excerpt_days')::integer,(pp.policy->'retention'->>'excerpt_days')::integer))<=clock_timestamp())
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.jobs j JOIN emailmonitor.lifecycle_configuration c ON c.organization_id=j.organization_id
 LEFT JOIN emailmonitor.discovery d ON d.organization_id=j.organization_id AND d.job_id=j.id
 LEFT JOIN emailmonitor.source_policies p ON p.organization_id=d.organization_id AND p.source_id=d.source_id AND p.version=d.policy_version
 WHERE j.organization_id=p_org AND j.id=p_job AND j.created_at+make_interval(days=>LEAST(
 (c.retention->>'contact_days')::integer,COALESCE((p.policy->'retention'->>'contact_days')::integer,90)))<=clock_timestamp())
$$;

CREATE OR REPLACE FUNCTION emailmonitor.source_resource_current(p_org uuid,p_id uuid) RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.privacy_source_state(p_org) AND NOT EXISTS(SELECT 1 FROM emailmonitor.source_resource_requests rr WHERE rr.organization_id=p_org AND rr.id=p_id AND rr.job_id IS NOT NULL AND NOT emailmonitor.privacy_job_state(p_org,rr.job_id)) AND EXISTS(SELECT 1 FROM emailmonitor.source_resource_requests r
 JOIN emailmonitor.organizations o ON o.id=r.organization_id AND o.status='active'
 JOIN emailmonitor.memberships m ON m.organization_id=r.organization_id AND m.identity_id=r.actor_id
 JOIN emailmonitor.identities i ON i.id=m.identity_id AND i.active
 JOIN emailmonitor.source_policy_heads h ON h.organization_id=r.organization_id AND h.source_id=r.source_id
 JOIN emailmonitor.source_policies p ON p.organization_id=h.organization_id AND p.source_id=h.source_id AND p.version=h.current_version
 JOIN emailmonitor.source_catalog c ON c.source_id=r.source_id AND c.enabled AND c.execution_mode='fixture'
 JOIN emailmonitor.tenant_configuration cfg ON cfg.organization_id=r.organization_id
 WHERE r.organization_id=p_org AND r.id=p_id AND p.version=r.policy_version
 AND r.deletion_generation=o.deletion_generation
 AND m.status='active' AND m.role IN ('owner','admin','data_steward','operator')
 AND emailmonitor.authority_row_current(r.organization_id,r.actor_id,r.session_hash,r.service_delegation)
 AND (r.service_delegation IS NULL OR EXISTS(SELECT 1 FROM emailmonitor.service_delegations d
 WHERE d.organization_id=r.organization_id AND d.id=r.service_delegation
 AND d.purpose='extraction' AND d.resource_id=r.job_id AND d.generation=r.generation
 AND d.deletion_generation=r.deletion_generation AND d.policy_version=r.policy_version))
 AND p.state='approved' AND p.valid_until>statement_timestamp() AND p.policy->>'execution_mode'='fixture'
 AND p.policy->'allowed_operations' ? r.operation AND r.operation=ANY(c.allowed_operations)
 AND p.policy->'allowed_hosts' ? 'synthetic.publisher.example' AND 'synthetic.publisher.example'=ANY(c.allowed_hosts)
 AND c.support->'routes_by_operation'->r.operation ? r.path
 AND (cfg.configuration->'entitlements'->>'max_parallel_parse')::integer>0
 AND (r.operation<>'browser' OR ((cfg.configuration->'entitlements'->>'browser_enabled')::boolean
 AND (cfg.configuration->'entitlements'->>'max_parallel_browser')::integer>0))
 AND (r.job_id IS NULL OR EXISTS(SELECT 1 FROM emailmonitor.jobs j JOIN emailmonitor.discovery d
 ON d.organization_id=j.organization_id AND d.job_id=j.id JOIN emailmonitor.job_entitlements e
 ON e.organization_id=j.organization_id AND e.job_id=j.id
 WHERE j.organization_id=r.organization_id AND j.id=r.job_id AND j.state IN ('draft','running')
 AND j.generation=r.generation AND d.generation=j.generation
 AND d.deletion_generation=o.deletion_generation
 AND d.policy_version=r.policy_version AND j.request->>'purpose'=p.policy->>'purpose'
 AND (r.operation<>'browser' OR (e.entitlements->>'browser_enabled')::boolean))))
$$;

CREATE OR REPLACE FUNCTION emailmonitor.source_resource_claim(p_org uuid,p_id uuid,p_job uuid,p_version bigint,
 p_operation text,p_path text,p_nonce uuid,p_seconds integer) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE stamp timestamptz:=clock_timestamp(); mine emailmonitor.source_resource_requests;
 bucket emailmonitor.source_resource_buckets; tenant emailmonitor.tenant_source_buckets;
 spacing double precision; chosen uuid; until_time timestamptz; v_pool text; gen bigint:=1; epoch bigint;
BEGIN
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE NOWAIT;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 IF NOT emailmonitor.work_execution_allowed(p_org,p_job)
 OR p_id IS NULL OR p_nonce IS NULL OR p_version IS NULL OR p_version<1 OR p_operation IS NULL
 OR p_operation NOT IN ('fetch_html','fetch_xml','browser','search') OR p_path IS NULL OR length(p_path)>512
 OR p_seconds IS NULL OR p_seconds NOT BETWEEN 1 AND 60
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 PERFORM emailmonitor.work_authority_fence(p_org);
 IF p_job IS NOT NULL THEN
 PERFORM 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 SELECT generation INTO gen FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 IF NOT COALESCE(emailmonitor.execution_write_allowed(p_org,p_job),false)
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 END IF;
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 stamp:=clock_timestamp();
 PERFORM emailmonitor.admission_cleanup();
 PERFORM 1 FROM emailmonitor.source_catalog WHERE source_id='synthetic-publisher' FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policy_heads WHERE organization_id=p_org AND source_id='synthetic-publisher' FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policies WHERE organization_id=p_org AND source_id='synthetic-publisher' AND version=p_version FOR SHARE;
 PERFORM 1 FROM emailmonitor.tenant_configuration WHERE organization_id=p_org FOR SHARE;
 SELECT deletion_generation INTO epoch FROM emailmonitor.organizations WHERE id=p_org;
 SELECT * INTO mine FROM emailmonitor.source_resource_requests WHERE organization_id=p_org AND id=p_id;
 IF mine.id IS NOT NULL AND (mine.job_id IS DISTINCT FROM p_job OR mine.policy_version<>p_version
 OR mine.operation<>p_operation OR mine.path<>p_path OR mine.generation<>gen OR mine.deletion_generation<>epoch OR NOT emailmonitor.work_ticket_owned(p_org,mine.actor_id,mine.session_hash,mine.service_delegation) OR mine.state='finished')
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 IF mine.id IS NULL AND ((SELECT count(*) FROM emailmonitor.source_resource_requests WHERE organization_id=p_org)>=500
 OR (SELECT count(*) FROM emailmonitor.source_resource_requests)>=10000) THEN
 RETURN jsonb_build_object('admitted',false,'wait_seconds',1.0); END IF;
 INSERT INTO emailmonitor.source_resource_requests(organization_id,id,job_id,actor_id,session_hash,service_delegation,source_id,generation,deletion_generation,policy_version,operation,path,expires_at,state)
 VALUES(p_org,p_id,p_job,emailmonitor.work_actor(p_org),nullif(current_setting('emailmonitor.session_hash',true),''),
 nullif(current_setting('emailmonitor.service_delegation',true),'')::uuid,
 'synthetic-publisher',gen,epoch,p_version,p_operation,p_path,stamp+interval '120 seconds','waiting')
 ON CONFLICT(organization_id,id) DO UPDATE SET heartbeat_at=stamp WHERE source_resource_requests.state='waiting';
 IF NOT COALESCE(emailmonitor.source_resource_current(p_org,p_id),false)
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 IF mine.state='active' THEN
 IF mine.nonce IS DISTINCT FROM p_nonce OR mine.lease_until<=stamp
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 RETURN jsonb_build_object('admitted',true,'wait_seconds',0.0); END IF;
 INSERT INTO emailmonitor.source_resource_buckets(source_id) VALUES('synthetic-publisher') ON CONFLICT DO NOTHING;
 INSERT INTO emailmonitor.tenant_source_buckets(organization_id,source_id) VALUES(p_org,'synthetic-publisher') ON CONFLICT DO NOTHING;
 SELECT * INTO bucket FROM emailmonitor.source_resource_buckets WHERE source_id='synthetic-publisher' FOR UPDATE;
 IF bucket.provider_blocked THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 SELECT * INTO tenant FROM emailmonitor.tenant_source_buckets WHERE organization_id=p_org AND source_id='synthetic-publisher' FOR UPDATE;
 until_time:=greatest(bucket.ready_at,bucket.retry_after_until,tenant.ready_at);
 IF until_time>stamp OR EXISTS(SELECT 1 FROM emailmonitor.source_resource_requests
 WHERE source_id='synthetic-publisher' AND state='active' AND lease_until>stamp) THEN
 RETURN jsonb_build_object('admitted',false,'wait_seconds',greatest(0.05,least(1.0,extract(epoch FROM until_time-stamp)))); END IF;
 SELECT r.id INTO chosen FROM emailmonitor.source_resource_requests r
 WHERE r.source_id='synthetic-publisher' AND r.state='waiting' AND r.expires_at>stamp
 AND r.heartbeat_at>=stamp-interval '5 seconds' AND emailmonitor.source_resource_current(r.organization_id,r.id)
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.tenant_source_buckets t WHERE t.organization_id=r.organization_id
 AND t.source_id=r.source_id AND t.ready_at>stamp)
 ORDER BY (r.organization_id IS NOT DISTINCT FROM bucket.last_organization),r.ordinal LIMIT 1;
 IF chosen IS DISTINCT FROM p_id THEN RETURN jsonb_build_object('admitted',false,'wait_seconds',0.05); END IF;
 v_pool:=CASE p_operation WHEN 'browser' THEN 'browser' ELSE 'http' END;
 -- HTTP uses the same bounded pool metadata; its per-tenant ceiling is parse's2.
 IF NOT emailmonitor.admission_try(p_org,p_job,p_id,v_pool,gen,p_nonce,p_seconds)
 THEN RETURN jsonb_build_object('admitted',false,'wait_seconds',0.05); END IF;
 SELECT greatest(5.0,(policy->'limits'->>'min_request_interval_seconds')::double precision) INTO spacing
 FROM emailmonitor.source_policies WHERE organization_id=p_org AND source_id='synthetic-publisher' AND version=p_version;
 IF spacing IS NULL OR spacing>86400 OR spacing<5 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 IF NOT COALESCE(emailmonitor.source_resource_current(p_org,p_id),false)
 OR NOT COALESCE(emailmonitor.network_entitlement_allowed(p_org,p_operation,p_job),false) THEN
 RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 stamp:=clock_timestamp();
 UPDATE emailmonitor.source_resource_requests SET state='active',nonce=p_nonce,lease_until=stamp+make_interval(secs=>p_seconds)
 WHERE organization_id=p_org AND id=p_id;
 UPDATE emailmonitor.source_resource_buckets SET ready_at=stamp+interval '5 seconds',attempts=attempts+1,last_organization=p_org
 WHERE source_id='synthetic-publisher';
 UPDATE emailmonitor.tenant_source_buckets SET ready_at=stamp+make_interval(secs=>spacing),attempts=attempts+1
 WHERE organization_id=p_org AND source_id='synthetic-publisher';
 RETURN jsonb_build_object('admitted',true,'wait_seconds',0.0);
EXCEPTION WHEN lock_not_available THEN
 RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013';
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.network_entitlement_allowed(p_org uuid,p_operation text,p_job uuid DEFAULT NULL) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE conf jsonb; saved jsonb;
BEGIN
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE NOWAIT;
 IF NOT FOUND THEN RETURN false; END IF;
 IF p_job IS NOT NULL THEN PERFORM 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR SHARE NOWAIT; IF NOT FOUND THEN RETURN false; END IF; END IF;
 IF NOT emailmonitor.privacy_source_allowed(p_org) OR (p_job IS NOT NULL AND NOT emailmonitor.privacy_job_allowed(p_org,p_job)) THEN RETURN false; END IF;
 IF NOT emailmonitor.work_execution_allowed(p_org,p_job)
 OR p_operation IS NULL OR p_operation NOT IN ('fetch_html','fetch_xml','browser','search') THEN RETURN false; END IF;
 PERFORM emailmonitor.work_authority_fence(p_org);
 SELECT configuration->'entitlements' INTO conf FROM emailmonitor.tenant_configuration WHERE organization_id=p_org FOR SHARE;
 IF p_job IS NOT NULL THEN
 SELECT entitlements INTO saved FROM emailmonitor.job_entitlements WHERE organization_id=p_org AND job_id=p_job;
 IF saved IS NULL OR NOT COALESCE(emailmonitor.execution_write_allowed(p_org,p_job),false) THEN RETURN false; END IF;
 ELSE saved:=conf; END IF;
 RETURN conf IS NOT NULL AND least((conf->>'max_parallel_parse')::integer,(saved->>'max_parallel_parse')::integer)>0
 AND (p_operation<>'browser' OR ((conf->>'browser_enabled')::boolean AND (saved->>'browser_enabled')::boolean
 AND least((conf->>'max_parallel_browser')::integer,(saved->>'max_parallel_browser')::integer)>0));
EXCEPTION WHEN lock_not_available THEN RETURN false;
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.fixture_admission_claim(p_org uuid,p_job uuid,p_url text,p_nonce uuid,p_seconds integer)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs; d emailmonitor.discovery; v_pool text; reference uuid; inherited boolean;
BEGIN
 IF NOT emailmonitor.work_execution_allowed(p_org,p_job)
 OR p_url NOT IN ('https://synthetic.publisher.example/search-page-1.html','https://synthetic.publisher.example/search-page-2.html',
 'https://synthetic.publisher.example/article-a.html','https://synthetic.publisher.example/article-b.html',
 'https://synthetic.publisher.example/tooltip.html','https://synthetic.publisher.example/no-contact.html','https://synthetic.publisher.example/article-xml.xml','https://synthetic.publisher.example/provider-search-0.json','https://synthetic.publisher.example/provider-doi.xml','https://synthetic.publisher.example/provider-pii.xml') THEN
 RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR UPDATE;
 SELECT * INTO d FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job;
 IF j.id IS NULL OR d.job_id IS NULL OR j.state NOT IN ('draft','running') THEN
 RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 PERFORM emailmonitor.discovery_source_fence(p_org,p_job,d.policy_version);
 IF NOT (d.checkpoint->'articles' ? p_url) AND NOT (d.checkpoint->'pages' ? p_url)
 AND d.checkpoint->>'next_url' IS DISTINCT FROM p_url THEN
 RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 v_pool:=CASE WHEN d.checkpoint->'articles' ? p_url THEN 'parse' ELSE 'fixture_io' END;
 IF j.state='running' THEN
 inherited:=COALESCE(emailmonitor.execution_write_allowed(p_org,p_job),false) AND EXISTS(
 SELECT 1 FROM emailmonitor.execution_items i WHERE i.organization_id=p_org AND i.job_id=p_job
 AND i.id::text=current_setting('emailmonitor.execution_item',true) AND i.input_url=p_url);
 IF NOT inherited THEN RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 RETURN jsonb_build_object('admitted',true,'inherited',true,'reference',null);
 END IF;
 IF emailmonitor.execution_budget_exhausted(p_org,p_job) THEN
 RETURN jsonb_build_object('admitted',false,'inherited',false,'reference',null); END IF;
 reference:=md5(p_org::text||':'||p_job::text||':fixture:'||p_url)::uuid;
 inherited:=emailmonitor.admission_try(p_org,p_job,reference,v_pool,j.generation,p_nonce,p_seconds);
 RETURN jsonb_build_object('admitted',inherited,'inherited',false,'reference',reference);
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.source_resource_finish(p_org uuid,p_id uuid,p_nonce uuid,p_outcome text,p_retry_seconds integer) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE mine emailmonitor.source_resource_requests; stamp timestamptz:=clock_timestamp();
BEGIN
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE NOWAIT;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 IF NOT COALESCE(emailmonitor.work_tenant_allowed(p_org),false) OR p_outcome IS NULL
 OR p_outcome NOT IN ('response','network_failure','provider_backoff') OR p_retry_seconds IS NULL
 OR p_retry_seconds NOT BETWEEN -1 AND 86400 OR (p_outcome<>'provider_backoff' AND p_retry_seconds<>0)
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 SELECT * INTO mine FROM emailmonitor.source_resource_requests WHERE organization_id=p_org AND id=p_id;
 PERFORM emailmonitor.work_authority_fence(p_org);
 IF mine.job_id IS NOT NULL THEN PERFORM 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=mine.job_id FOR SHARE NOWAIT; END IF;
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 stamp:=clock_timestamp();
 SELECT * INTO mine FROM emailmonitor.source_resource_requests WHERE organization_id=p_org AND id=p_id;
 IF mine.id IS NULL OR NOT emailmonitor.work_ticket_owned(p_org,mine.actor_id,mine.session_hash,mine.service_delegation) OR (mine.state='active' AND mine.nonce IS DISTINCT FROM p_nonce)
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 IF p_outcome<>'network_failure' AND (mine.state IS DISTINCT FROM 'active'
 OR mine.nonce IS DISTINCT FROM p_nonce OR mine.lease_until IS NULL OR mine.lease_until<=stamp
 OR NOT emailmonitor.source_resource_current(p_org,p_id)
 OR NOT emailmonitor.network_entitlement_allowed(p_org,mine.operation,mine.job_id))
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 stamp:=clock_timestamp();
 IF p_outcome<>'network_failure' AND mine.lease_until<=stamp THEN
 RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 IF mine.state='active' AND mine.lease_until>stamp AND p_outcome='provider_backoff' THEN
 UPDATE emailmonitor.source_resource_buckets SET provider_blocked=provider_blocked OR p_retry_seconds=-1,
 retry_after_until=greatest(retry_after_until,stamp+make_interval(secs=>greatest(5,p_retry_seconds)))
 WHERE source_id=mine.source_id;
 END IF;
 DELETE FROM emailmonitor.admission_requests WHERE organization_id=p_org AND reference_id=p_id AND nonce=p_nonce
 AND pool=CASE mine.operation WHEN 'browser' THEN 'browser' ELSE 'http' END;
 UPDATE emailmonitor.source_resource_requests SET state='finished',outcome=p_outcome,nonce=NULL,lease_until=NULL
 WHERE organization_id=p_org AND id=p_id AND state IN ('waiting','active');
EXCEPTION WHEN lock_not_available THEN
 RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013';
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.execution_write_allowed(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs;
BEGIN
 IF NOT COALESCE(emailmonitor.execution_write_allowed_pre_admission(p_org,p_job),false) THEN RETURN false; END IF;
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 -- Initial planning checks source permission before it atomically captures limits.
 -- Observation/admission guards separately require that captured configuration.
 IF j.state='draft' AND NOT EXISTS(SELECT 1 FROM emailmonitor.job_entitlements
 WHERE organization_id=p_org AND job_id=p_job) THEN RETURN true; END IF;
 IF emailmonitor.execution_budget_exhausted(p_org,p_job) THEN RETURN false; END IF;
 IF j.state='draft' THEN RETURN true; END IF;
 RETURN EXISTS(SELECT 1 FROM emailmonitor.admission_requests a WHERE a.organization_id=p_org
 AND a.job_id=p_job AND a.reference_id::text=current_setting('emailmonitor.execution_item',true)
 AND a.generation=j.generation AND a.state='active' AND a.lease_until>clock_timestamp()
 AND a.nonce::text=current_setting('emailmonitor.execution_token',true)
 AND emailmonitor.work_ticket_owned(p_org,a.actor_id,a.session_hash,a.service_delegation));
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.resolution_observation_reserve() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs; root uuid; unit uuid; account emailmonitor.resolution_accounts;
 conf jsonb; saved jsonb; cap integer; article_cap integer; position bigint; units bigint;
 v_period date:=date_trunc('month',clock_timestamp() AT TIME ZONE 'UTC')::date; item uuid;
BEGIN
 IF NOT emailmonitor.work_execution_allowed(NEW.organization_id,NEW.job_id)
 THEN RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 PERFORM emailmonitor.discovery_source_fence(NEW.organization_id,NEW.job_id,NEW.policy_version);
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=NEW.organization_id AND id=NEW.job_id FOR UPDATE;
 IF j.id IS NULL OR j.kind<>'extraction' OR j.state NOT IN ('draft','running') THEN RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 SELECT root_job_id INTO root FROM emailmonitor.execution_runs WHERE organization_id=NEW.organization_id AND job_id=NEW.job_id;
 root:=COALESCE(root,NEW.job_id);
 unit:=md5(NEW.organization_id::text||':'||root::text||':article:'||NEW.article_url)::uuid;
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 SELECT configuration->'entitlements' INTO conf FROM emailmonitor.tenant_configuration
 WHERE organization_id=NEW.organization_id FOR SHARE;
 SELECT entitlements INTO saved FROM emailmonitor.job_entitlements
 WHERE organization_id=NEW.organization_id AND job_id=NEW.job_id;
 IF saved IS NULL OR conf IS NULL THEN RAISE EXCEPTION 'EFFECTIVE_ENTITLEMENT_REQUIRED'; END IF;
 IF NEW.observation->>'route'='browser_dom' AND
 (NOT (conf->>'browser_enabled')::boolean OR NOT (saved->>'browser_enabled')::boolean)
 THEN RAISE EXCEPTION 'ENTITLEMENT_BUDGET_EXHAUSTED' USING ERRCODE='EM013'; END IF;
 article_cap:=least((conf->>'max_articles_per_job')::integer,(saved->>'max_articles_per_job')::integer);
 SELECT entry.ordinality INTO position FROM emailmonitor.discovery d,
 LATERAL jsonb_array_elements_text(d.checkpoint->'articles') WITH ORDINALITY entry(url,ordinality)
 WHERE d.organization_id=NEW.organization_id AND d.job_id=NEW.job_id AND entry.url=NEW.article_url;
 IF position IS NULL OR position>article_cap THEN RAISE EXCEPTION 'ENTITLEMENT_BUDGET_EXHAUSTED' USING ERRCODE='EM013'; END IF;
 SELECT * INTO account FROM emailmonitor.resolution_accounts WHERE organization_id=NEW.organization_id
 AND root_job_id=root AND unit_id=unit;
 IF account.state='settled' THEN RETURN NEW; END IF;
 IF account.state='reserved' THEN v_period:=account.period; END IF;
 cap:=least((conf->>'monthly_resolution_units')::integer,(saved->>'monthly_resolution_units')::integer);
 SELECT count(*) INTO units FROM emailmonitor.resolution_accounts WHERE organization_id=NEW.organization_id
 AND period=v_period AND state IN ('reserved','settled');
 IF units>cap OR (account.state IS DISTINCT FROM 'reserved' AND units>=cap)
 THEN RAISE EXCEPTION 'ENTITLEMENT_BUDGET_EXHAUSTED' USING ERRCODE='EM013'; END IF;
 item:=nullif(current_setting('emailmonitor.execution_item',true),'')::uuid;
 INSERT INTO emailmonitor.resolution_accounts(organization_id,root_job_id,unit_id,job_id,item_id,period,state)
 VALUES(NEW.organization_id,root,unit,NEW.job_id,item,v_period,'reserved')
 ON CONFLICT(organization_id,root_job_id,unit_id) DO UPDATE SET job_id=EXCLUDED.job_id,item_id=EXCLUDED.item_id,
 period=EXCLUDED.period,state='reserved';
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.guard_association_record() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
DECLARE b emailmonitor.association_batches; old_revision bigint; author uuid; candidate uuid; cited uuid[];
BEGIN
 SELECT * INTO b FROM emailmonitor.association_batches WHERE organization_id=NEW.organization_id AND id=NEW.batch_id FOR SHARE;
 PERFORM emailmonitor.association_parent_fence(b.organization_id,b.job_id,b.article_url,b.source_revision,TG_OP='INSERT');
 IF TG_OP='INSERT' THEN
 IF b.id IS NULL OR b.sealed OR NOT COALESCE(emailmonitor.job_write_allowed(b.organization_id,b.job_id),false)
 OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(b.snapshot->TG_ARGV[0]) item WHERE item=NEW.record)
 THEN RAISE EXCEPTION 'ASSOCIATION_RECEIPT'; END IF;
 ELSE
 IF TG_TABLE_NAME<>'author_email_associations' OR NOT b.sealed
 OR emailmonitor.session_role(b.organization_id) NOT IN ('owner','admin','data_steward','reviewer')
 OR NEW.organization_id<>OLD.organization_id OR NEW.batch_id<>OLD.batch_id
 OR (NEW.record-ARRAY['author_id','state','evidence_strength','evidence_ids','reason','revision'])
 IS DISTINCT FROM (OLD.record-ARRAY['author_id','state','evidence_strength','evidence_ids','reason','revision'])
 OR (NEW.record->>'revision')::bigint<>(OLD.record->>'revision')::bigint+1
 OR OLD.record->>'state'='suppressed' OR NEW.record->>'state' NOT IN ('accepted','rejected')
 OR NEW.record->>'reason' IS DISTINCT FROM 'reviewed_evidence'
 THEN RAISE EXCEPTION 'ASSOCIATION_REVIEW_FENCE'; END IF;
 END IF;
 IF TG_TABLE_NAME='author_email_associations' AND NEW.record->>'state'='accepted' THEN
 author:=(NEW.record->>'author_id')::uuid; candidate:=(NEW.record->>'candidate_id')::uuid;
 SELECT array_agg(value::uuid) INTO cited FROM jsonb_array_elements_text(NEW.record->'evidence_ids');
 IF author IS NULL OR NEW.record->>'evidence_strength' NOT IN ('explicit','supported')
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.association_candidates c WHERE c.organization_id=NEW.organization_id
 AND c.batch_id=NEW.batch_id AND c.id=candidate AND c.syntax_status='valid' AND NOT c.normalization_collision)
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.association_authors a WHERE a.organization_id=NEW.organization_id AND a.batch_id=NEW.batch_id AND a.id=author)
 OR cited IS NULL OR cardinality(cited)>40
 OR EXISTS(SELECT 1 FROM unnest(cited) eid WHERE NOT EXISTS(SELECT 1 FROM emailmonitor.association_evidence e
 WHERE e.organization_id=NEW.organization_id AND e.batch_id=NEW.batch_id AND e.id=eid AND length(e.excerpt)>0))
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.association_candidates c WHERE c.organization_id=NEW.organization_id AND c.batch_id=NEW.batch_id AND c.id=candidate
 AND EXISTS(SELECT 1 FROM jsonb_array_elements_text(c.record->'evidence_ids') eid WHERE eid::uuid=ANY(cited)))
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.association_authors a WHERE a.organization_id=NEW.organization_id AND a.batch_id=NEW.batch_id AND a.id=author
 AND EXISTS(SELECT 1 FROM jsonb_array_elements_text(a.record->'evidence_ids') eid WHERE eid::uuid=ANY(cited)))
 THEN RAISE EXCEPTION 'ASSOCIATION_ACCEPTANCE_EVIDENCE'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.guard_association_relation() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
DECLARE b emailmonitor.association_batches; source jsonb; entity uuid;
BEGIN
 SELECT * INTO b FROM emailmonitor.association_batches WHERE organization_id=NEW.organization_id AND id=NEW.batch_id FOR SHARE;
 PERFORM emailmonitor.association_parent_fence(b.organization_id,b.job_id,b.article_url,b.source_revision,NOT COALESCE(b.sealed,false));
 IF b.id IS NULL THEN RAISE EXCEPTION 'ASSOCIATION_RELATION'; END IF;
 IF b.sealed THEN
 IF emailmonitor.service_selected(b.organization_id) THEN RAISE EXCEPTION 'ASSOCIATION_IMMUTABLE'; END IF;
 IF TG_TABLE_NAME<>'association_evidence_links' OR emailmonitor.session_role(b.organization_id) NOT IN ('owner','admin','data_steward','reviewer')
 THEN RAISE EXCEPTION 'ASSOCIATION_IMMUTABLE'; END IF;
 RETURN NEW;
 END IF;
 IF NOT COALESCE(emailmonitor.job_write_allowed(b.organization_id,b.job_id),false) THEN RAISE EXCEPTION 'ASSOCIATION_DENIED' USING ERRCODE='EM009'; END IF;
 entity:=(to_jsonb(NEW)->>TG_ARGV[1])::uuid;
 SELECT item INTO source FROM jsonb_array_elements(b.snapshot->TG_ARGV[0]) item WHERE item->>'id'=entity::text;
 IF source IS NULL THEN RAISE EXCEPTION 'ASSOCIATION_RELATION'; END IF;
 IF TG_TABLE_NAME='association_affiliations' THEN
 IF source->'affiliations'->>(NEW.ordinal-1) IS DISTINCT FROM NEW.institution_name THEN RAISE EXCEPTION 'ASSOCIATION_AFFILIATION'; END IF;
 ELSIF TG_TABLE_NAME='association_raw_variants' THEN
 IF source->'raw_variants'->>(NEW.ordinal-1) IS DISTINCT FROM NEW.raw_address THEN RAISE EXCEPTION 'ASSOCIATION_RAW_VARIANT'; END IF;
 ELSIF NOT (source->'evidence_ids' ? NEW.evidence_id::text) THEN RAISE EXCEPTION 'ASSOCIATION_EVIDENCE_LINK'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION emailmonitor.service_read_job(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.service_scope_allowed(p_org,p_job,'extraction')
 AND emailmonitor.execution_read_allowed(p_org,p_job)
$$;
CREATE FUNCTION emailmonitor.service_read_batch(p_org uuid,p_batch uuid) RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT EXISTS(SELECT 1 FROM emailmonitor.association_batches b
 WHERE b.organization_id=p_org AND b.id=p_batch
 AND emailmonitor.service_scope_allowed(p_org,b.job_id,'extraction'))
$$;
CREATE FUNCTION emailmonitor.service_read_source(p_org uuid,p_source text,p_version bigint)
 RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.service_selected(p_org) AND emailmonitor.privacy_source_allowed(p_org)
 AND EXISTS(SELECT 1 FROM emailmonitor.service_delegations d WHERE d.organization_id=p_org
 AND d.id=nullif(current_setting('emailmonitor.service_delegation',true),'')::uuid
 AND d.purpose='extraction' AND d.source_id=p_source AND d.policy_version=p_version)
$$;
CREATE OR REPLACE FUNCTION emailmonitor.association_insert_allowed(p_org uuid,p_batch uuid)
 RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.work_tenant_allowed(p_org) AND EXISTS(SELECT 1 FROM emailmonitor.association_batches b
 WHERE b.organization_id=p_org AND b.id=p_batch AND NOT b.sealed
 AND emailmonitor.job_write_allowed(p_org,b.job_id))
$$;
CREATE FUNCTION emailmonitor.work_audit(p_org uuid,p_resource uuid,p_action text,p_id uuid)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF p_action IS NULL OR p_action NOT IN ('discovery.planned','discovery.page_committed','discovery.delivery.received')
 THEN RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 IF emailmonitor.service_selected(p_org) THEN
 IF p_action<>'discovery.page_committed' OR NOT emailmonitor.service_scope_allowed(p_org,p_resource,'extraction')
 THEN RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 PERFORM emailmonitor.job_permission_fence(p_org,p_resource);
 ELSE
 IF NOT COALESCE(emailmonitor.human_work_tenant_allowed(p_org),false) THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 END IF;
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,p_id,emailmonitor.work_actor(p_org),p_action,p_resource);
END $$;

CREATE POLICY service_read ON emailmonitor.organizations FOR SELECT TO emailmonitor_worker
 USING(emailmonitor.service_selected(id));
GRANT SELECT(id,status,deletion_generation) ON emailmonitor.organizations TO emailmonitor_worker;
CREATE POLICY service_read ON emailmonitor.jobs FOR SELECT TO emailmonitor_worker
 USING(emailmonitor.service_read_job(organization_id,id));
GRANT SELECT ON emailmonitor.jobs TO emailmonitor_worker;
CREATE POLICY service_read ON emailmonitor.discovery FOR SELECT TO emailmonitor_worker
 USING(emailmonitor.service_read_job(organization_id,job_id));
CREATE POLICY service_update ON emailmonitor.discovery FOR UPDATE TO emailmonitor_worker
 USING(emailmonitor.service_read_job(organization_id,job_id))
 WITH CHECK(emailmonitor.service_read_job(organization_id,job_id));
GRANT SELECT ON emailmonitor.discovery TO emailmonitor_worker;
GRANT UPDATE(checkpoint,revision) ON emailmonitor.discovery TO emailmonitor_worker;
CREATE POLICY service_read ON emailmonitor.discovery_outbox FOR SELECT TO emailmonitor_worker
 USING(emailmonitor.service_read_job(organization_id,job_id));
CREATE POLICY service_insert ON emailmonitor.discovery_outbox FOR INSERT TO emailmonitor_worker
 WITH CHECK(emailmonitor.service_read_job(organization_id,job_id));
GRANT SELECT,INSERT ON emailmonitor.discovery_outbox TO emailmonitor_worker;

DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['execution_runs','execution_items','execution_outbox','execution_events','execution_effects','job_entitlements'] LOOP
 EXECUTE format('CREATE POLICY service_read ON emailmonitor.%I FOR SELECT TO emailmonitor_worker USING(emailmonitor.service_read_job(organization_id,job_id))',t);
 EXECUTE format('GRANT SELECT ON emailmonitor.%I TO emailmonitor_worker',t);
 END LOOP;
END $$;
CREATE POLICY service_read ON emailmonitor.source_policy_heads FOR SELECT TO emailmonitor_worker
 USING(emailmonitor.service_read_source(organization_id,source_id,current_version));
CREATE POLICY service_read ON emailmonitor.source_policies FOR SELECT TO emailmonitor_worker
 USING(emailmonitor.service_read_source(organization_id,source_id,version));
GRANT SELECT ON emailmonitor.source_policy_heads,emailmonitor.source_policies TO emailmonitor_worker;
-- Catalog is global public configuration already readable by human runtime;
-- source-policy row visibility still binds actual use to the exact delegation.
GRANT SELECT ON emailmonitor.source_catalog TO emailmonitor_worker;

CREATE POLICY service_read ON emailmonitor.article_observations FOR SELECT TO emailmonitor_worker
 USING(emailmonitor.service_read_job(organization_id,job_id) AND expires_at>clock_timestamp());
CREATE POLICY service_insert ON emailmonitor.article_observations FOR INSERT TO emailmonitor_worker
 WITH CHECK(emailmonitor.service_read_job(organization_id,job_id));
CREATE POLICY service_update ON emailmonitor.article_observations FOR UPDATE TO emailmonitor_worker
 USING(emailmonitor.service_read_job(organization_id,job_id) AND expires_at>clock_timestamp())
 WITH CHECK(emailmonitor.service_read_job(organization_id,job_id));
CREATE POLICY service_privacy ON emailmonitor.article_observations AS RESTRICTIVE FOR SELECT TO emailmonitor_worker
 USING(emailmonitor.privacy_payload_allowed(organization_id,observation));
CREATE POLICY service_retention ON emailmonitor.article_observations AS RESTRICTIVE FOR SELECT TO emailmonitor_worker
 USING(emailmonitor.privacy_excerpt_allowed(organization_id,observed_at,observation));
GRANT SELECT,INSERT ON emailmonitor.article_observations TO emailmonitor_worker;
GRANT UPDATE(observation,revision,observed_at) ON emailmonitor.article_observations TO emailmonitor_worker;
CREATE POLICY service_read ON emailmonitor.association_batches FOR SELECT TO emailmonitor_worker
 USING(emailmonitor.service_read_job(organization_id,job_id) AND emailmonitor.association_visible(organization_id,id));
CREATE POLICY service_insert ON emailmonitor.association_batches FOR INSERT TO emailmonitor_worker
 WITH CHECK(emailmonitor.service_read_job(organization_id,job_id) AND NOT sealed);
GRANT SELECT,INSERT ON emailmonitor.association_batches TO emailmonitor_worker;
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['association_authors','association_candidates','association_evidence','author_email_associations',
 'association_affiliations','association_raw_variants','association_author_evidence','association_candidate_evidence','association_evidence_links'] LOOP
 EXECUTE format('CREATE POLICY service_read ON emailmonitor.%I FOR SELECT TO emailmonitor_worker USING(emailmonitor.service_read_batch(organization_id,batch_id) AND emailmonitor.association_visible(organization_id,batch_id))',t);
 EXECUTE format('CREATE POLICY service_insert ON emailmonitor.%I FOR INSERT TO emailmonitor_worker WITH CHECK(emailmonitor.association_insert_allowed(organization_id,batch_id))',t);
 EXECUTE format('GRANT SELECT,INSERT ON emailmonitor.%I TO emailmonitor_worker',t);
 END LOOP;
END $$;

-- Exact export execution only. No service grant for create/review/download.
CREATE FUNCTION emailmonitor.work_export_allowed(p_org uuid,p_export uuid)
 RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT (COALESCE(emailmonitor.human_work_tenant_allowed(p_org),false) AND COALESCE(emailmonitor.session_role(p_org)
 IN ('owner','admin','data_steward'),false)) OR emailmonitor.service_scope_allowed(p_org,p_export,'export')
$$;

CREATE OR REPLACE FUNCTION emailmonitor.results_fence(p_org uuid,p_export boolean DEFAULT false,
 p_requester uuid DEFAULT NULL,p_policy boolean DEFAULT true) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE actor uuid; p emailmonitor.source_policies; s emailmonitor.source_catalog;
BEGIN
 IF NOT emailmonitor.privacy_source_allowed(p_org) OR (p_export AND EXISTS(SELECT 1 FROM emailmonitor.lifecycle_configuration WHERE organization_id=p_org AND (retention->>'export_hours')::integer=0)) THEN RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 IF NOT COALESCE(emailmonitor.work_tenant_allowed(p_org),false) THEN
 RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 IF emailmonitor.service_selected(p_org) AND (NOT p_export OR NOT EXISTS(
 SELECT 1 FROM emailmonitor.service_delegations d WHERE d.organization_id=p_org
 AND d.id=nullif(current_setting('emailmonitor.service_delegation',true),'')::uuid
 AND d.purpose='export' AND (p_requester IS NULL OR d.initiator_id=p_requester))) THEN
 RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 PERFORM emailmonitor.work_authority_fence(p_org);
 actor:=emailmonitor.work_actor(p_org);
 -- NOWAIT refuses contention rather than introducing a reverse-lock wait against
 -- existing membership triggers; current authority is rechecked after every lock.
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.memberships WHERE organization_id=p_org
 AND identity_id IN (actor,COALESCE(p_requester,actor)) ORDER BY identity_id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.identities WHERE id IN (actor,COALESCE(p_requester,actor))
 ORDER BY id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.sessions WHERE token_hash=current_setting('emailmonitor.session_hash',true)
 FOR SHARE NOWAIT;
 IF NOT COALESCE(emailmonitor.work_tenant_allowed(p_org),false) OR NOT EXISTS(
 SELECT 1 FROM emailmonitor.organizations WHERE id=p_org AND status='active') OR NOT emailmonitor.work_authority_current(p_org)
 OR (p_export AND NOT emailmonitor.service_selected(p_org) AND COALESCE(emailmonitor.session_role(p_org),'') NOT IN ('owner','admin','data_steward'))
 OR (p_requester IS NOT NULL AND NOT EXISTS(SELECT 1 FROM emailmonitor.memberships m
 JOIN emailmonitor.identities ii ON ii.id=m.identity_id WHERE m.organization_id=p_org
 AND m.identity_id=p_requester AND m.status='active' AND ii.active
 AND m.role IN ('owner','admin','data_steward')))
 THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 IF p_policy THEN
 SELECT * INTO s FROM emailmonitor.source_catalog WHERE source_id='synthetic-publisher' FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.source_policy_heads WHERE organization_id=p_org
 AND source_id='synthetic-publisher' FOR SHARE NOWAIT;
 SELECT pp.* INTO p FROM emailmonitor.source_policies pp JOIN emailmonitor.source_policy_heads h
 USING(organization_id,source_id) WHERE pp.organization_id=p_org AND pp.source_id='synthetic-publisher'
 AND pp.version=h.current_version FOR SHARE OF pp NOWAIT;
 IF NOT COALESCE(s.enabled,false) OR s.execution_mode IS DISTINCT FROM 'fixture'
 OR p.state IS DISTINCT FROM 'approved' OR p.valid_until<=clock_timestamp()
 OR p.policy->>'purpose' IS DISTINCT FROM 'academic_contact_research'
 OR NOT COALESCE(p.policy->'allowed_operations' ? 'extract_contacts',false)
 OR NOT COALESCE('extract_contacts'=ANY(s.allowed_operations),false)
 OR NOT COALESCE('synthetic.publisher.example'=ANY(s.allowed_hosts),false)
 OR NOT COALESCE(p.policy->'allowed_hosts' ? 'synthetic.publisher.example',false)
 OR (p_export AND (NOT COALESCE(p.policy->'allowed_operations' ? 'export_contacts',false)
 OR NOT COALESCE((p.policy->>'export_contacts_allowed')::boolean,false)
 OR NOT COALESCE('export_contacts'=ANY(s.allowed_operations),false)))
 THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 END IF;
 RETURN actor;
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.export_valid(p_org uuid,p_export uuid) RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.privacy_source_allowed(p_org) AND NOT EXISTS(SELECT 1 FROM emailmonitor.exports ee JOIN emailmonitor.lifecycle_configuration cc ON cc.organization_id=ee.organization_id WHERE ee.organization_id=p_org AND ee.id=p_export AND ee.created_at+make_interval(hours=>(cc.retention->>'export_hours')::integer)<=clock_timestamp()) AND COALESCE(EXISTS(SELECT 1 FROM emailmonitor.exports e JOIN emailmonitor.organizations o
 ON o.id=e.organization_id JOIN emailmonitor.memberships m ON m.organization_id=e.organization_id
 AND m.identity_id=e.requested_by JOIN emailmonitor.identities ii ON ii.id=m.identity_id
 JOIN emailmonitor.source_policy_heads h ON h.organization_id=e.organization_id AND h.source_id='synthetic-publisher'
 JOIN emailmonitor.source_policies p ON p.organization_id=h.organization_id AND p.source_id=h.source_id AND p.version=h.current_version
 JOIN emailmonitor.source_catalog s ON s.source_id=h.source_id
 WHERE e.organization_id=p_org AND e.id=p_export AND emailmonitor.work_export_allowed(p_org,p_export)
 AND o.status='active' AND o.deletion_generation=e.deletion_generation AND m.status='active' AND ii.active
 AND m.role IN ('owner','admin','data_steward') AND e.expires_at>clock_timestamp()
 AND e.state NOT IN ('revoked','expired','failed') AND p.version=e.policy_version
 AND p.state='approved' AND p.valid_until>clock_timestamp() AND s.enabled AND s.execution_mode='fixture'
 AND p.policy->>'purpose'=e.request->>'purpose' AND p.policy->'allowed_operations' ? 'export_contacts'
 AND (p.policy->>'export_contacts_allowed')::boolean AND 'export_contacts'=ANY(s.allowed_operations)
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.export_members em LEFT JOIN emailmonitor.author_email_associations a
 ON a.organization_id=em.organization_id AND a.batch_id=em.batch_id AND a.id=em.association_id
 WHERE em.organization_id=p_org AND em.export_id=p_export AND
 (a.id IS NULL OR a.revision<>em.association_revision OR a.state IN ('rejected','suppressed')
 OR NOT emailmonitor.association_visible(p_org,em.batch_id)))
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.export_outcomes eo JOIN emailmonitor.jobs j
 ON j.organization_id=eo.organization_id AND j.id=eo.job_id
 WHERE eo.organization_id=p_org AND eo.export_id=p_export AND (j.row_version<>eo.job_revision
 OR NOT emailmonitor.execution_read_allowed(p_org,eo.job_id)
 OR emailmonitor.result_outcome_document(p_org,eo.job_id,eo.item_id) IS DISTINCT FROM eo.document))),false)
$$;

CREATE OR REPLACE FUNCTION emailmonitor.export_lock(p_org uuid,p_export uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE item record; requester uuid;
BEGIN
 IF NOT emailmonitor.work_export_allowed(p_org,p_export) THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 SELECT requested_by INTO requester FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export;
 PERFORM emailmonitor.results_fence(p_org,true,requester);
 FOR item IN SELECT DISTINCT batch_id FROM emailmonitor.export_members
 WHERE organization_id=p_org AND export_id=p_export ORDER BY batch_id LOOP
 PERFORM emailmonitor.lock_association_batch(p_org,item.batch_id);
 END LOOP;
 PERFORM 1 FROM emailmonitor.author_email_associations a JOIN emailmonitor.export_members em
 ON em.organization_id=a.organization_id AND em.batch_id=a.batch_id AND em.association_id=a.id
 WHERE em.organization_id=p_org AND em.export_id=p_export ORDER BY a.batch_id,a.id FOR SHARE OF a NOWAIT;
 FOR item IN SELECT DISTINCT job_id FROM emailmonitor.export_outcomes
 WHERE organization_id=p_org AND export_id=p_export ORDER BY job_id LOOP
 PERFORM emailmonitor.execution_read_fence(p_org,item.job_id);
 END LOOP;
 PERFORM 1 FROM emailmonitor.execution_items i JOIN emailmonitor.export_outcomes eo
 ON eo.organization_id=i.organization_id AND eo.job_id=i.job_id AND eo.item_id=i.id
 WHERE eo.organization_id=p_org AND eo.export_id=p_export ORDER BY i.job_id,i.id FOR SHARE OF i NOWAIT;
 IF NOT emailmonitor.export_valid(p_org,p_export) THEN
 RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.export_entitlement_fence(p_org uuid,p_export uuid DEFAULT NULL) RETURNS integer
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE conf jsonb; saved jsonb;
BEGIN
 IF NOT COALESCE(emailmonitor.human_work_tenant_allowed(p_org),false) AND NOT emailmonitor.service_scope_allowed(p_org,p_export,'export') THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 PERFORM emailmonitor.results_fence(p_org,true);
 SELECT configuration->'entitlements' INTO conf FROM emailmonitor.tenant_configuration WHERE organization_id=p_org FOR SHARE;
 IF p_export IS NOT NULL THEN
 SELECT entitlements INTO saved FROM emailmonitor.export_entitlements WHERE organization_id=p_org AND export_id=p_export;
 IF saved IS NULL THEN RAISE EXCEPTION 'EXPORT_ENTITLEMENT_DENIED' USING ERRCODE='EM013'; END IF;
 ELSE saved:=conf; END IF;
 IF conf IS NULL OR NOT (conf->>'exports_enabled')::boolean OR NOT (saved->>'exports_enabled')::boolean
 OR least((conf->>'max_parallel_export')::integer,(saved->>'max_parallel_export')::integer)=0
 OR least((conf->>'max_export_bytes')::integer,(saved->>'max_export_bytes')::integer)=0
 THEN RAISE EXCEPTION 'EXPORT_ENTITLEMENT_DENIED' USING ERRCODE='EM013'; END IF;
 RETURN least((conf->>'max_export_bytes')::integer,(saved->>'max_export_bytes')::integer);
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.exports_claim(p_org uuid,p_export uuid,p_event uuid,p_generation bigint,p_nonce uuid,p_seconds integer) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE e emailmonitor.exports;
BEGIN
 IF NOT emailmonitor.work_export_allowed(p_org,p_export) THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 PERFORM emailmonitor.results_fence(p_org,true);
 IF emailmonitor.service_scope_allowed(p_org,p_export,'export') THEN
 -- Bound even direct RPC callers: never rely only on the Python transaction setting.
 PERFORM set_config('lock_timeout','2000ms',true);
 SELECT * INTO e FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export FOR UPDATE;
 -- Authority may have expired while the publisher released its shared row lock.
 PERFORM emailmonitor.work_authority_fence(p_org);
 ELSE
 SELECT * INTO e FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export FOR UPDATE NOWAIT;
 END IF;
 -- Invalid/stale/duplicate delivery retains the original receipt and denial path.
 IF e.id IS NULL OR e.generation IS DISTINCT FROM p_generation OR e.state NOT IN ('queued','running')
 OR (e.state='running' AND e.lease_until>clock_timestamp()) OR e.attempts>=3
 OR p_seconds IS NULL OR p_seconds NOT BETWEEN 1 AND 120 OR p_nonce IS NULL
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.export_outbox WHERE organization_id=p_org
 AND export_id=p_export AND event_id=p_event AND generation=p_generation) THEN
 RETURN emailmonitor.exports_claim_pre_admission(p_org,p_export,p_event,p_generation,p_nonce,p_seconds); END IF;
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 PERFORM emailmonitor.export_entitlement_fence(p_org,p_export);
 PERFORM emailmonitor.export_lock(p_org,p_export);
 IF NOT emailmonitor.admission_try(p_org,NULL,p_export,'export',p_generation,p_nonce,p_seconds) THEN RETURN NULL; END IF;
 RETURN emailmonitor.exports_claim_pre_admission(p_org,p_export,p_event,p_generation,p_nonce,p_seconds);
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.exports_finish(p_org uuid,p_export uuid,p_generation bigint,p_nonce uuid,p_body bytea,p_mime text,p_extension text) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE cap integer;
BEGIN
 IF NOT emailmonitor.work_export_allowed(p_org,p_export) THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 PERFORM emailmonitor.results_fence(p_org,true);
 PERFORM 1 FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export FOR UPDATE NOWAIT;
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 cap:=emailmonitor.export_entitlement_fence(p_org,p_export);
 IF p_body IS NULL OR octet_length(p_body)>cap THEN RAISE EXCEPTION 'EXPORT_ENTITLEMENT_DENIED' USING ERRCODE='EM013'; END IF;
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.admission_requests WHERE organization_id=p_org AND reference_id=p_export
 AND pool='export' AND state='active' AND generation=p_generation AND nonce=p_nonce AND lease_until>clock_timestamp()
 AND emailmonitor.work_ticket_owned(p_org,actor_id,session_hash,service_delegation)) THEN RETURN false; END IF;
 RETURN emailmonitor.exports_finish_pre_entitlement(p_org,p_export,p_generation,p_nonce,p_body,p_mime,p_extension);
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.exports_fail(p_org uuid,p_export uuid,p_generation bigint,p_nonce uuid,p_reason text)
 RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF NOT emailmonitor.work_export_allowed(p_org,p_export) THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 PERFORM emailmonitor.results_fence(p_org,true,NULL,false);
 IF p_reason IS NULL OR p_reason NOT IN ('unsafe_csv_cell','unsupported_text','render_limit','snapshot_changed','worker_failure')
 THEN RAISE EXCEPTION 'EXPORT_FAILURE_INVALID'; END IF;
 UPDATE emailmonitor.exports SET state='failed',reason=p_reason,revision=revision+1,lease_nonce=NULL,lease_until=NULL
 WHERE organization_id=p_org AND id=p_export AND generation=p_generation AND lease_nonce=p_nonce
 AND state='running' AND lease_until>clock_timestamp();
 RETURN FOUND;
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.exports_reconcile(p_org uuid,p_export uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE e emailmonitor.exports;
BEGIN
 IF NOT emailmonitor.work_export_allowed(p_org,p_export) THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 PERFORM emailmonitor.results_fence(p_org,true,NULL,false);
 SELECT * INTO e FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export FOR UPDATE NOWAIT;
 IF e.id IS NULL THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 -- A current service may terminalize its own stale snapshot without changing
 -- immutable authority generation. Failed is terminal; no requeue or renewal.
 IF emailmonitor.service_selected(p_org) AND e.state IN ('queued','running')
 AND (NOT emailmonitor.export_entitlement_allowed(p_org,p_export)
 OR NOT emailmonitor.export_valid(p_org,p_export)) THEN
 UPDATE emailmonitor.exports SET state='failed',reason='snapshot_changed',
 revision=revision+1,lease_nonce=NULL,lease_until=NULL
 WHERE organization_id=p_org AND id=p_export;
 PERFORM emailmonitor.work_authority_fence(p_org);
 RETURN;
 END IF;
 IF e.state IN ('queued','running') AND NOT emailmonitor.export_entitlement_allowed(p_org,p_export) THEN
 UPDATE emailmonitor.exports SET state='failed',reason='snapshot_changed',generation=generation+1,
 revision=revision+1,lease_nonce=NULL,lease_until=NULL WHERE organization_id=p_org AND id=p_export;
 RETURN;
 END IF;
 PERFORM emailmonitor.exports_reconcile_pre_entitlement(p_org,p_export);
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.exports_finish_pre_entitlement(p_org uuid,p_export uuid,p_generation bigint,p_nonce uuid,p_body bytea,p_mime text,p_extension text)
 RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE e emailmonitor.exports; hash text; mime text; extension text;
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true);
 SELECT * INTO e FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export FOR UPDATE NOWAIT;
 IF e.id IS NULL OR e.state<>'running' OR e.generation IS DISTINCT FROM p_generation
 OR e.lease_nonce IS DISTINCT FROM p_nonce OR e.lease_until<=clock_timestamp() THEN RETURN false; END IF;
 PERFORM emailmonitor.export_lock(p_org,p_export);
 IF e.request->>'format'='xlsx' THEN mime:='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';extension:='xlsx';
 ELSIF (e.request->>'include_article_outcomes')::boolean THEN mime:='application/zip';extension:='zip';
 ELSE mime:='text/csv; charset=utf-8';extension:='csv'; END IF;
 IF p_body IS NULL OR octet_length(p_body)>8388608 OR octet_length(p_body)=0
 OR p_mime IS DISTINCT FROM mime OR p_extension IS DISTINCT FROM extension THEN RAISE EXCEPTION 'EXPORT_ARTIFACT_INVALID'; END IF;
 hash:=encode(sha256(p_body),'hex');
 INSERT INTO emailmonitor.export_effects(organization_id,export_id,generation,digest) VALUES(p_org,p_export,p_generation,hash);
 INSERT INTO emailmonitor.export_artifacts VALUES(p_org,p_export,p_body,mime,extension,hash);
 UPDATE emailmonitor.exports SET state='ready',reason='complete',revision=revision+1,lease_nonce=NULL,lease_until=NULL
 WHERE organization_id=p_org AND id=p_export;
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,p_nonce,emailmonitor.work_actor(p_org),'export.ready',p_export);
 INSERT INTO emailmonitor.export_events(organization_id,export_id,event_id,event_type) VALUES(p_org,p_export,p_nonce,'export.ready');
 PERFORM emailmonitor.export_lock(p_org,p_export);
 RETURN true;
END $$;

CREATE FUNCTION emailmonitor.work_job_lock(p_org uuid,p_job uuid)
 RETURNS SETOF emailmonitor.jobs LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
DECLARE row emailmonitor.jobs;
BEGIN
 PERFORM emailmonitor.job_permission_fence(p_org,p_job);
 SELECT * INTO row FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR UPDATE;
 IF row.id IS NULL OR NOT COALESCE(emailmonitor.job_write_allowed(p_org,p_job),false) THEN
 RAISE EXCEPTION 'JOB_UNAVAILABLE'; END IF;
 PERFORM emailmonitor.job_permission_fence(p_org,p_job);
 RETURN NEXT row;
END $$;
CREATE FUNCTION emailmonitor.work_discovery_complete(p_org uuid,p_job uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 PERFORM emailmonitor.job_permission_fence(p_org,p_job);
 PERFORM 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job
 AND checkpoint->>'discovery_complete'='true') OR
 (emailmonitor.service_selected(p_org) AND NOT COALESCE(emailmonitor.execution_write_allowed(p_org,p_job),false))
 THEN RAISE EXCEPTION 'EXECUTION_WORK_FENCE' USING ERRCODE='EM010'; END IF;
 UPDATE emailmonitor.jobs SET discovery_complete=true
 WHERE organization_id=p_org AND id=p_job AND NOT discovery_complete;
 PERFORM emailmonitor.job_permission_fence(p_org,p_job);
END $$;
GRANT EXECUTE ON FUNCTION emailmonitor.work_job_lock(uuid,uuid),
 emailmonitor.work_discovery_complete(uuid,uuid) TO emailmonitor_runtime,emailmonitor_worker;

CREATE OR REPLACE FUNCTION emailmonitor.execution_quota_stop(p_org uuid,p_job uuid,p_event uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs;
BEGIN
 PERFORM emailmonitor.execution_control_fence(p_org,p_job);
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 IF j.state NOT IN ('queued','running') THEN RETURN; END IF;
 PERFORM emailmonitor.execution_sync(p_org,p_job);
 UPDATE emailmonitor.execution_items SET state='skipped',reason='quota_exhausted',lease_token=NULL,
 lease_until=NULL,lease_generation=NULL,lease_deletion_generation=NULL,completed_at=clock_timestamp()
 WHERE organization_id=p_org AND job_id=p_job AND state IN ('pending','running','retry_wait');
 DELETE FROM emailmonitor.admission_requests WHERE organization_id=p_org AND job_id=p_job;
 UPDATE emailmonitor.resolution_accounts SET state='released' WHERE organization_id=p_org AND job_id=p_job AND state='reserved';
 PERFORM emailmonitor.execution_emit(p_org,p_job,p_event,'job.item_terminal');
 PERFORM emailmonitor.execution_settle(p_org,p_job,md5(p_event::text||':quota-finished')::uuid);
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,p_event,emailmonitor.work_actor(p_org),'job.quota_exhausted',p_job);
END $$;

REVOKE ALL ON emailmonitor.service_principals,emailmonitor.service_delegations,
 emailmonitor.service_audit FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator,
 emailmonitor_worker,emailmonitor_publisher;
REVOKE ALL ON FUNCTION emailmonitor.service_delegation_current(uuid,uuid),
 emailmonitor.service_caller_allowed(uuid,uuid,text),emailmonitor.guard_service_delegation(),
 emailmonitor.guard_service_principal(),
 emailmonitor.delegate_service_work(uuid,uuid,uuid,text,integer),
 emailmonitor.revoke_service_work(uuid,uuid),
 emailmonitor.service_authority_fence(uuid,uuid,text),
 emailmonitor.service_begin(uuid,uuid,text,bigint,text,uuid),
 emailmonitor.service_scope_allowed(uuid,uuid,text,text),
 emailmonitor.service_end(uuid,uuid,text,text),
 emailmonitor.service_selected(uuid,text),emailmonitor.service_job_visible(uuid,uuid),
 emailmonitor.service_batch_visible(uuid,uuid),emailmonitor.work_tenant_allowed(uuid),
 emailmonitor.work_actor(uuid),emailmonitor.work_authority_current(uuid),
 emailmonitor.work_authority_fence(uuid)
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator,
 emailmonitor_worker,emailmonitor_publisher;
GRANT EXECUTE ON FUNCTION emailmonitor.delegate_service_work(uuid,uuid,uuid,text,integer),
 emailmonitor.revoke_service_work(uuid,uuid) TO emailmonitor_runtime;
GRANT EXECUTE ON FUNCTION emailmonitor.service_begin(uuid,uuid,text,bigint,text,uuid),
 emailmonitor.service_end(uuid,uuid,text,text)
 TO emailmonitor_worker,emailmonitor_publisher;
GRANT EXECUTE ON FUNCTION emailmonitor.service_read_batch(uuid,uuid),emailmonitor.service_selected(uuid,text),emailmonitor.service_read_job(uuid,uuid),
 emailmonitor.service_read_source(uuid,text,bigint),emailmonitor.service_batch_visible(uuid,uuid),
 emailmonitor.privacy_payload_allowed(uuid,jsonb),emailmonitor.privacy_excerpt_allowed(uuid,timestamptz,jsonb),
 emailmonitor.association_visible(uuid,uuid),emailmonitor.association_insert_allowed(uuid,uuid),
 emailmonitor.job_write_allowed(uuid,uuid),emailmonitor.execution_read_allowed(uuid,uuid),
 emailmonitor.job_permission_fence(uuid,uuid),
 emailmonitor.execution_read_fence(uuid,uuid),emailmonitor.execution_write_allowed(uuid,uuid),
 emailmonitor.discovery_source_fence(uuid,uuid,bigint),emailmonitor.lock_association_batch(uuid,uuid),
 emailmonitor.seal_association_batch(uuid,uuid),
 emailmonitor.execution_claim(uuid,uuid,uuid,uuid,uuid,integer,bigint),
 emailmonitor.execution_finish(uuid,uuid,uuid,uuid,uuid,text,uuid),
 emailmonitor.execution_reconcile(uuid,uuid,uuid),
 emailmonitor.fixture_admission_claim(uuid,uuid,text,uuid,integer),
 emailmonitor.network_entitlement_allowed(uuid,text,uuid),
 emailmonitor.source_resource_claim(uuid,uuid,uuid,bigint,text,text,uuid,integer),
 emailmonitor.source_resource_finish(uuid,uuid,uuid,text,integer),
 emailmonitor.work_audit(uuid,uuid,text,uuid) TO emailmonitor_worker;
GRANT EXECUTE ON FUNCTION emailmonitor.work_audit(uuid,uuid,text,uuid) TO emailmonitor_runtime;


GRANT EXECUTE ON FUNCTION emailmonitor.exports_claim(uuid,uuid,uuid,bigint,uuid,integer),
 emailmonitor.exports_finish(uuid,uuid,bigint,uuid,bytea,text,text),
 emailmonitor.exports_fail(uuid,uuid,bigint,uuid,text),emailmonitor.exports_reconcile(uuid,uuid)
 TO emailmonitor_worker;
CREATE OR REPLACE FUNCTION emailmonitor.export_entitlement_allowed(p_org uuid,p_export uuid) RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(EXISTS(SELECT 1 FROM emailmonitor.exports e
 JOIN emailmonitor.tenant_configuration c ON c.organization_id=e.organization_id
 JOIN emailmonitor.export_entitlements saved ON saved.organization_id=e.organization_id AND saved.export_id=e.id
 LEFT JOIN emailmonitor.export_artifacts a ON a.organization_id=e.organization_id AND a.export_id=e.id
 WHERE e.organization_id=p_org AND e.id=p_export AND emailmonitor.work_export_allowed(p_org,p_export)
 AND (c.configuration->'entitlements'->>'exports_enabled')::boolean AND (saved.entitlements->>'exports_enabled')::boolean
 AND least((c.configuration->'entitlements'->>'max_parallel_export')::integer,(saved.entitlements->>'max_parallel_export')::integer)>0
 AND least((c.configuration->'entitlements'->>'max_export_bytes')::integer,(saved.entitlements->>'max_export_bytes')::integer)>0
 AND (e.state<>'ready' OR (a.body IS NOT NULL AND octet_length(a.body)<=least(
 (c.configuration->'entitlements'->>'max_export_bytes')::integer,(saved.entitlements->>'max_export_bytes')::integer)))),false)
$$;

-- Private stored eligibility predicates grant no caller access and are never
-- executable by human/service logins. Only fenced publication calls them.
CREATE FUNCTION emailmonitor.publication_payload_state(p_org uuid,p_document jsonb) RETURNS boolean
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE value text; domain text;
BEGIN
 IF p_document IS NULL OR jsonb_typeof(p_document)<>'object' OR octet_length(p_document::text)>2097152 OR NOT emailmonitor.privacy_source_state(p_org) THEN RETURN false; END IF;
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.privacy_suppressions WHERE organization_id=p_org AND active AND kind IN ('domain','contact')) THEN RETURN true; END IF;
 FOR value IN SELECT x#>>'{}' FROM jsonb_path_query(p_document,'$.**.raw_address') x LOOP
 -- Unsupported canonical forms fail closed under active contact/domain privacy rules.
 IF NOT emailmonitor.privacy_canonical_allowed('contact',value) THEN RETURN false; END IF;
 domain=split_part(lower(value),'@',2);
 IF EXISTS(SELECT 1 FROM emailmonitor.privacy_suppressions WHERE organization_id=p_org AND active AND
 ((kind='contact' AND digest=emailmonitor.privacy_digest(p_org,'contact',value)) OR
 (kind='domain' AND digest=emailmonitor.privacy_digest(p_org,'domain',domain)))) THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$;

CREATE FUNCTION emailmonitor.publication_job_state(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.privacy_job_state(p_org,p_job) AND EXISTS(
 SELECT 1 FROM emailmonitor.jobs j JOIN emailmonitor.discovery d
 ON d.organization_id=j.organization_id AND d.job_id=j.id
 JOIN emailmonitor.organizations o ON o.id=j.organization_id
 JOIN emailmonitor.source_policy_heads h ON h.organization_id=d.organization_id AND h.source_id=d.source_id
 JOIN emailmonitor.source_policies p ON p.organization_id=h.organization_id AND p.source_id=h.source_id AND p.version=h.current_version
 JOIN emailmonitor.source_catalog s ON s.source_id=p.source_id
 LEFT JOIN emailmonitor.execution_runs r ON r.organization_id=j.organization_id AND r.job_id=j.id
 WHERE j.organization_id=p_org AND j.id=p_job AND j.kind='extraction' AND o.status='active'
 AND d.deletion_generation=o.deletion_generation AND p.version=d.policy_version
 AND (r.job_id IS NULL OR (r.policy_version=p.version AND r.deletion_generation=o.deletion_generation AND r.expires_at>statement_timestamp()))
 AND p.state='approved' AND p.valid_until>statement_timestamp() AND s.enabled
 AND j.request->>'purpose'=p.policy->>'purpose'
 AND p.policy->'allowed_operations' ? emailmonitor.fixture_acquisition_operation(d.plan->>'start_url') AND p.policy->'allowed_operations' ? 'extract_contacts'
 AND emailmonitor.fixture_acquisition_operation(d.plan->>'start_url')=ANY(s.allowed_operations) AND 'extract_contacts'=ANY(s.allowed_operations)
 AND 'synthetic.publisher.example'=ANY(s.allowed_hosts) AND p.policy->'allowed_hosts' ? 'synthetic.publisher.example'
 AND (p.policy->'retention'->>'contact_days')::integer>0)
$$;

CREATE FUNCTION emailmonitor.publication_batch_state(p_org uuid,p_batch uuid) RETURNS boolean
 LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE b emailmonitor.association_batches;
BEGIN
 IF NOT emailmonitor.privacy_job_state(p_org,(SELECT job_id FROM emailmonitor.association_batches WHERE organization_id=p_org AND id=p_batch)) THEN RETURN false; END IF;
 SELECT * INTO b FROM emailmonitor.association_batches WHERE organization_id=p_org AND id=p_batch;
 RETURN b.id IS NOT NULL AND EXISTS(SELECT 1 FROM emailmonitor.article_observations a WHERE a.organization_id=p_org AND a.job_id=b.job_id AND a.article_url=b.article_url AND emailmonitor.publication_payload_state(p_org,a.observation) AND NOT EXISTS(SELECT 1 FROM emailmonitor.lifecycle_configuration c WHERE c.organization_id=p_org AND jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")') AND a.observed_at+make_interval(days=>(c.retention->>'excerpt_days')::integer)<=clock_timestamp())) AND b.sealed AND b.expires_at>statement_timestamp() AND EXISTS(
 SELECT 1 FROM emailmonitor.article_observations a JOIN emailmonitor.jobs j ON j.organization_id=a.organization_id AND j.id=a.job_id
 JOIN emailmonitor.organizations o ON o.id=a.organization_id
 JOIN emailmonitor.source_policy_heads h ON h.organization_id=a.organization_id AND h.source_id=a.source_id
 JOIN emailmonitor.source_policies p ON p.organization_id=h.organization_id AND p.source_id=h.source_id AND p.version=h.current_version
 JOIN emailmonitor.source_catalog s ON s.source_id=p.source_id
 WHERE a.organization_id=p_org AND a.job_id=b.job_id AND a.article_url=b.article_url
 AND a.revision=b.source_revision AND a.policy_version=b.policy_version
 AND a.generation=b.generation AND j.kind='extraction' AND j.kind='extraction'
 AND a.deletion_generation=b.deletion_generation AND o.deletion_generation=b.deletion_generation AND o.status='active'
 AND a.expires_at>statement_timestamp() AND s.enabled AND p.state='approved' AND p.valid_until>statement_timestamp()
 AND p.version=b.policy_version AND a.policy_version=b.policy_version
 AND j.request->>'purpose'=p.policy->>'purpose' AND p.policy->'allowed_operations' ? 'extract_contacts'
 AND 'extract_contacts'=ANY(s.allowed_operations) AND 'synthetic.publisher.example'=ANY(s.allowed_hosts)
 AND p.policy->'allowed_hosts' ? 'synthetic.publisher.example'
 AND s.support->'routes_by_operation'->'extract_contacts' ? replace(b.article_url,'https://synthetic.publisher.example','')
 AND (p.policy->'retention'->>'contact_days')::integer>0
 AND (a.observation->>'route'<>'article_xml' OR (p.policy->'allowed_operations' ? 'fetch_xml' AND 'fetch_xml'=ANY(s.allowed_operations)))
 AND (a.observation->>'route'<>'browser_dom' OR (p.policy->'allowed_operations' ? 'browser' AND 'browser'=ANY(s.allowed_operations)))
 AND (NOT jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")') OR (
 p.policy->'allowed_operations' ? 'retain_excerpt' AND 'retain_excerpt'=ANY(s.allowed_operations) AND (p.policy->'retention'->>'excerpt_days')::integer>0)));
END $$;

CREATE FUNCTION emailmonitor.publication_outcome_state(p_org uuid,p_job uuid,p_item uuid)
 RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT jsonb_build_object('organization_id',i.organization_id,'job_id',i.job_id,'item_id',i.id,
 'source_url',i.input_url,'state',i.state,'reason',i.reason,'batch_id',i.batch_id,'completed_at',i.completed_at,
 'inherited_job_id',i.inherited_job_id,'observation_status',obs.observation->'status',
 'technical_status','not_checked','outreach_eligibility','not_assessed')
 FROM emailmonitor.execution_items i LEFT JOIN emailmonitor.article_observations obs
 ON obs.organization_id=i.organization_id AND obs.job_id=COALESCE(i.inherited_job_id,i.job_id)
 AND obs.article_url=i.input_url WHERE i.organization_id=p_org AND i.job_id=p_job AND i.id=p_item
 AND i.work_kind='article' AND emailmonitor.publication_job_state(p_org,p_job)
$$;

CREATE FUNCTION emailmonitor.publication_export_state(p_org uuid,p_export uuid) RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.privacy_source_state(p_org) AND NOT EXISTS(SELECT 1 FROM emailmonitor.exports ee JOIN emailmonitor.lifecycle_configuration cc ON cc.organization_id=ee.organization_id WHERE ee.organization_id=p_org AND ee.id=p_export AND ee.created_at+make_interval(hours=>(cc.retention->>'export_hours')::integer)<=clock_timestamp()) AND COALESCE(EXISTS(SELECT 1 FROM emailmonitor.exports e JOIN emailmonitor.organizations o
 ON o.id=e.organization_id JOIN emailmonitor.memberships m ON m.organization_id=e.organization_id
 AND m.identity_id=e.requested_by JOIN emailmonitor.identities ii ON ii.id=m.identity_id
 JOIN emailmonitor.source_policy_heads h ON h.organization_id=e.organization_id AND h.source_id='synthetic-publisher'
 JOIN emailmonitor.source_policies p ON p.organization_id=h.organization_id AND p.source_id=h.source_id AND p.version=h.current_version
 JOIN emailmonitor.source_catalog s ON s.source_id=h.source_id
 WHERE e.organization_id=p_org AND e.id=p_export
 AND o.status='active' AND o.deletion_generation=e.deletion_generation AND m.status='active' AND ii.active
 AND m.role IN ('owner','admin','data_steward') AND e.expires_at>clock_timestamp()
 AND e.state NOT IN ('revoked','expired','failed') AND p.version=e.policy_version
 AND p.state='approved' AND p.valid_until>clock_timestamp() AND s.enabled AND s.execution_mode='fixture'
 AND p.policy->>'purpose'=e.request->>'purpose' AND p.policy->'allowed_operations' ? 'export_contacts'
 AND (p.policy->>'export_contacts_allowed')::boolean AND 'export_contacts'=ANY(s.allowed_operations)
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.export_members em LEFT JOIN emailmonitor.author_email_associations a
 ON a.organization_id=em.organization_id AND a.batch_id=em.batch_id AND a.id=em.association_id
 WHERE em.organization_id=p_org AND em.export_id=p_export AND
 (a.id IS NULL OR a.revision<>em.association_revision OR a.state IN ('rejected','suppressed')
 OR NOT emailmonitor.publication_batch_state(p_org,em.batch_id)))
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.export_outcomes eo JOIN emailmonitor.jobs j
 ON j.organization_id=eo.organization_id AND j.id=eo.job_id
 WHERE eo.organization_id=p_org AND eo.export_id=p_export AND (j.row_version<>eo.job_revision
 OR NOT emailmonitor.publication_job_state(p_org,eo.job_id)
 OR emailmonitor.publication_outcome_state(p_org,eo.job_id,eo.item_id) IS DISTINCT FROM eo.document))),false)
$$;

CREATE FUNCTION emailmonitor.publication_export_entitlement(p_org uuid,p_export uuid) RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(EXISTS(SELECT 1 FROM emailmonitor.exports e
 JOIN emailmonitor.tenant_configuration c ON c.organization_id=e.organization_id
 JOIN emailmonitor.export_entitlements saved ON saved.organization_id=e.organization_id AND saved.export_id=e.id
 LEFT JOIN emailmonitor.export_artifacts a ON a.organization_id=e.organization_id AND a.export_id=e.id
 WHERE e.organization_id=p_org AND e.id=p_export
 AND (c.configuration->'entitlements'->>'exports_enabled')::boolean AND (saved.entitlements->>'exports_enabled')::boolean
 AND least((c.configuration->'entitlements'->>'max_parallel_export')::integer,(saved.entitlements->>'max_parallel_export')::integer)>0
 AND least((c.configuration->'entitlements'->>'max_export_bytes')::integer,(saved.entitlements->>'max_export_bytes')::integer)>0
 AND (e.state<>'ready' OR (a.body IS NOT NULL AND octet_length(a.body)<=least(
 (c.configuration->'entitlements'->>'max_export_bytes')::integer,(saved.entitlements->>'max_export_bytes')::integer)))),false)
$$;

-- Publisher enumeration and confirmation release identifiers only. Each send is
-- inside a short current-authority transaction; the worker independently claims
-- full snapshot/privacy/lease authority before reading or committing payloads.
CREATE FUNCTION emailmonitor.service_pending(p_principal uuid,p_limit integer)
 RETURNS TABLE(organization_id uuid,resource_id uuid,purpose text,generation bigint,
 event_id uuid,item_id uuid,phase text)
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF p_limit IS NULL OR p_limit<1 OR p_limit>100 THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.service_principals sp
 WHERE sp.id=p_principal AND sp.kind='publisher' AND sp.active
 AND sp.login_name=session_user AND sp.login_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user))
 THEN RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 RETURN QUERY SELECT d.organization_id,d.resource_id,d.purpose,d.generation,
 o.event_id,o.item_id,CASE i.work_kind WHEN 'discover' THEN 'fixture_io' ELSE 'parse' END
 FROM emailmonitor.service_delegations d JOIN emailmonitor.execution_outbox o
 ON o.organization_id=d.organization_id AND o.job_id=d.resource_id AND o.generation=d.generation
 JOIN emailmonitor.execution_items i ON i.organization_id=o.organization_id
 AND i.job_id=o.job_id AND i.id=o.item_id
 JOIN emailmonitor.jobs j ON j.organization_id=o.organization_id AND j.id=o.job_id
 WHERE d.principal_id=p_principal AND d.purpose='extraction'
 AND emailmonitor.service_caller_allowed(d.organization_id,d.id,'publisher')
 AND emailmonitor.publication_job_state(d.organization_id,d.resource_id)
 AND EXISTS(SELECT 1 FROM emailmonitor.tenant_configuration c JOIN emailmonitor.job_entitlements saved
 ON saved.organization_id=c.organization_id WHERE c.organization_id=d.organization_id
 AND saved.job_id=d.resource_id AND least(
 (c.configuration->'entitlements'->>'max_parallel_parse')::integer,
 (saved.entitlements->>'max_parallel_parse')::integer)>0)
 AND j.state IN ('queued','running') AND i.state IN ('pending','retry_wait')
 AND i.attempts<3 AND i.work_kind IN ('discover','article') AND o.published_at IS NULL
 UNION ALL SELECT d.organization_id,d.resource_id,d.purpose,d.generation,
 o.event_id,NULL::uuid,'export'::text FROM emailmonitor.service_delegations d
 JOIN emailmonitor.export_outbox o ON o.organization_id=d.organization_id
 AND o.export_id=d.resource_id AND o.generation=d.generation
 JOIN emailmonitor.exports e ON e.organization_id=o.organization_id AND e.id=o.export_id
 WHERE d.principal_id=p_principal AND d.purpose='export'
 AND emailmonitor.service_caller_allowed(d.organization_id,d.id,'publisher')
 AND emailmonitor.publication_export_state(d.organization_id,d.resource_id)
 AND emailmonitor.publication_export_entitlement(d.organization_id,d.resource_id)
 AND e.state='queued' AND o.published_at IS NULL
 ORDER BY 1,2,5 LIMIT p_limit;
END $$;

CREATE FUNCTION emailmonitor.service_publish_event(p_org uuid,p_resource uuid,p_purpose text,
 p_generation bigint,p_event uuid,p_item uuid,p_confirm boolean DEFAULT false) RETURNS text
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE delegation uuid; phase text;
BEGIN
 IF p_confirm IS NULL OR NOT emailmonitor.service_scope_allowed(p_org,p_resource,p_purpose,'publisher')
 THEN RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 delegation:=nullif(current_setting('emailmonitor.service_delegation',true),'')::uuid;
 PERFORM emailmonitor.service_authority_fence(p_org,delegation,'publisher');
 PERFORM 1 FROM emailmonitor.tenant_configuration WHERE organization_id=p_org FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.lifecycle_configuration WHERE organization_id=p_org FOR SHARE NOWAIT;
 IF NOT emailmonitor.privacy_source_state(p_org) THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 IF p_purpose='extraction' THEN
 IF NOT emailmonitor.publication_job_state(p_org,p_resource) OR NOT EXISTS(
 SELECT 1 FROM emailmonitor.tenant_configuration c JOIN emailmonitor.job_entitlements j
 ON j.organization_id=c.organization_id WHERE c.organization_id=p_org AND j.job_id=p_resource
 AND least((c.configuration->'entitlements'->>'max_parallel_parse')::integer,
 (j.entitlements->>'max_parallel_parse')::integer)>0) THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 PERFORM 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_resource FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.execution_items WHERE organization_id=p_org
 AND job_id=p_resource AND id=p_item FOR SHARE NOWAIT;
 SELECT CASE i.work_kind WHEN 'discover' THEN 'fixture_io' WHEN 'article' THEN 'parse' END INTO phase
 FROM emailmonitor.execution_outbox o JOIN emailmonitor.execution_items i
 ON i.organization_id=o.organization_id AND i.job_id=o.job_id AND i.id=o.item_id
 JOIN emailmonitor.jobs j ON j.organization_id=o.organization_id AND j.id=o.job_id
 WHERE o.organization_id=p_org AND o.job_id=p_resource AND o.item_id=p_item
 AND o.event_id=p_event AND o.generation=p_generation AND j.generation=p_generation
 AND j.state IN ('queued','running') AND i.state IN ('pending','retry_wait')
 AND i.attempts<3 AND o.published_at IS NULL
 AND emailmonitor.privacy_job_state(p_org,p_resource) FOR UPDATE OF o NOWAIT;
 IF phase IS NULL THEN RETURN NULL; END IF;
 IF p_confirm THEN UPDATE emailmonitor.execution_outbox SET published_at=clock_timestamp()
 WHERE organization_id=p_org AND job_id=p_resource AND event_id=p_event; END IF;
 ELSIF p_purpose='export' AND p_item IS NULL THEN
 PERFORM 1 FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_resource FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.association_batches b JOIN emailmonitor.export_members em
 ON em.organization_id=b.organization_id AND em.batch_id=b.id
 WHERE em.organization_id=p_org AND em.export_id=p_resource ORDER BY b.id FOR SHARE OF b NOWAIT;
 PERFORM 1 FROM emailmonitor.author_email_associations a JOIN emailmonitor.export_members em
 ON em.organization_id=a.organization_id AND em.batch_id=a.batch_id AND em.association_id=a.id
 WHERE em.organization_id=p_org AND em.export_id=p_resource ORDER BY a.batch_id,a.id FOR SHARE OF a NOWAIT;
 PERFORM 1 FROM emailmonitor.jobs j WHERE j.organization_id=p_org AND (
 EXISTS(SELECT 1 FROM emailmonitor.export_outcomes eo WHERE eo.organization_id=p_org
 AND eo.export_id=p_resource AND eo.job_id=j.id) OR EXISTS(
 SELECT 1 FROM emailmonitor.export_members em JOIN emailmonitor.association_batches b
 ON b.organization_id=em.organization_id AND b.id=em.batch_id
 WHERE em.organization_id=p_org AND em.export_id=p_resource AND b.job_id=j.id))
 ORDER BY j.id FOR SHARE OF j NOWAIT;
 PERFORM 1 FROM emailmonitor.execution_items i JOIN emailmonitor.export_outcomes eo
 ON eo.organization_id=i.organization_id AND eo.job_id=i.job_id AND eo.item_id=i.id
 WHERE eo.organization_id=p_org AND eo.export_id=p_resource ORDER BY i.job_id,i.id FOR SHARE OF i NOWAIT;
 PERFORM 1 FROM emailmonitor.article_observations a WHERE a.organization_id=p_org AND (
 EXISTS(SELECT 1 FROM emailmonitor.export_members em JOIN emailmonitor.association_batches b
 ON b.organization_id=em.organization_id AND b.id=em.batch_id
 WHERE em.organization_id=p_org AND em.export_id=p_resource
 AND b.job_id=a.job_id AND b.article_url=a.article_url) OR EXISTS(
 SELECT 1 FROM emailmonitor.export_outcomes eo JOIN emailmonitor.execution_items i
 ON i.organization_id=eo.organization_id AND i.job_id=eo.job_id AND i.id=eo.item_id
 WHERE eo.organization_id=p_org AND eo.export_id=p_resource
 AND COALESCE(i.inherited_job_id,i.job_id)=a.job_id AND i.input_url=a.article_url))
 ORDER BY a.job_id,a.article_url FOR SHARE OF a NOWAIT;
 IF NOT emailmonitor.publication_export_state(p_org,p_resource)
 OR NOT emailmonitor.publication_export_entitlement(p_org,p_resource) THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 PERFORM 1 FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_resource FOR SHARE NOWAIT;
 SELECT 'export' INTO phase FROM emailmonitor.export_outbox o JOIN emailmonitor.exports e
 ON e.organization_id=o.organization_id AND e.id=o.export_id
 WHERE o.organization_id=p_org AND o.export_id=p_resource AND o.event_id=p_event
 AND o.generation=p_generation AND e.generation=p_generation AND e.state='queued'
 AND o.published_at IS NULL FOR UPDATE OF o NOWAIT;
 IF phase IS NULL THEN RETURN NULL; END IF;
 IF p_confirm THEN UPDATE emailmonitor.export_outbox SET published_at=clock_timestamp()
 WHERE organization_id=p_org AND export_id=p_resource AND event_id=p_event; END IF;
 ELSE RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 PERFORM emailmonitor.service_authority_fence(p_org,delegation,'publisher');
 RETURN phase;
END $$;
GRANT EXECUTE ON FUNCTION emailmonitor.service_pending(uuid,integer),
 emailmonitor.service_publish_event(uuid,uuid,text,bigint,uuid,uuid,boolean)
 TO emailmonitor_publisher;

CREATE FUNCTION emailmonitor.service_identity(p_principal uuid,p_kind text) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE org uuid;
BEGIN
 SELECT sp.organization_id INTO org FROM emailmonitor.service_principals sp JOIN pg_roles r
 ON r.oid=sp.login_oid AND r.rolname=sp.login_name WHERE sp.id=p_principal
 AND sp.kind=p_kind AND sp.active AND r.rolname=session_user AND r.rolcanlogin
 AND emailmonitor.service_login_safe(r.oid)
 AND NOT r.rolsuper AND NOT r.rolbypassrls
 AND NOT r.rolcreaterole AND NOT r.rolcreatedb AND NOT r.rolreplication
 AND NOT has_function_privilege(r.oid,
 'emailmonitor.establish_session(text,text,text,text)','EXECUTE')
 AND p_kind IN ('worker','publisher')
 AND pg_has_role(r.oid,'emailmonitor_'||p_kind,'MEMBER')
 AND NOT pg_has_role(r.oid,CASE p_kind WHEN 'worker' THEN 'emailmonitor_publisher'
 ELSE 'emailmonitor_worker' END,'MEMBER')
 AND NOT pg_has_role(r.oid,'emailmonitor_owner','MEMBER')
 AND NOT pg_has_role(r.oid,'emailmonitor_runtime','MEMBER')
 AND NOT pg_has_role(r.oid,'emailmonitor_authenticator','MEMBER');
 IF org IS NULL THEN RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 RETURN org;
END $$;
GRANT EXECUTE ON FUNCTION emailmonitor.service_identity(uuid,text)
 TO emailmonitor_worker,emailmonitor_publisher;

CREATE FUNCTION emailmonitor.service_worklist(p_principal uuid,p_after_purpose text,
 p_after_resource uuid,p_limit integer)
 RETURNS TABLE(organization_id uuid,resource_id uuid,purpose text,generation bigint)
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF p_limit IS NULL OR p_limit<1 OR p_limit>100 OR
 ((p_after_purpose IS NULL)<>(p_after_resource IS NULL)) OR
 (p_after_purpose IS NOT NULL AND p_after_purpose NOT IN ('extraction','export')) THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 PERFORM emailmonitor.service_identity(p_principal,'worker');
 RETURN QUERY SELECT d.organization_id,d.resource_id,d.purpose,d.generation
 FROM emailmonitor.service_delegations d WHERE d.principal_id=p_principal
 AND emailmonitor.service_caller_allowed(d.organization_id,d.id,'worker')
 AND (p_after_resource IS NULL OR (d.purpose,d.resource_id)>(p_after_purpose,p_after_resource))
 AND ((d.purpose='extraction' AND EXISTS(SELECT 1 FROM emailmonitor.jobs j
 WHERE j.organization_id=d.organization_id AND j.id=d.resource_id
 AND j.state IN ('queued','running'))) OR (d.purpose='export' AND EXISTS(
 SELECT 1 FROM emailmonitor.exports e WHERE e.organization_id=d.organization_id
 AND e.id=d.resource_id AND e.state IN ('queued','running'))))
 ORDER BY d.purpose,d.resource_id LIMIT p_limit;
END $$;
GRANT EXECUTE ON FUNCTION emailmonitor.service_worklist(uuid,text,uuid,integer)
 TO emailmonitor_worker;

CREATE FUNCTION emailmonitor.service_schema_ready() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT (SELECT count(*)=1 AND min(version_num)='0014_service_authority' FROM public.alembic_version)
$$;
CREATE FUNCTION emailmonitor.service_api_binding_ready(p_org uuid,p_worker uuid,p_publisher uuid)
 RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.service_schema_ready() AND p_worker<>p_publisher AND EXISTS(
 SELECT 1 FROM pg_roles r WHERE r.rolname=session_user AND NOT r.rolsuper AND NOT r.rolbypassrls
 AND pg_has_role(r.oid,'emailmonitor_runtime','MEMBER')
 AND NOT pg_has_role(r.oid,'emailmonitor_worker','MEMBER')
 AND NOT pg_has_role(r.oid,'emailmonitor_publisher','MEMBER')
 AND NOT pg_has_role(r.oid,'emailmonitor_owner','MEMBER')
 AND NOT pg_has_role(r.oid,'emailmonitor_authenticator','MEMBER'))
 AND 2=(SELECT count(*) FROM emailmonitor.service_principals sp JOIN pg_roles r
 ON r.oid=sp.login_oid AND r.rolname=sp.login_name WHERE sp.organization_id=p_org
 AND sp.active AND emailmonitor.service_login_safe(r.oid) AND ((sp.id=p_worker AND sp.kind='worker') OR
 (sp.id=p_publisher AND sp.kind='publisher')) AND r.rolcanlogin AND NOT r.rolsuper
 AND NOT r.rolbypassrls AND NOT r.rolcreaterole AND NOT r.rolcreatedb
 AND NOT r.rolreplication AND pg_has_role(r.oid,'emailmonitor_'||sp.kind,'MEMBER')
 AND NOT pg_has_role(r.oid,CASE sp.kind WHEN 'worker' THEN 'emailmonitor_publisher'
 ELSE 'emailmonitor_worker' END,'MEMBER')
 AND NOT pg_has_role(r.oid,CASE sp.kind WHEN 'worker' THEN 'emailmonitor_publisher'
 ELSE 'emailmonitor_worker' END,'SET')
 AND NOT has_function_privilege(r.oid,
 'emailmonitor.establish_session(text,text,text,text)','EXECUTE')
 AND NOT pg_has_role(r.oid,'emailmonitor_owner','SET')
 AND NOT pg_has_role(r.oid,'emailmonitor_runtime','SET')
 AND NOT pg_has_role(r.oid,'emailmonitor_authenticator','SET')
 AND NOT pg_has_role(r.oid,'emailmonitor_owner','MEMBER')
 AND NOT pg_has_role(r.oid,'emailmonitor_runtime','MEMBER')
 AND NOT pg_has_role(r.oid,'emailmonitor_authenticator','MEMBER'))
$$;
GRANT EXECUTE ON FUNCTION emailmonitor.service_schema_ready()
 TO emailmonitor_runtime,emailmonitor_worker,emailmonitor_publisher;
GRANT EXECUTE ON FUNCTION emailmonitor.service_api_binding_ready(uuid,uuid,uuid)
 TO emailmonitor_runtime;

-- Newly introduced internal helpers have no PUBLIC execution path. Existing
-- explicit human grants are retained; service grants remain individually listed.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA emailmonitor FROM PUBLIC;
RESET ROLE;
GRANT SELECT ON public.alembic_version TO emailmonitor_owner;
