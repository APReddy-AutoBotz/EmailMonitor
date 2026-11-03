-- Disposable synthetic data only. Private keyed privacy indexes are not identities.
SET ROLE emailmonitor_owner;
CREATE TABLE emailmonitor.lifecycle_configuration (
 organization_id uuid PRIMARY KEY REFERENCES emailmonitor.organizations,
 revision bigint NOT NULL DEFAULT 1 CHECK(revision>=1),
 retention jsonb NOT NULL DEFAULT '{"raw_hours":24,"excerpt_days":30,"contact_days":90,"export_hours":24,"audit_days":365,"idempotency_hours":24}',
 next_due_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE emailmonitor.lifecycle_job_deadlines (
 organization_id uuid NOT NULL,job_id uuid NOT NULL,contact_deadline timestamptz NOT NULL,excerpt_deadline timestamptz NOT NULL,
 PRIMARY KEY(organization_id,job_id),FOREIGN KEY(organization_id,job_id) REFERENCES emailmonitor.jobs
);
CREATE TABLE emailmonitor.privacy_keys (
 organization_id uuid PRIMARY KEY REFERENCES emailmonitor.organizations,
 key bytea NOT NULL CHECK(octet_length(key)=32)
);
CREATE TABLE emailmonitor.privacy_suppressions (
 organization_id uuid NOT NULL REFERENCES emailmonitor.organizations,id uuid NOT NULL,
 kind text NOT NULL CHECK(kind IN ('source','domain','contact')),
 digest bytea NOT NULL CHECK(octet_length(digest)=32),
 reason text NOT NULL CHECK(reason IN ('privacy_request','source_restriction')),
 active boolean NOT NULL DEFAULT true,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 withdrawn_at timestamptz,PRIMARY KEY(organization_id,id),UNIQUE(organization_id,kind,digest)
);
CREATE TABLE emailmonitor.deletion_tombstones (
 organization_id uuid NOT NULL REFERENCES emailmonitor.organizations,id uuid NOT NULL,
 job_id uuid,reason text NOT NULL CHECK(reason IN ('privacy_request','retention_expired','owner_request')),
 stage text NOT NULL DEFAULT 'fenced' CHECK(stage IN ('fenced','purged')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),purged_at timestamptz,
 PRIMARY KEY(organization_id,id),FOREIGN KEY(organization_id,job_id) REFERENCES emailmonitor.jobs
);
CREATE UNIQUE INDEX lifecycle_job_tombstone ON emailmonitor.deletion_tombstones(organization_id,job_id) WHERE job_id IS NOT NULL;
CREATE UNIQUE INDEX lifecycle_org_tombstone ON emailmonitor.deletion_tombstones(organization_id) WHERE job_id IS NULL;
CREATE TABLE emailmonitor.lifecycle_purge_context (
 transaction_id bigint NOT NULL,organization_id uuid NOT NULL,job_id uuid NOT NULL,
 PRIMARY KEY(transaction_id,organization_id,job_id)
);
CREATE TABLE emailmonitor.support_contexts (
 organization_id uuid NOT NULL,id uuid NOT NULL,grantee_id uuid NOT NULL,job_id uuid NOT NULL,
 approved_by uuid NOT NULL,reason text NOT NULL CHECK(reason IN ('synthetic_incident','synthetic_privacy_check')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),expires_at timestamptz NOT NULL,revoked_at timestamptz,
 PRIMARY KEY(organization_id,id),FOREIGN KEY(organization_id,grantee_id) REFERENCES emailmonitor.memberships(organization_id,identity_id),
 FOREIGN KEY(organization_id,approved_by) REFERENCES emailmonitor.memberships(organization_id,identity_id),
 FOREIGN KEY(organization_id,job_id) REFERENCES emailmonitor.jobs,
 CHECK(expires_at>created_at AND expires_at<=created_at+interval '4 hours')
);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['lifecycle_configuration','lifecycle_job_deadlines','privacy_keys','privacy_suppressions','deletion_tombstones','lifecycle_purge_context','support_contexts'] LOOP
 EXECUTE format('ALTER TABLE emailmonitor.%I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('ALTER TABLE emailmonitor.%I FORCE ROW LEVEL SECURITY',t);
 EXECUTE format('CREATE POLICY owner_all ON emailmonitor.%I TO emailmonitor_owner USING(true) WITH CHECK(true)',t);
 EXECUTE format('REVOKE ALL ON emailmonitor.%I FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator',t);
 END LOOP;
END $$;
CREATE FUNCTION emailmonitor.lifecycle_scope(p_org uuid,p_manager boolean DEFAULT false) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 -- Exclusive organization lock serializes privacy changes with existing SHARE fences.
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR UPDATE NOWAIT;
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false)
 OR emailmonitor.session_role(p_org) NOT IN ('owner','data_steward')
 OR (NOT p_manager AND emailmonitor.session_role(p_org)<>'owner') THEN
 RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 PERFORM 1 FROM emailmonitor.memberships WHERE organization_id=p_org AND identity_id=emailmonitor.job_actor() FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.identities WHERE id=emailmonitor.job_actor() FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.sessions WHERE token_hash=current_setting('emailmonitor.session_hash',true) FOR SHARE NOWAIT;
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) THEN RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 INSERT INTO emailmonitor.lifecycle_configuration(organization_id) VALUES(p_org) ON CONFLICT DO NOTHING;
 INSERT INTO emailmonitor.lifecycle_job_deadlines(organization_id,job_id,contact_deadline,excerpt_deadline)
 SELECT p_org,j.id,j.created_at+interval '90 days',j.created_at+interval '30 days' FROM emailmonitor.jobs j WHERE j.organization_id=p_org ON CONFLICT DO NOTHING;
 INSERT INTO emailmonitor.privacy_keys(organization_id,key)
 VALUES(p_org,sha256(convert_to(gen_random_uuid()::text||gen_random_uuid()::text,'UTF8'))) ON CONFLICT DO NOTHING;
END $$;
CREATE FUNCTION emailmonitor.privacy_digest(p_org uuid,p_kind text,p_value text) RETURNS bytea
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE k bytea; inner_pad bytea:=decode(repeat('36',64),'hex');outer_pad bytea:=decode(repeat('5c',64),'hex'); n integer;
BEGIN
 SELECT key INTO k FROM emailmonitor.privacy_keys WHERE organization_id=p_org;
 IF k IS NULL THEN RETURN NULL; END IF;
 -- RFC2104 HMAC-SHA256 using PostgreSQL core byte operations, no extension.
 FOR n IN 0..31 LOOP
 inner_pad=set_byte(inner_pad,n,get_byte(inner_pad,n)#get_byte(k,n));
 outer_pad=set_byte(outer_pad,n,get_byte(outer_pad,n)#get_byte(k,n));
 END LOOP;
 RETURN sha256(outer_pad||sha256(inner_pad||convert_to('emailmonitor/privacy/v1/'||p_kind||'/'||lower(p_value),'UTF8')));
END $$;
CREATE FUNCTION emailmonitor.privacy_source_allowed(p_org uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(emailmonitor.tenant_allowed(p_org),false) AND NOT EXISTS(SELECT 1 FROM emailmonitor.deletion_tombstones WHERE organization_id=p_org AND job_id IS NULL)
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.privacy_suppressions WHERE organization_id=p_org AND active AND kind='source'
 AND digest=emailmonitor.privacy_digest(p_org,'source','synthetic-publisher'))
$$;
CREATE FUNCTION emailmonitor.privacy_job_allowed(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.privacy_source_allowed(p_org) AND NOT EXISTS(SELECT 1 FROM emailmonitor.lifecycle_job_deadlines d WHERE d.organization_id=p_org AND d.job_id=p_job
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
CREATE FUNCTION emailmonitor.privacy_canonical_allowed(p_kind text,p_value text) RETURNS boolean
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,emailmonitor AS $$
DECLARE domain_pattern text:='[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+';
 local_pattern text:=$pattern$[a-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*$pattern$;
BEGIN
 IF p_kind IS NULL OR p_value IS NULL OR length(p_value) NOT BETWEEN 1 AND 254 OR octet_length(p_value)<>length(p_value) THEN RETURN false; END IF;
 IF p_kind='source' THEN RETURN lower(p_value)='synthetic-publisher'; END IF;
 IF p_kind='domain' THEN RETURN lower(p_value) ~ ('^'||domain_pattern||'$'); END IF;
 IF p_kind='contact' THEN RETURN length(split_part(p_value,'@',1))<=64 AND lower(p_value) ~ ('^'||local_pattern||'@'||domain_pattern||'$'); END IF;
 RETURN false;
END $$;
REVOKE ALL ON FUNCTION emailmonitor.privacy_canonical_allowed(text,text) FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
CREATE FUNCTION emailmonitor.privacy_payload_allowed(p_org uuid,p_document jsonb) RETURNS boolean
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE value text; domain text;
BEGIN
 IF p_document IS NULL OR jsonb_typeof(p_document)<>'object' OR octet_length(p_document::text)>2097152 OR NOT emailmonitor.privacy_source_allowed(p_org) THEN RETURN false; END IF;
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

CREATE OR REPLACE FUNCTION emailmonitor.job_write_allowed(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.privacy_job_allowed(p_org,p_job) AND emailmonitor.tenant_allowed(p_org) AND EXISTS(SELECT 1 FROM emailmonitor.jobs j
 WHERE j.organization_id=p_org AND j.id=p_job AND
 (emailmonitor.session_role(p_org) IN ('owner','admin','data_steward') OR
  (emailmonitor.session_role(p_org)='operator' AND j.created_by=emailmonitor.job_actor())))
$$;

CREATE OR REPLACE FUNCTION emailmonitor.execution_read_allowed(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.privacy_job_allowed(p_org,p_job) AND COALESCE(emailmonitor.tenant_allowed(p_org),false) AND EXISTS(
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
 AND p.policy->'allowed_operations' ? 'fetch_html' AND p.policy->'allowed_operations' ? 'extract_contacts'
 AND 'fetch_html'=ANY(s.allowed_operations) AND 'extract_contacts'=ANY(s.allowed_operations)
 AND 'synthetic.publisher.example'=ANY(s.allowed_hosts) AND p.policy->'allowed_hosts' ? 'synthetic.publisher.example'
 AND (p.policy->'retention'->>'contact_days')::integer>0) AND EXISTS(
 SELECT 1 FROM emailmonitor.sessions ss JOIN emailmonitor.identities ii ON ii.id=ss.identity_id
 WHERE ss.token_hash=current_setting('emailmonitor.session_hash',true) AND ss.revoked_at IS NULL
 AND ss.expires_at>statement_timestamp() AND ii.active AND ss.permission_revision=ii.permission_revision)
$$;

CREATE OR REPLACE FUNCTION emailmonitor.association_visible(p_org uuid,p_batch uuid) RETURNS boolean
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE b emailmonitor.association_batches;
BEGIN
 IF NOT emailmonitor.privacy_job_allowed(p_org,(SELECT job_id FROM emailmonitor.association_batches WHERE organization_id=p_org AND id=p_batch)) THEN RETURN false; END IF;
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) THEN RETURN false; END IF;
 SELECT * INTO b FROM emailmonitor.association_batches WHERE organization_id=p_org AND id=p_batch;
 RETURN b.id IS NOT NULL AND EXISTS(SELECT 1 FROM emailmonitor.article_observations a WHERE a.organization_id=p_org AND a.job_id=b.job_id AND a.article_url=b.article_url AND emailmonitor.privacy_payload_allowed(p_org,a.observation) AND NOT EXISTS(SELECT 1 FROM emailmonitor.lifecycle_configuration c WHERE c.organization_id=p_org AND jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")') AND a.observed_at+make_interval(days=>(c.retention->>'excerpt_days')::integer)<=clock_timestamp())) AND b.sealed AND b.expires_at>statement_timestamp() AND EXISTS(
 SELECT 1 FROM emailmonitor.sessions ss JOIN emailmonitor.identities ii ON ii.id=ss.identity_id
 WHERE ss.token_hash=current_setting('emailmonitor.session_hash',true) AND ss.revoked_at IS NULL
 AND ss.expires_at>statement_timestamp() AND ii.active AND ss.permission_revision=ii.permission_revision) AND EXISTS(
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
 AND (a.observation->>'route'<>'browser_dom' OR (p.policy->'allowed_operations' ? 'browser' AND 'browser'=ANY(s.allowed_operations)))
 AND (NOT jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")') OR (
 p.policy->'allowed_operations' ? 'retain_excerpt' AND 'retain_excerpt'=ANY(s.allowed_operations) AND (p.policy->'retention'->>'excerpt_days')::integer>0)));
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.source_resource_current(p_org uuid,p_id uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.privacy_source_allowed(p_org) AND NOT EXISTS(SELECT 1 FROM emailmonitor.source_resource_requests rr WHERE rr.organization_id=p_org AND rr.id=p_id AND rr.job_id IS NOT NULL AND NOT emailmonitor.privacy_job_allowed(p_org,rr.job_id)) AND EXISTS(SELECT 1 FROM emailmonitor.source_resource_requests r
 JOIN emailmonitor.organizations o ON o.id=r.organization_id AND o.status='active'
 JOIN emailmonitor.memberships m ON m.organization_id=r.organization_id AND m.identity_id=r.actor_id
 JOIN emailmonitor.identities i ON i.id=m.identity_id AND i.active
 JOIN emailmonitor.sessions ss ON ss.token_hash=r.session_hash AND ss.identity_id=i.id
 JOIN emailmonitor.source_policy_heads h ON h.organization_id=r.organization_id AND h.source_id=r.source_id
 JOIN emailmonitor.source_policies p ON p.organization_id=h.organization_id AND p.source_id=h.source_id AND p.version=h.current_version
 JOIN emailmonitor.source_catalog c ON c.source_id=r.source_id AND c.enabled AND c.execution_mode='fixture'
 JOIN emailmonitor.tenant_configuration cfg ON cfg.organization_id=r.organization_id
 WHERE r.organization_id=p_org AND r.id=p_id AND p.version=r.policy_version
 AND r.deletion_generation=o.deletion_generation
 AND m.status='active' AND m.role IN ('owner','admin','data_steward','operator')
 AND ss.revoked_at IS NULL AND ss.expires_at>statement_timestamp() AND ss.permission_revision=i.permission_revision
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

CREATE OR REPLACE FUNCTION emailmonitor.job_permission_fence(p_org uuid,p_job uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE actor uuid; source text;
BEGIN
 IF NOT emailmonitor.privacy_job_allowed(p_org,p_job) THEN RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 IF NOT COALESCE(emailmonitor.job_write_allowed(p_org,p_job),false) THEN
 RAISE EXCEPTION 'JOB_UNAVAILABLE'; END IF;
 actor=emailmonitor.job_actor();
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
 IF NOT COALESCE(emailmonitor.job_write_allowed(p_org,p_job),false) OR NOT EXISTS(
 SELECT 1 FROM emailmonitor.sessions WHERE token_hash=current_setting('emailmonitor.session_hash',true)
 AND revoked_at IS NULL AND expires_at>clock_timestamp()) THEN RAISE EXCEPTION 'JOB_UNAVAILABLE'; END IF;
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.results_fence(p_org uuid,p_export boolean DEFAULT false,
 p_requester uuid DEFAULT NULL,p_policy boolean DEFAULT true) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE actor uuid; p emailmonitor.source_policies; s emailmonitor.source_catalog;
BEGIN
 IF NOT emailmonitor.privacy_source_allowed(p_org) OR (p_export AND EXISTS(SELECT 1 FROM emailmonitor.lifecycle_configuration WHERE organization_id=p_org AND (retention->>'export_hours')::integer=0)) THEN RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) THEN
 RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 actor:=emailmonitor.job_actor();
 -- NOWAIT refuses contention rather than introducing a reverse-lock wait against
 -- existing membership triggers; current authority is rechecked after every lock.
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.memberships WHERE organization_id=p_org
 AND identity_id IN (actor,COALESCE(p_requester,actor)) ORDER BY identity_id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.identities WHERE id IN (actor,COALESCE(p_requester,actor))
 ORDER BY id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.sessions WHERE token_hash=current_setting('emailmonitor.session_hash',true)
 FOR SHARE NOWAIT;
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) OR NOT EXISTS(
 SELECT 1 FROM emailmonitor.organizations WHERE id=p_org AND status='active') OR NOT EXISTS(
 SELECT 1 FROM emailmonitor.sessions ss JOIN emailmonitor.identities ii ON ii.id=ss.identity_id
 WHERE ss.token_hash=current_setting('emailmonitor.session_hash',true) AND ss.revoked_at IS NULL
 AND ss.expires_at>clock_timestamp() AND ii.active AND ss.permission_revision=ii.permission_revision)
 OR (p_export AND emailmonitor.session_role(p_org) NOT IN ('owner','admin','data_steward'))
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
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.privacy_source_allowed(p_org) AND NOT EXISTS(SELECT 1 FROM emailmonitor.exports ee JOIN emailmonitor.lifecycle_configuration cc ON cc.organization_id=ee.organization_id WHERE ee.organization_id=p_org AND ee.id=p_export AND ee.created_at+make_interval(hours=>(cc.retention->>'export_hours')::integer)<=clock_timestamp()) AND COALESCE(EXISTS(SELECT 1 FROM emailmonitor.exports e JOIN emailmonitor.organizations o
 ON o.id=e.organization_id JOIN emailmonitor.memberships m ON m.organization_id=e.organization_id
 AND m.identity_id=e.requested_by JOIN emailmonitor.identities ii ON ii.id=m.identity_id
 JOIN emailmonitor.source_policy_heads h ON h.organization_id=e.organization_id AND h.source_id='synthetic-publisher'
 JOIN emailmonitor.source_policies p ON p.organization_id=h.organization_id AND p.source_id=h.source_id AND p.version=h.current_version
 JOIN emailmonitor.source_catalog s ON s.source_id=h.source_id
 WHERE e.organization_id=p_org AND e.id=p_export AND emailmonitor.tenant_allowed(p_org)
 AND emailmonitor.session_role(p_org) IN ('owner','admin','data_steward')
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

CREATE OR REPLACE FUNCTION emailmonitor.guard_article_observation() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE d emailmonitor.discovery; j emailmonitor.jobs; source_hash text; p jsonb; days integer;
BEGIN
 IF NOT emailmonitor.privacy_payload_allowed(NEW.organization_id,NEW.observation) OR NOT emailmonitor.privacy_excerpt_allowed(NEW.organization_id,NEW.observed_at,NEW.observation) OR (jsonb_path_exists(NEW.observation,'$.**.excerpt ? (@ != "")') AND EXISTS(SELECT 1 FROM emailmonitor.lifecycle_job_deadlines deadline WHERE deadline.organization_id=NEW.organization_id AND deadline.job_id=NEW.job_id AND deadline.excerpt_deadline<=clock_timestamp())) THEN RAISE EXCEPTION 'PRIVACY_SUPPRESSED' USING ERRCODE='EM014'; END IF;
 PERFORM emailmonitor.discovery_source_fence(NEW.organization_id,NEW.job_id,NEW.policy_version);
 SELECT * INTO d FROM emailmonitor.discovery WHERE organization_id=NEW.organization_id
 AND job_id=NEW.job_id FOR SHARE;
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=NEW.organization_id
 AND id=NEW.job_id FOR SHARE;
 IF j.state='running' AND NOT EXISTS(SELECT 1 FROM emailmonitor.execution_items i
 WHERE i.organization_id=NEW.organization_id AND i.job_id=NEW.job_id AND i.work_kind='article'
 AND i.input_url=NEW.article_url AND i.id::text=current_setting('emailmonitor.execution_item',true)) THEN
 RAISE EXCEPTION 'EXECUTION_WORK_FENCE' USING ERRCODE='EM010'; END IF;
 IF (NEW.generation<>d.generation AND NOT (TG_OP='UPDATE' AND NEW.generation=OLD.generation
 AND j.state='running' AND COALESCE(emailmonitor.execution_write_allowed(NEW.organization_id,NEW.job_id),false)))
 OR NEW.deletion_generation<>d.deletion_generation
 OR NEW.deletion_generation<>(SELECT deletion_generation FROM emailmonitor.organizations
 WHERE id=NEW.organization_id) OR NEW.policy_version<>d.policy_version
 OR NOT (d.checkpoint->'articles' ? NEW.article_url)
 OR NEW.discovery_revision>d.revision OR NEW.observation->>'url' IS DISTINCT FROM NEW.article_url
 OR NEW.observation->>'schema_version' IS DISTINCT FROM '1.0'
 OR NEW.observation->>'parser_version' IS DISTINCT FROM 'synthetic-html-v1'
 OR NEW.observation->>'identity_association_implemented' IS DISTINCT FROM 'false'
 OR COALESCE(NEW.observation->>'route','') NOT IN ('html','browser_dom')
 OR COALESCE(NEW.observation->>'status','') NOT IN ('observed','no_contact','requires_browser')
 OR COALESCE(jsonb_typeof(NEW.observation->'authors'),'')<>'array'
 OR COALESCE(jsonb_typeof(NEW.observation->'candidates'),'')<>'array'
 OR jsonb_array_length(NEW.observation->'authors') NOT BETWEEN 1 AND 100
 OR jsonb_array_length(NEW.observation->'candidates')>100
 OR COALESCE(NEW.observation->>'content_digest','') !~ '^[0-9a-f]{64}$'
 THEN RAISE EXCEPTION 'ARTICLE_OBSERVATION_FENCE'; END IF;
 SELECT policy INTO p FROM emailmonitor.source_policies WHERE organization_id=NEW.organization_id
 AND source_id='synthetic-publisher' AND version=NEW.policy_version;
 IF j.request->>'purpose' IS DISTINCT FROM p->>'purpose'
 OR NOT (p->'allowed_operations' ? 'extract_contacts')
 OR (p->'retention'->>'contact_days')::integer<=0
 OR NOT (p->'allowed_operations' ? 'fetch_html')
 THEN RAISE EXCEPTION 'ARTICLE_OBSERVATION_PERMISSION'; END IF;
 days := (p->'retention'->>'contact_days')::integer;
 IF jsonb_path_exists(NEW.observation,'$.**.excerpt ? (@ != "")') THEN
 IF NOT (p->'allowed_operations' ? 'retain_excerpt')
 OR (p->'retention'->>'excerpt_days')::integer<=0
 THEN RAISE EXCEPTION 'ARTICLE_OBSERVATION_EXCERPT'; END IF;
 days := LEAST(days,(p->'retention'->>'excerpt_days')::integer);
 END IF;
 NEW.observed_at := clock_timestamp();
 NEW.expires_at := NEW.observed_at+make_interval(days=>days);
 source_hash := CASE NEW.article_url
 WHEN 'https://synthetic.publisher.example/article-a.html' THEN '33c3bddb62834da34acb300b7c0bd7bb4c8728fb57e5ece43b8fc4e81920c3f0'
 WHEN 'https://synthetic.publisher.example/article-b.html' THEN '87cd02138f7cc3dfa921ccdf9b2a1613e21529c1c89c3f36fcf36fd0ba8530b1'
 WHEN 'https://synthetic.publisher.example/tooltip.html' THEN 'f5ef425b50becc43b78b5a94c120c698d2c11d3d394325112d02355a0c27a893'
 WHEN 'https://synthetic.publisher.example/no-contact.html' THEN 'e743113b240ab1e931df471a9a3d8bd0137fc89157d69803a9238de3c8985b01' END;
 IF NEW.source_digest IS DISTINCT FROM source_hash
 OR (NEW.observation->>'route'='html' AND NEW.observation->>'content_digest'<>source_hash)
 OR (NEW.observation->>'route'='html' AND NEW.observation->>'acquisition_digest' IS DISTINCT FROM source_hash)
 OR (NEW.observation->>'route'='browser_dom' AND NEW.observation->>'acquisition_digest'
 IS DISTINCT FROM '7c26b49fe73a02899f77c88ebea70abb1f256399b66ed9c3b41eab12b587f9e3')
 OR (NEW.observation->>'route'='browser_dom' AND (
 NEW.article_url<>'https://synthetic.publisher.example/tooltip.html'
 OR NOT COALESCE((j.request->'options'->>'allow_browser')::boolean,true)
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.source_policies p
 WHERE p.organization_id=NEW.organization_id AND p.source_id='synthetic-publisher'
 AND p.version=NEW.policy_version AND p.policy->'allowed_operations' ? 'browser')))
 OR (NEW.observation->>'status'='observed' AND jsonb_array_length(NEW.observation->'candidates')=0)
 OR (NEW.observation->>'status'<>'observed' AND jsonb_array_length(NEW.observation->'candidates')<>0)
 THEN RAISE EXCEPTION 'ARTICLE_OBSERVATION_PROVENANCE'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.observation->'candidates') candidate
 WHERE COALESCE(candidate->>'association_status','') NOT IN ('unmatched','needs_review')
 OR candidate->>'technical_status' IS DISTINCT FROM 'not_checked'
 OR candidate->>'delivery_status' IS DISTINCT FROM 'unverified'
 OR candidate->>'outreach_eligibility' IS DISTINCT FROM 'not_assessed')
 THEN RAISE EXCEPTION 'ARTICLE_OBSERVATION_NOT_ASSOCIATION'; END IF;
 IF TG_OP='INSERT' THEN
 IF NEW.revision<>1 OR NEW.discovery_revision<>d.revision
 THEN RAISE EXCEPTION 'ARTICLE_OBSERVATION_REVISION'; END IF;
 ELSE
 IF (NEW.organization_id,NEW.job_id,NEW.article_url,NEW.generation,
 NEW.deletion_generation,NEW.policy_version,NEW.discovery_revision,NEW.source_digest)
 IS DISTINCT FROM (OLD.organization_id,OLD.job_id,OLD.article_url,OLD.generation,
 OLD.deletion_generation,OLD.policy_version,OLD.discovery_revision,OLD.source_digest)
 OR NEW.revision<>OLD.revision+1 OR OLD.observation->>'status'<>'requires_browser'
 OR NEW.observation->>'route'<>'browser_dom' OR NEW.observation->>'status'<>'observed'
 THEN RAISE EXCEPTION 'ARTICLE_OBSERVATION_IMMUTABLE'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.guard_job() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF TG_OP='INSERT' AND (NOT emailmonitor.privacy_source_allowed(NEW.organization_id) OR EXISTS(SELECT 1 FROM emailmonitor.deletion_tombstones WHERE organization_id=NEW.organization_id AND (job_id IS NULL OR job_id=NEW.id))) THEN
 RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 IF TG_OP='UPDATE' AND EXISTS(SELECT 1 FROM emailmonitor.lifecycle_purge_context
 WHERE transaction_id=txid_current() AND organization_id=OLD.organization_id AND job_id=OLD.id) THEN
 IF (NEW.organization_id,NEW.id,NEW.created_by,NEW.kind,NEW.source_id,NEW.policy_version,NEW.created_at)
 IS DISTINCT FROM (OLD.organization_id,OLD.id,OLD.created_by,OLD.kind,OLD.source_id,OLD.policy_version,OLD.created_at)
 OR NEW.request IS DISTINCT FROM '{"lifecycle":"content_removed"}'::jsonb
 OR NEW.generation<>OLD.generation+1 OR NEW.state IS DISTINCT FROM
 (CASE WHEN OLD.state IN ('cancelled','completed','completed_partial','failed') THEN OLD.state ELSE 'cancelled' END)
 THEN RAISE EXCEPTION 'LIFECYCLE_PURGE_FENCE' USING ERRCODE='EM014'; END IF;
 NEW.row_version=OLD.row_version+1;RETURN NEW;
 END IF;
 IF TG_OP='UPDATE' THEN
 IF (NEW.organization_id,NEW.id,NEW.created_by,NEW.kind,NEW.request,NEW.source_id,NEW.policy_version,NEW.created_at)
 IS DISTINCT FROM (OLD.organization_id,OLD.id,OLD.created_by,OLD.kind,OLD.request,OLD.source_id,OLD.policy_version,OLD.created_at)
 THEN RAISE EXCEPTION 'JOB_INPUT_IMMUTABLE'; END IF;
 IF NEW.kind='extraction' AND NEW.state IN ('ready','queued','running') AND (
 NOT EXISTS(SELECT 1 FROM emailmonitor.execution_runs WHERE organization_id=NEW.organization_id AND job_id=NEW.id)
 OR NOT COALESCE(emailmonitor.execution_read_allowed(NEW.organization_id,NEW.id),false))
 THEN RAISE EXCEPTION 'EXECUTION_REQUIRED'; END IF;
 IF NEW.kind='extraction' AND NEW.state IN ('completed','completed_partial','failed') THEN
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.execution_runs WHERE organization_id=NEW.organization_id AND job_id=NEW.id)
 OR EXISTS(SELECT 1 FROM emailmonitor.execution_items WHERE organization_id=NEW.organization_id
 AND job_id=NEW.id AND state IN ('pending','running','retry_wait'))
 THEN RAISE EXCEPTION 'TERMINAL_EXECUTION_REQUIRED'; END IF;
 IF NEW.state='completed' AND (NOT EXISTS(SELECT 1 FROM emailmonitor.discovery
 WHERE organization_id=NEW.organization_id AND job_id=NEW.id AND checkpoint->>'discovery_complete'='true')
 OR EXISTS(SELECT 1 FROM emailmonitor.execution_items WHERE organization_id=NEW.organization_id AND job_id=NEW.id
 AND state IN ('policy_blocked','access_blocked','unsupported','skipped','failed','cancelled')))
 THEN RAISE EXCEPTION 'COMPLETE_EXECUTION_REQUIRED'; END IF;
 END IF;
 IF NEW.kind='extraction' AND ((NEW.state='paused' AND EXISTS(SELECT 1 FROM emailmonitor.execution_items
 WHERE organization_id=NEW.organization_id AND job_id=NEW.id AND state='running')) OR
 (NEW.state='cancelled' AND OLD.state<>'draft' AND EXISTS(SELECT 1 FROM emailmonitor.execution_items
 WHERE organization_id=NEW.organization_id AND job_id=NEW.id AND state IN ('pending','running','retry_wait'))))
 THEN RAISE EXCEPTION 'CLEARED_LEASES_REQUIRED'; END IF;
 IF OLD.state IN ('cancelled','completed','completed_partial','failed') THEN RAISE EXCEPTION 'TERMINAL_JOB'; END IF;
 IF NEW.state<>OLD.state AND NOT (
 (OLD.state='draft' AND NEW.state IN ('awaiting_approval','ready','cancelled')) OR
 (OLD.state='awaiting_approval' AND NEW.state IN ('ready','cancelled')) OR
 (OLD.state='ready' AND (NEW.state IN ('queued','cancelled') OR (NEW.kind='extraction' AND NEW.state='cancelling'))) OR
 (OLD.state='queued' AND (NEW.state IN ('running','pausing','cancelling') OR
 (NEW.kind='extraction' AND NEW.state='completed_partial' AND EXISTS(SELECT 1 FROM emailmonitor.execution_runs WHERE organization_id=NEW.organization_id AND job_id=NEW.id)
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.execution_items WHERE organization_id=NEW.organization_id AND job_id=NEW.id AND state IN ('pending','running','retry_wait'))))) OR
 (OLD.state='running' AND NEW.state IN ('pausing','cancelling','completed','completed_partial','failed')) OR
 (OLD.state='pausing' AND NEW.state IN ('paused','cancelling')) OR
 (OLD.state='paused' AND NEW.state IN ('queued','cancelling')) OR
 (OLD.state='cancelling' AND NEW.state='cancelled')) THEN RAISE EXCEPTION 'INVALID_JOB_TRANSITION'; END IF;
 IF NEW.generation<>OLD.generation+(CASE WHEN (NEW.state IN ('pausing','cancelling') OR (NEW.state='cancelled' AND OLD.state='draft')) AND NEW.state<>OLD.state THEN 1 ELSE 0 END)
 THEN RAISE EXCEPTION 'GENERATION_REQUIRED'; END IF;
 NEW.row_version=OLD.row_version+1;
 ELSE
 IF NEW.generation<>1 OR NEW.row_version<>1 OR NEW.state NOT IN ('draft','queued')
 OR (NEW.kind='extraction' AND NEW.state<>'draft') THEN RAISE EXCEPTION 'INITIAL_JOB_REQUIRED'; END IF;
 END IF;
 RETURN NEW;
END $$;

-- RESTRICTIVE policies compose with existing current-tenant/source policies.
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['jobs','job_items','job_outbox','job_idempotency','usage_reservations','usage_events','discovery','discovery_outbox','article_observations','execution_runs','execution_items','execution_outbox','execution_events','execution_effects','job_entitlements','admission_requests','resolution_accounts','source_resource_requests'] LOOP
 IF t='jobs' THEN
 EXECUTE format('CREATE POLICY lifecycle_read ON emailmonitor.%I AS RESTRICTIVE FOR SELECT TO emailmonitor_runtime USING(emailmonitor.privacy_job_allowed(organization_id,id))',t);
 ELSE
 EXECUTE format('CREATE POLICY lifecycle_read ON emailmonitor.%I AS RESTRICTIVE FOR SELECT TO emailmonitor_runtime USING(job_id IS NULL OR emailmonitor.privacy_job_allowed(organization_id,job_id))',t);
 END IF;
 END LOOP;
END $$;
CREATE POLICY privacy_read ON emailmonitor.article_observations AS RESTRICTIVE FOR SELECT TO emailmonitor_runtime
 USING(emailmonitor.privacy_payload_allowed(organization_id,observation));
CREATE FUNCTION emailmonitor.privacy_excerpt_allowed(p_org uuid,p_observed timestamptz,p_document jsonb) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(emailmonitor.tenant_allowed(p_org),false) AND NOT EXISTS(SELECT 1 FROM emailmonitor.lifecycle_configuration c
 WHERE c.organization_id=p_org AND jsonb_path_exists(p_document,'$.**.excerpt ? (@ != "")')
 AND p_observed+make_interval(days=>(c.retention->>'excerpt_days')::integer)<=clock_timestamp())
$$;
CREATE POLICY retention_read ON emailmonitor.article_observations AS RESTRICTIVE FOR SELECT TO emailmonitor_runtime
 USING(emailmonitor.privacy_excerpt_allowed(organization_id,observed_at,observation));
CREATE FUNCTION emailmonitor.lifecycle_receipt(p_org uuid,p_id uuid) RETURNS jsonb
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT jsonb_build_object('organization_id',organization_id,'id',id,'job_id',job_id,'reason',reason,
 'stage',stage,'created_at',created_at,'purged_at',purged_at,'backup_replay_required',true)
 FROM emailmonitor.deletion_tombstones WHERE organization_id=p_org AND id=p_id
$$;
CREATE FUNCTION emailmonitor.lifecycle_invalidate_exports(p_org uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 -- Conservative tenant-wide invalidation avoids unsnapshotted and empty-export gaps.
 UPDATE emailmonitor.exports SET state='revoked',reason='user_revoked',generation=generation+1,
 revision=revision+1,lease_nonce=NULL,lease_until=NULL WHERE organization_id=p_org AND state NOT IN ('revoked','expired','failed');
 DELETE FROM emailmonitor.export_artifacts WHERE organization_id=p_org;
END $$;
CREATE FUNCTION emailmonitor.lifecycle_fence_job(p_org uuid,p_job uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE released integer;
BEGIN
 PERFORM 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 INSERT INTO emailmonitor.lifecycle_purge_context VALUES(txid_current(),p_org,p_job);
 UPDATE emailmonitor.execution_items SET state='cancelled',reason='user_cancelled',lease_token=NULL,
 lease_until=NULL,lease_generation=NULL,lease_deletion_generation=NULL,effect_id=NULL,completed_at=clock_timestamp()
 WHERE organization_id=p_org AND job_id=p_job AND state IN ('pending','running','retry_wait');
 -- Synthetic probe content is purged in stage two; its lease is already invalidated by generation.
 UPDATE emailmonitor.jobs SET request='{"lifecycle":"content_removed"}',generation=generation+1,
 state=CASE WHEN state IN ('cancelled','completed','completed_partial','failed') THEN state ELSE 'cancelled' END
 WHERE organization_id=p_org AND id=p_job;
 DELETE FROM emailmonitor.lifecycle_purge_context WHERE transaction_id=txid_current() AND organization_id=p_org AND job_id=p_job;
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 DELETE FROM emailmonitor.admission_requests WHERE organization_id=p_org AND job_id=p_job;
 UPDATE emailmonitor.resolution_accounts SET state='released' WHERE organization_id=p_org AND job_id=p_job AND state='reserved';
 SELECT count(*)::integer INTO released FROM emailmonitor.usage_reservations WHERE organization_id=p_org AND job_id=p_job AND state='reserved';
 UPDATE emailmonitor.usage_reservations SET state='released' WHERE organization_id=p_org AND job_id=p_job AND state='reserved';
 IF released>0 THEN UPDATE emailmonitor.fixture_quota SET reserved=reserved-released WHERE organization_id=p_org; END IF;
END $$;
CREATE FUNCTION emailmonitor.lifecycle_stage(p_org uuid,p_id uuid,p_job uuid,p_reason text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE previous uuid; item record;
BEGIN
 PERFORM emailmonitor.lifecycle_scope(p_org);
 IF p_id IS NULL OR p_reason IS NULL OR p_reason NOT IN ('privacy_request','retention_expired','owner_request') THEN
 RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 SELECT id INTO previous FROM emailmonitor.deletion_tombstones WHERE organization_id=p_org AND job_id IS NOT DISTINCT FROM p_job;
 IF previous IS NOT NULL THEN RETURN emailmonitor.lifecycle_receipt(p_org,previous); END IF;
 IF p_job IS NOT NULL AND NOT EXISTS(SELECT 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job) THEN
 RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 INSERT INTO emailmonitor.deletion_tombstones(organization_id,id,job_id,reason) VALUES(p_org,p_id,p_job,p_reason);
 PERFORM emailmonitor.lifecycle_invalidate_exports(p_org);
 -- An org marker fences every current/future job immediately; physical work is bounded in purge.
 IF p_job IS NOT NULL THEN PERFORM emailmonitor.lifecycle_fence_job(p_org,p_job); END IF;
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,p_id,emailmonitor.job_actor(),'lifecycle.fenced',COALESCE(p_job,p_org));
 RETURN emailmonitor.lifecycle_receipt(p_org,p_id);
END $$;
CREATE FUNCTION emailmonitor.lifecycle_purge_job(p_org uuid,p_job uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE batch record; t text;
BEGIN
 -- Retain minimal durable accounting/root UUIDs; remove content and content-bearing snapshots.
 -- Clear foreign references from inherited continuations only after fencing their jobs.
 FOR batch IN SELECT DISTINCT job_id FROM emailmonitor.execution_items WHERE organization_id=p_org
 AND batch_id IN (SELECT id FROM emailmonitor.association_batches WHERE organization_id=p_org AND job_id=p_job)
 AND job_id<>p_job ORDER BY job_id LOOP
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.deletion_tombstones WHERE organization_id=p_org AND job_id=batch.job_id) THEN
 INSERT INTO emailmonitor.deletion_tombstones(organization_id,id,job_id,reason) VALUES(p_org,gen_random_uuid(),batch.job_id,'privacy_request');
 PERFORM emailmonitor.lifecycle_fence_job(p_org,batch.job_id); END IF;
 END LOOP;
 DELETE FROM emailmonitor.export_requests WHERE organization_id=p_org;
 DELETE FROM emailmonitor.export_members WHERE organization_id=p_org;
 DELETE FROM emailmonitor.export_outcomes WHERE organization_id=p_org;
 UPDATE emailmonitor.exports SET request='{}',snapshot='{}' WHERE organization_id=p_org;
 FOR batch IN SELECT id FROM emailmonitor.association_batches WHERE organization_id=p_org AND job_id=p_job ORDER BY id LOOP
 DELETE FROM emailmonitor.execution_events WHERE organization_id=p_org AND batch_id=batch.id;
 DELETE FROM emailmonitor.execution_effects WHERE organization_id=p_org AND batch_id=batch.id;
 UPDATE emailmonitor.execution_items SET batch_id=NULL WHERE organization_id=p_org AND batch_id=batch.id;
 FOREACH t IN ARRAY ARRAY['association_review_evidence','association_outbox','association_reviews','association_evidence_links',
 'association_candidate_evidence','association_author_evidence','association_raw_variants','association_affiliations',
 'author_email_associations','association_candidates','association_authors','association_evidence'] LOOP
 EXECUTE format('DELETE FROM emailmonitor.%I WHERE organization_id=$1 AND batch_id=$2',t) USING p_org,batch.id;
 END LOOP;
 DELETE FROM emailmonitor.association_batches WHERE organization_id=p_org AND id=batch.id;
 END LOOP;
 UPDATE emailmonitor.execution_runs SET selected_urls=NULL WHERE organization_id=p_org AND job_id=p_job;
 DELETE FROM emailmonitor.source_resource_requests WHERE organization_id=p_org AND job_id=p_job;
 DELETE FROM emailmonitor.article_observations WHERE organization_id=p_org AND job_id=p_job;
 DELETE FROM emailmonitor.discovery_outbox WHERE organization_id=p_org AND job_id=p_job;
 DELETE FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job;
 -- Probe-only content may be retained in legacy result JSON; erase result rows and their operational FKs together.
 DELETE FROM emailmonitor.job_outbox WHERE organization_id=p_org AND job_id=p_job;
 DELETE FROM emailmonitor.usage_events WHERE organization_id=p_org AND job_id=p_job;
 DELETE FROM emailmonitor.usage_reservations WHERE organization_id=p_org AND job_id=p_job;
 DELETE FROM emailmonitor.job_items WHERE organization_id=p_org AND job_id=p_job;
 DELETE FROM emailmonitor.job_idempotency WHERE organization_id=p_org AND job_id=p_job;
END $$;
CREATE FUNCTION emailmonitor.lifecycle_purge(p_org uuid,p_id uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE marker emailmonitor.deletion_tombstones; item record; remain boolean;
BEGIN
 PERFORM emailmonitor.lifecycle_scope(p_org);
 SELECT * INTO marker FROM emailmonitor.deletion_tombstones WHERE organization_id=p_org AND id=p_id FOR UPDATE;
 IF marker.id IS NULL THEN RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 IF marker.stage='purged' THEN RETURN emailmonitor.lifecycle_receipt(p_org,p_id); END IF;
 IF marker.job_id IS NOT NULL THEN
 PERFORM emailmonitor.lifecycle_purge_job(p_org,marker.job_id);
 ELSE
 -- A fixed bounded batch; tombstones preserve immediate refusal between calls.
 FOR item IN SELECT j.id FROM emailmonitor.jobs j WHERE j.organization_id=p_org AND NOT EXISTS(
 SELECT 1 FROM emailmonitor.deletion_tombstones d WHERE d.organization_id=p_org AND d.job_id=j.id AND d.stage='purged')
 ORDER BY j.id LIMIT 10 LOOP
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.deletion_tombstones WHERE organization_id=p_org AND job_id=item.id) THEN
 INSERT INTO emailmonitor.deletion_tombstones(organization_id,id,job_id,reason) VALUES(p_org,gen_random_uuid(),item.id,marker.reason);
 PERFORM emailmonitor.lifecycle_fence_job(p_org,item.id); END IF;
 PERFORM emailmonitor.lifecycle_purge_job(p_org,item.id);
 UPDATE emailmonitor.deletion_tombstones SET stage='purged',purged_at=clock_timestamp() WHERE organization_id=p_org AND job_id=item.id;
 END LOOP;
 IF EXISTS(SELECT 1 FROM emailmonitor.jobs j WHERE j.organization_id=p_org AND NOT EXISTS(
 SELECT 1 FROM emailmonitor.deletion_tombstones d WHERE d.organization_id=p_org AND d.job_id=j.id AND d.stage='purged')) THEN
 RETURN emailmonitor.lifecycle_receipt(p_org,p_id); END IF;
 END IF;
 UPDATE emailmonitor.deletion_tombstones SET stage='purged',purged_at=clock_timestamp() WHERE organization_id=p_org AND id=p_id;
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,gen_random_uuid(),emailmonitor.job_actor(),'lifecycle.purged',COALESCE(marker.job_id,p_org));
 RETURN emailmonitor.lifecycle_receipt(p_org,p_id);
END $$;
CREATE FUNCTION emailmonitor.lifecycle_suppression_document(p_org uuid,p_id uuid) RETURNS jsonb
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT jsonb_build_object('organization_id',organization_id,'id',id,'kind',kind,'reason',reason,'active',active,
 'created_at',created_at,'withdrawn_at',withdrawn_at) FROM emailmonitor.privacy_suppressions WHERE organization_id=p_org AND id=p_id
$$;
CREATE FUNCTION emailmonitor.lifecycle_suppress(p_org uuid,p_id uuid,p_kind text,p_value text,p_reason text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE found_id uuid; item record;
BEGIN
 PERFORM emailmonitor.lifecycle_scope(p_org,true);
 IF p_id IS NULL OR p_kind IS NULL OR p_reason IS NULL OR p_reason NOT IN ('privacy_request','source_restriction')
 OR NOT emailmonitor.privacy_canonical_allowed(p_kind,p_value)
 THEN RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 SELECT id INTO found_id FROM emailmonitor.privacy_suppressions WHERE organization_id=p_org AND kind=p_kind
 AND digest=emailmonitor.privacy_digest(p_org,p_kind,p_value);
 IF found_id IS NULL THEN
 found_id=p_id;INSERT INTO emailmonitor.privacy_suppressions(organization_id,id,kind,digest,reason)
 VALUES(p_org,p_id,p_kind,emailmonitor.privacy_digest(p_org,p_kind,p_value),p_reason);
 ELSE UPDATE emailmonitor.privacy_suppressions SET active=true,withdrawn_at=NULL WHERE organization_id=p_org AND id=found_id; END IF;
 IF (SELECT count(*) FROM emailmonitor.jobs WHERE organization_id=p_org)>1000 THEN RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 PERFORM emailmonitor.lifecycle_invalidate_exports(p_org);
 -- Existing matching content is permanently fenced; withdrawal permits only fresh authorized observations.
 FOR item IN SELECT j.id FROM emailmonitor.jobs j WHERE j.organization_id=p_org AND
 (p_kind='source' OR EXISTS(SELECT 1 FROM emailmonitor.article_observations a WHERE a.organization_id=p_org AND a.job_id=j.id
 AND NOT emailmonitor.privacy_payload_allowed(p_org,a.observation))) ORDER BY j.id LOOP
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.deletion_tombstones WHERE organization_id=p_org AND job_id=item.id) THEN
 INSERT INTO emailmonitor.deletion_tombstones(organization_id,id,job_id,reason) VALUES(p_org,gen_random_uuid(),item.id,'privacy_request');
 PERFORM emailmonitor.lifecycle_fence_job(p_org,item.id); END IF;
 END LOOP;
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,gen_random_uuid(),emailmonitor.job_actor(),'privacy.suppressed',found_id);
 RETURN emailmonitor.lifecycle_suppression_document(p_org,found_id);
END $$;
CREATE FUNCTION emailmonitor.lifecycle_withdraw(p_org uuid,p_id uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 PERFORM emailmonitor.lifecycle_scope(p_org,true);
 UPDATE emailmonitor.privacy_suppressions SET active=false,withdrawn_at=clock_timestamp() WHERE organization_id=p_org AND id=p_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,gen_random_uuid(),emailmonitor.job_actor(),'privacy.withdrawn',p_id);
 RETURN emailmonitor.lifecycle_suppression_document(p_org,p_id);
END $$;
CREATE FUNCTION emailmonitor.lifecycle_retention(p_org uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 PERFORM emailmonitor.lifecycle_scope(p_org);
 RETURN (SELECT jsonb_build_object('organization_id',organization_id,'revision',revision,'retention',retention,'next_due_at',next_due_at)
 FROM emailmonitor.lifecycle_configuration WHERE organization_id=p_org);
END $$;
CREATE FUNCTION emailmonitor.lifecycle_retention_update(p_org uuid,p_revision bigint,p_retention jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE key text; maximum integer;
BEGIN
 PERFORM emailmonitor.lifecycle_scope(p_org);
 IF p_revision IS NULL OR NOT EXISTS(SELECT 1 FROM emailmonitor.lifecycle_configuration WHERE organization_id=p_org AND revision=p_revision)
 THEN RAISE EXCEPTION 'LIFECYCLE_REVISION_CONFLICT' USING ERRCODE='EM014'; END IF;
 IF p_retention IS NULL OR jsonb_typeof(p_retention)<>'object'
 OR NOT p_retention ?& ARRAY['raw_hours','excerpt_days','contact_days','export_hours','audit_days','idempotency_hours']
 OR p_retention-'raw_hours'-'excerpt_days'-'contact_days'-'export_hours'-'audit_days'-'idempotency_hours'<>'{}' THEN
 RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 FOREACH key IN ARRAY ARRAY['raw_hours','excerpt_days','contact_days','export_hours','audit_days','idempotency_hours'] LOOP
 maximum=CASE key WHEN 'raw_hours' THEN 24 WHEN 'excerpt_days' THEN 30 WHEN 'contact_days' THEN 90
 WHEN 'export_hours' THEN 24 WHEN 'audit_days' THEN 365 ELSE 24 END;
 IF jsonb_typeof(p_retention->key)<>'number' OR p_retention->>key !~ '^[0-9]+$'
 OR (p_retention->>key)::integer>maximum OR (key IN ('audit_days','idempotency_hours') AND (p_retention->>key)::integer<1) THEN
 RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 END LOOP;
 UPDATE emailmonitor.lifecycle_configuration SET revision=revision+1,retention=p_retention,next_due_at=clock_timestamp() WHERE organization_id=p_org;
 -- Existing object ceilings only tighten; later changes cannot unexpire retained content.
 UPDATE emailmonitor.lifecycle_job_deadlines d SET contact_deadline=LEAST(d.contact_deadline,j.created_at+make_interval(days=>(p_retention->>'contact_days')::integer)),
 excerpt_deadline=LEAST(d.excerpt_deadline,j.created_at+make_interval(days=>(p_retention->>'excerpt_days')::integer))
 FROM emailmonitor.jobs j WHERE d.organization_id=p_org AND j.organization_id=d.organization_id AND j.id=d.job_id;

 PERFORM emailmonitor.lifecycle_invalidate_exports(p_org);
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,gen_random_uuid(),emailmonitor.job_actor(),'retention.updated',p_org);
 RETURN emailmonitor.lifecycle_retention(p_org);
END $$;
CREATE FUNCTION emailmonitor.lifecycle_tick(p_org uuid) RETURNS integer
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE item record; deleted integer:=0; marker uuid;
BEGIN
 PERFORM emailmonitor.lifecycle_scope(p_org);
 FOR item IN SELECT id FROM emailmonitor.jobs WHERE organization_id=p_org AND NOT emailmonitor.privacy_job_allowed(p_org,id) AND NOT EXISTS(SELECT 1 FROM emailmonitor.deletion_tombstones d WHERE d.organization_id=p_org AND d.job_id=jobs.id AND d.stage='purged')
 ORDER BY id LIMIT 10 LOOP
 marker=(emailmonitor.lifecycle_stage(p_org,gen_random_uuid(),item.id,'retention_expired')->>'id')::uuid;
 PERFORM emailmonitor.lifecycle_purge(p_org,marker);deleted=deleted+1;
 END LOOP;
 -- Capture each invalid artifact identifier before changing its snapshot membership.
 FOR item IN SELECT e.id FROM emailmonitor.exports e WHERE e.organization_id=p_org AND NOT emailmonitor.export_valid(p_org,e.id)
 AND (e.snapshot<>'{}'::jsonb OR e.request<>'{}'::jsonb OR EXISTS(SELECT 1 FROM emailmonitor.export_artifacts a WHERE a.organization_id=p_org AND a.export_id=e.id))
 ORDER BY e.id LIMIT 10 LOOP
 DELETE FROM emailmonitor.export_artifacts WHERE organization_id=p_org AND export_id=item.id;
 DELETE FROM emailmonitor.export_members WHERE organization_id=p_org AND export_id=item.id;
 DELETE FROM emailmonitor.export_outcomes WHERE organization_id=p_org AND export_id=item.id;
 DELETE FROM emailmonitor.export_requests WHERE organization_id=p_org AND export_id=item.id;
 UPDATE emailmonitor.exports SET snapshot='{}',request='{}',state=CASE WHEN state IN ('revoked','failed','expired') THEN state ELSE 'expired' END,
 reason='expired',generation=generation+1,revision=revision+1,lease_nonce=NULL,lease_until=NULL WHERE organization_id=p_org AND id=item.id;
 END LOOP;
 DELETE FROM emailmonitor.audit_events a USING emailmonitor.lifecycle_configuration c WHERE a.organization_id=p_org AND c.organization_id=p_org
 AND a.occurred_at+make_interval(days=>(c.retention->>'audit_days')::integer)<=clock_timestamp();
 DELETE FROM emailmonitor.job_idempotency i USING emailmonitor.lifecycle_configuration c WHERE i.organization_id=p_org AND c.organization_id=p_org
 AND (i.expires_at<=clock_timestamp() OR EXISTS(SELECT 1 FROM emailmonitor.jobs j WHERE j.organization_id=i.organization_id AND j.id=i.job_id AND j.created_at+make_interval(hours=>(c.retention->>'idempotency_hours')::integer)<=clock_timestamp()));
 UPDATE emailmonitor.lifecycle_configuration SET next_due_at=clock_timestamp()+interval '1 hour' WHERE organization_id=p_org;
 RETURN deleted;
END $$;
CREATE FUNCTION emailmonitor.lifecycle_support_document(p_org uuid,p_id uuid) RETURNS jsonb
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT jsonb_build_object('organization_id',organization_id,'id',id,'grantee_id',grantee_id,'job_id',job_id,
 'reason',reason,'expires_at',expires_at,'revoked_at',revoked_at) FROM emailmonitor.support_contexts WHERE organization_id=p_org AND id=p_id
$$;
CREATE FUNCTION emailmonitor.lifecycle_support_create(p_org uuid,p_id uuid,p_grantee uuid,p_job uuid,p_minutes integer,p_reason text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE stamp timestamptz;
BEGIN
 PERFORM emailmonitor.lifecycle_scope(p_org);
 PERFORM 1 FROM emailmonitor.identities WHERE id IN (emailmonitor.job_actor(),p_grantee) ORDER BY id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.memberships WHERE organization_id=p_org AND identity_id=p_grantee FOR SHARE NOWAIT;
 IF p_id IS NULL OR p_minutes IS NULL OR p_minutes NOT BETWEEN 1 AND 240 OR p_reason IS NULL
 OR p_reason NOT IN ('synthetic_incident','synthetic_privacy_check') OR NOT emailmonitor.privacy_job_allowed(p_org,p_job)
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job)
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.memberships m JOIN emailmonitor.identities i ON i.id=m.identity_id
 WHERE m.organization_id=p_org AND m.identity_id=p_grantee AND m.status='active' AND i.active)
 THEN RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 stamp=clock_timestamp();
 INSERT INTO emailmonitor.support_contexts(organization_id,id,grantee_id,job_id,approved_by,reason,created_at,expires_at)
 VALUES(p_org,p_id,p_grantee,p_job,emailmonitor.job_actor(),p_reason,stamp,stamp+make_interval(mins=>p_minutes));
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,gen_random_uuid(),emailmonitor.job_actor(),'support.context_approved',p_id);
 RETURN emailmonitor.lifecycle_support_document(p_org,p_id);
EXCEPTION WHEN lock_not_available THEN
 RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014';
END $$;
CREATE FUNCTION emailmonitor.lifecycle_support_revoke(p_org uuid,p_id uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 PERFORM emailmonitor.lifecycle_scope(p_org);
 UPDATE emailmonitor.support_contexts SET revoked_at=clock_timestamp() WHERE organization_id=p_org AND id=p_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,gen_random_uuid(),emailmonitor.job_actor(),'support.context_revoked',p_id);
 RETURN emailmonitor.lifecycle_support_document(p_org,p_id);
END $$;
CREATE FUNCTION emailmonitor.lifecycle_support_inspect(p_org uuid,p_id uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE ctx emailmonitor.support_contexts; j emailmonitor.jobs; count bigint;
BEGIN
 PERFORM emailmonitor.results_fence(p_org,false,NULL,true);
 SELECT * INTO ctx FROM emailmonitor.support_contexts WHERE organization_id=p_org AND id=p_id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.identities WHERE id IN (emailmonitor.job_actor(),ctx.approved_by) ORDER BY id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.memberships WHERE organization_id=p_org AND identity_id=ctx.approved_by FOR SHARE NOWAIT;
 IF ctx.id IS NULL OR ctx.grantee_id<>emailmonitor.job_actor() OR ctx.revoked_at IS NOT NULL OR ctx.expires_at<=clock_timestamp()
 OR NOT emailmonitor.execution_read_allowed(p_org,ctx.job_id) OR NOT EXISTS(SELECT 1 FROM emailmonitor.memberships m JOIN emailmonitor.identities i ON i.id=m.identity_id
 WHERE m.organization_id=p_org AND m.identity_id=ctx.approved_by AND m.status='active' AND m.role='owner' AND i.active) THEN
 RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=ctx.job_id FOR SHARE NOWAIT;
 SELECT count(*) INTO count FROM emailmonitor.article_observations WHERE organization_id=p_org AND job_id=ctx.job_id;
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,gen_random_uuid(),emailmonitor.job_actor(),'support.context_used',p_id);
 RETURN jsonb_build_object('organization_id',p_org,'context_id',p_id,'job_id',ctx.job_id,'job_state',j.state,
 'generation',j.generation,'retained_observations',count,'content_access',false);
EXCEPTION WHEN lock_not_available THEN
 RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014';
END $$;
CREATE TABLE emailmonitor.lifecycle_ticks (
 organization_id uuid NOT NULL REFERENCES emailmonitor.organizations,id uuid NOT NULL,
 due_at timestamptz NOT NULL,configuration_revision bigint NOT NULL,created_by uuid NOT NULL,
 published_at timestamptz,completed_at timestamptz,deliveries bigint NOT NULL DEFAULT 0 CHECK(deliveries>=0),purged_jobs integer CHECK(purged_jobs BETWEEN 0 AND 10),
 PRIMARY KEY(organization_id,id),UNIQUE(organization_id,due_at),
 FOREIGN KEY(organization_id,created_by) REFERENCES emailmonitor.memberships(organization_id,identity_id)
);
ALTER TABLE emailmonitor.lifecycle_ticks ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.lifecycle_ticks FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.lifecycle_ticks TO emailmonitor_owner USING(true) WITH CHECK(true);
REVOKE ALL ON emailmonitor.lifecycle_ticks FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
CREATE FUNCTION emailmonitor.lifecycle_schedule(p_org uuid,p_id uuid) RETURNS TABLE(id uuid) LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE configuration emailmonitor.lifecycle_configuration;
BEGIN
 PERFORM emailmonitor.lifecycle_scope(p_org);
 SELECT * INTO configuration FROM emailmonitor.lifecycle_configuration WHERE organization_id=p_org FOR UPDATE;
 IF configuration.next_due_at<=clock_timestamp() THEN
 INSERT INTO emailmonitor.lifecycle_ticks(organization_id,id,due_at,configuration_revision,created_by)
 VALUES(p_org,p_id,configuration.next_due_at,configuration.revision,emailmonitor.job_actor()) ON CONFLICT(organization_id,due_at) DO NOTHING;
 END IF;
 -- Repeated publish of uncompleted identifiers recovers confirmed broker loss safely.
 RETURN QUERY SELECT t.id FROM emailmonitor.lifecycle_ticks t WHERE t.organization_id=p_org AND t.completed_at IS NULL ORDER BY t.due_at LIMIT 10;
END $$;
CREATE FUNCTION emailmonitor.lifecycle_scheduled_tick(p_org uuid,p_id uuid) RETURNS integer LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE event emailmonitor.lifecycle_ticks; count integer;
BEGIN
 PERFORM emailmonitor.lifecycle_scope(p_org);
 SELECT * INTO event FROM emailmonitor.lifecycle_ticks WHERE organization_id=p_org AND id=p_id FOR UPDATE;
 IF event.id IS NULL OR event.created_by<>emailmonitor.job_actor() THEN RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 UPDATE emailmonitor.lifecycle_ticks SET deliveries=deliveries+1 WHERE organization_id=p_org AND id=p_id;
 IF event.completed_at IS NOT NULL THEN RETURN event.purged_jobs; END IF;
 count=emailmonitor.lifecycle_tick(p_org);
 UPDATE emailmonitor.lifecycle_ticks SET completed_at=clock_timestamp(),purged_jobs=count WHERE organization_id=p_org AND id=p_id;
 RETURN count;
END $$;
CREATE FUNCTION emailmonitor.lifecycle_confirmed(p_org uuid,p_id uuid) RETURNS void LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 PERFORM emailmonitor.lifecycle_scope(p_org);
 UPDATE emailmonitor.lifecycle_ticks SET published_at=clock_timestamp() WHERE organization_id=p_org AND id=p_id AND created_by=emailmonitor.job_actor();
 IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
END $$;
CREATE OR REPLACE FUNCTION emailmonitor.source_resource_claim(p_org uuid,p_id uuid,p_job uuid,p_version bigint,
 p_operation text,p_path text,p_nonce uuid,p_seconds integer) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE stamp timestamptz:=clock_timestamp(); mine emailmonitor.source_resource_requests;
 bucket emailmonitor.source_resource_buckets; tenant emailmonitor.tenant_source_buckets;
 spacing double precision; chosen uuid; until_time timestamptz; v_pool text; gen bigint:=1; epoch bigint;
BEGIN
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE NOWAIT;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) OR emailmonitor.session_role(p_org) NOT IN ('owner','admin','data_steward','operator')
 OR p_id IS NULL OR p_nonce IS NULL OR p_version IS NULL OR p_version<1 OR p_operation IS NULL
 OR p_operation NOT IN ('fetch_html','browser') OR p_path IS NULL OR length(p_path)>512
 OR p_seconds IS NULL OR p_seconds NOT BETWEEN 1 AND 60
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
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
 OR mine.operation<>p_operation OR mine.path<>p_path OR mine.generation<>gen OR mine.deletion_generation<>epoch OR mine.actor_id<>emailmonitor.job_actor()
 OR mine.session_hash<>current_setting('emailmonitor.session_hash',true) OR mine.state='finished')
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 IF mine.id IS NULL AND ((SELECT count(*) FROM emailmonitor.source_resource_requests WHERE organization_id=p_org)>=500
 OR (SELECT count(*) FROM emailmonitor.source_resource_requests)>=10000) THEN
 RETURN jsonb_build_object('admitted',false,'wait_seconds',1.0); END IF;
 INSERT INTO emailmonitor.source_resource_requests(organization_id,id,job_id,actor_id,session_hash,source_id,generation,deletion_generation,policy_version,operation,path,expires_at,state)
 VALUES(p_org,p_id,p_job,emailmonitor.job_actor(),current_setting('emailmonitor.session_hash',true),
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
CREATE OR REPLACE FUNCTION emailmonitor.source_resource_finish(p_org uuid,p_id uuid,p_nonce uuid,p_outcome text,p_retry_seconds integer) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE mine emailmonitor.source_resource_requests; stamp timestamptz:=clock_timestamp();
BEGIN
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE NOWAIT;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) OR p_outcome IS NULL
 OR p_outcome NOT IN ('response','network_failure','provider_backoff') OR p_retry_seconds IS NULL
 OR p_retry_seconds NOT BETWEEN -1 AND 86400 OR (p_outcome<>'provider_backoff' AND p_retry_seconds<>0)
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 SELECT * INTO mine FROM emailmonitor.source_resource_requests WHERE organization_id=p_org AND id=p_id;
 IF mine.job_id IS NOT NULL THEN PERFORM 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=mine.job_id FOR SHARE NOWAIT; END IF;
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 stamp:=clock_timestamp();
 SELECT * INTO mine FROM emailmonitor.source_resource_requests WHERE organization_id=p_org AND id=p_id;
 IF mine.id IS NULL OR mine.session_hash IS DISTINCT FROM current_setting('emailmonitor.session_hash',true)
 OR mine.actor_id IS DISTINCT FROM emailmonitor.job_actor() OR (mine.state='active' AND mine.nonce IS DISTINCT FROM p_nonce)
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
CREATE OR REPLACE FUNCTION emailmonitor.network_entitlement_allowed(p_org uuid,p_operation text,p_job uuid DEFAULT NULL) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE conf jsonb; saved jsonb;
BEGIN
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE NOWAIT;
 IF NOT FOUND THEN RETURN false; END IF;
 IF p_job IS NOT NULL THEN PERFORM 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR SHARE NOWAIT; IF NOT FOUND THEN RETURN false; END IF; END IF;
 IF NOT emailmonitor.privacy_source_allowed(p_org) OR (p_job IS NOT NULL AND NOT emailmonitor.privacy_job_allowed(p_org,p_job)) THEN RETURN false; END IF;
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) OR emailmonitor.session_role(p_org) NOT IN ('owner','admin','data_steward','operator')
 OR p_operation IS NULL OR p_operation NOT IN ('fetch_html','browser') THEN RETURN false; END IF;
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
CREATE FUNCTION emailmonitor.lifecycle_job_initialize() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE config jsonb;
BEGIN
 SELECT retention INTO config FROM emailmonitor.lifecycle_configuration WHERE organization_id=NEW.organization_id;
 INSERT INTO emailmonitor.lifecycle_job_deadlines VALUES(NEW.organization_id,NEW.id,
 NEW.created_at+make_interval(days=>COALESCE((config->>'contact_days')::integer,90)),
 NEW.created_at+make_interval(days=>COALESCE((config->>'excerpt_days')::integer,30)));
 RETURN NEW;
END $$;
CREATE TRIGGER lifecycle_job_initialize AFTER INSERT ON emailmonitor.jobs FOR EACH ROW EXECUTE FUNCTION emailmonitor.lifecycle_job_initialize();
CREATE FUNCTION emailmonitor.lifecycle_export_initialize() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE hours integer;
BEGIN
 SELECT (retention->>'export_hours')::integer INTO hours FROM emailmonitor.lifecycle_configuration WHERE organization_id=NEW.organization_id;
 IF hours=0 THEN RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 NEW.expires_at=LEAST(NEW.expires_at,NEW.created_at+make_interval(hours=>COALESCE(hours,24)));
 RETURN NEW;
END $$;
CREATE TRIGGER lifecycle_export_initialize BEFORE INSERT ON emailmonitor.exports FOR EACH ROW EXECUTE FUNCTION emailmonitor.lifecycle_export_initialize();
-- Every new helper is private by default; only bounded entry points and policy predicates are granted.
DO $$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='emailmonitor' AND (p.proname LIKE 'lifecycle_%' OR p.proname LIKE 'privacy_%') LOOP
 EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator',f.signature);
 END LOOP;
END $$;
GRANT EXECUTE ON FUNCTION emailmonitor.privacy_job_allowed(uuid,uuid),emailmonitor.privacy_source_allowed(uuid),
 emailmonitor.privacy_payload_allowed(uuid,jsonb),emailmonitor.privacy_excerpt_allowed(uuid,timestamptz,jsonb),emailmonitor.lifecycle_stage(uuid,uuid,uuid,text),emailmonitor.lifecycle_purge(uuid,uuid),
 emailmonitor.lifecycle_suppress(uuid,uuid,text,text,text),emailmonitor.lifecycle_withdraw(uuid,uuid),
 emailmonitor.lifecycle_retention(uuid),emailmonitor.lifecycle_retention_update(uuid,bigint,jsonb),emailmonitor.lifecycle_tick(uuid),
 emailmonitor.lifecycle_support_create(uuid,uuid,uuid,uuid,integer,text),emailmonitor.lifecycle_support_revoke(uuid,uuid),
 emailmonitor.lifecycle_support_inspect(uuid,uuid),emailmonitor.lifecycle_schedule(uuid,uuid),
 emailmonitor.lifecycle_scheduled_tick(uuid,uuid),emailmonitor.lifecycle_confirmed(uuid,uuid) TO emailmonitor_runtime;
RESET ROLE;
