-- Cache an executable plan, never an authority decision or a clock value.
-- The original SELECT is byte-preserved inside a VOLATILE procedural wrapper.
-- Existing function OIDs, owners and ACLs survive CREATE OR REPLACE.
SET ROLE emailmonitor_owner;

CREATE OR REPLACE FUNCTION emailmonitor.service_delegation_current(p_org uuid,p_id uuid)
 RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 RETURN (
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
);
END;
$$;

CREATE OR REPLACE FUNCTION emailmonitor.service_schema_ready() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT (SELECT count(*)=1 AND min(version_num)='0015_service_plan_cache' FROM public.alembic_version)
$$;

RESET ROLE;
