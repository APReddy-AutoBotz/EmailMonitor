-- Synthetic registry only: no live approval, credentials, acquisition or secrets.
SET ROLE emailmonitor_owner;
CREATE TABLE emailmonitor.source_catalog (
 source_id text PRIMARY KEY, manifest_version text NOT NULL, enabled boolean NOT NULL DEFAULT true,
 execution_mode text NOT NULL CHECK(execution_mode='fixture'),
 allowed_hosts text[] NOT NULL, allowed_operations text[] NOT NULL,
 support jsonb NOT NULL
);
INSERT INTO emailmonitor.source_catalog VALUES (
 'synthetic-publisher','1.0.0',true,'fixture',ARRAY['synthetic.publisher.example'],
 ARRAY['search','fetch_html','browser','extract_contacts','retain_excerpt','export_contacts'],
 '{"input_types":["keyword","search_results","article"],"fixture_routes":["/search-page-1.html","/search-page-2.html","/article-a.html","/article-b.html","/tooltip.html","/no-contact.html"],"acquisition_implemented":false,"extraction_implemented":false,"pdf_supported":false,"known_limits":["Synthetic fixtures only","No protected fetch gateway or extractor yet"],"routes_by_operation":{"fetch_html":["/search-page-1.html","/search-page-2.html","/article-a.html","/article-b.html","/tooltip.html","/no-contact.html"],"retain_excerpt":["/search-page-1.html","/search-page-2.html","/article-a.html","/article-b.html","/tooltip.html","/no-contact.html"],"export_contacts":["/search-page-1.html","/search-page-2.html","/article-a.html","/article-b.html","/tooltip.html","/no-contact.html"],"search":["/search-page-1.html","/search-page-2.html"],"browser":["/tooltip.html"],"extract_contacts":["/article-a.html","/article-b.html","/tooltip.html","/no-contact.html"]}}'::jsonb
);
CREATE TABLE emailmonitor.source_policy_heads (
 organization_id uuid NOT NULL REFERENCES emailmonitor.organizations(id),
 source_id text NOT NULL REFERENCES emailmonitor.source_catalog(source_id),
 current_version bigint NOT NULL DEFAULT 0 CHECK(current_version>=0),
 PRIMARY KEY(organization_id,source_id)
);
CREATE TABLE emailmonitor.source_policies (
 organization_id uuid NOT NULL, source_id text NOT NULL, version bigint NOT NULL CHECK(version>0),
 state text NOT NULL CHECK(state IN ('pending_review','approved','suspended','expired','revoked')),
 policy jsonb NOT NULL, created_by uuid NOT NULL,
 reviewed_by uuid, approved_at timestamptz,
 valid_until timestamptz NOT NULL, row_version bigint NOT NULL DEFAULT 1,
 PRIMARY KEY(organization_id,source_id,version),
 FOREIGN KEY(organization_id,source_id) REFERENCES emailmonitor.source_policy_heads,
 FOREIGN KEY(organization_id,created_by) REFERENCES emailmonitor.memberships(organization_id,identity_id),
 FOREIGN KEY(organization_id,reviewed_by) REFERENCES emailmonitor.memberships(organization_id,identity_id),
 CHECK(state<>'approved' OR (reviewed_by IS NOT NULL AND approved_at IS NOT NULL
   AND valid_until>approved_at AND valid_until<=approved_at+interval '366 days'
   AND length(policy->>'permission_reference')>0))
);
CREATE FUNCTION emailmonitor.source_policy_manager(p_org uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.tenant_allowed(p_org) AND emailmonitor.session_role(p_org) IN ('owner','data_steward')
$$;
CREATE FUNCTION emailmonitor.guard_source_policy() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE p jsonb; catalog emailmonitor.source_catalog; keys integer;
BEGIN
 IF TG_OP='UPDATE' THEN
   IF (NEW.organization_id,NEW.source_id,NEW.version,NEW.policy,NEW.created_by,NEW.valid_until)
      IS DISTINCT FROM
      (OLD.organization_id,OLD.source_id,OLD.version,OLD.policy,OLD.created_by,OLD.valid_until) THEN
     RAISE EXCEPTION 'POLICY_VERSION_IMMUTABLE';
   END IF;
   IF NEW.state='approved' AND (NEW.valid_until<=now() OR NEW.approved_at IS NULL) THEN
     RAISE EXCEPTION 'APPROVAL_EXPIRY_REQUIRED'; END IF;
   IF NEW.state=OLD.state OR NOT (
      (OLD.state='pending_review' AND NEW.state IN ('approved','revoked')) OR
      (OLD.state='approved' AND NEW.state IN ('suspended','revoked','expired')) OR
      (OLD.state='suspended' AND NEW.state='revoked')) THEN
     RAISE EXCEPTION 'INVALID_POLICY_TRANSITION';
   END IF;
   NEW.row_version=OLD.row_version+1;
 ELSE
   IF NEW.version<>(SELECT current_version+1 FROM emailmonitor.source_policy_heads
      WHERE organization_id=NEW.organization_id AND source_id=NEW.source_id) THEN
     RAISE EXCEPTION 'CURRENT_VERSION_REQUIRED'; END IF;
   IF NEW.state<>'pending_review' OR NEW.reviewed_by IS NOT NULL OR NEW.approved_at IS NOT NULL
      OR NEW.row_version<>1 THEN RAISE EXCEPTION 'REVIEW_REQUIRED'; END IF;
 END IF;
 SELECT * INTO catalog FROM emailmonitor.source_catalog WHERE source_id=NEW.source_id;
 p=NEW.policy;
 IF NEW.state='approved' AND p->>'permission_reference' IS NULL THEN
   RAISE EXCEPTION 'APPROVAL_PERMISSION_REQUIRED'; END IF;
 SELECT count(*) INTO keys FROM jsonb_object_keys(p);
 IF COALESCE(catalog.source_id IS NULL OR keys<>12 OR NOT p ?& ARRAY[
   'execution_mode','purpose','allowed_hosts','allowed_operations','permission_reference',
   'credential_reference','allowed_regions','robots_handling','limits','retention',
   'export_contacts_allowed','valid_until'] OR
   p->>'execution_mode'<>'fixture' OR p->>'purpose'<>'academic_contact_research' OR
   p->'allowed_hosts'<>'["synthetic.publisher.example"]'::jsonb OR
   p->'allowed_regions'<>'["test-only"]'::jsonb OR
   p->>'robots_handling'<>'fixture_no_network' OR p->'credential_reference'<>'null'::jsonb OR
   jsonb_typeof(p->'allowed_operations')<>'array' OR
   jsonb_array_length(p->'allowed_operations') NOT BETWEEN 1 AND 6 OR
   EXISTS(SELECT 1 FROM jsonb_array_elements_text(p->'allowed_operations') AS op
     WHERE NOT op=ANY(catalog.allowed_operations)) OR
   (SELECT count(*) FROM jsonb_array_elements_text(p->'allowed_operations'))<>
   (SELECT count(DISTINCT op) FROM jsonb_array_elements_text(p->'allowed_operations') AS op) OR
   p->'export_contacts_allowed' NOT IN ('true'::jsonb,'false'::jsonb) OR
   (p->>'export_contacts_allowed')::boolean<>(p->'allowed_operations' ? 'export_contacts') OR
   jsonb_typeof(p->'limits')<>'object' OR
   (SELECT count(*) FROM jsonb_object_keys(p->'limits'))<>3 OR
   NOT p->'limits' ?& ARRAY['max_concurrent_requests','min_request_interval_seconds','max_articles_per_job'] OR
   jsonb_typeof(p->'retention')<>'object' OR
   (SELECT count(*) FROM jsonb_object_keys(p->'retention'))<>3 OR
   NOT p->'retention' ?& ARRAY['raw_hours','excerpt_days','contact_days'] OR
   (p->'limits'->>'max_concurrent_requests')::numeric<>1 OR
   (p->'limits'->>'min_request_interval_seconds')::numeric NOT BETWEEN 5 AND 86400 OR
   (p->'limits'->>'max_articles_per_job')::numeric NOT BETWEEN 1 AND 500 OR
   (p->'retention'->>'raw_hours')::numeric NOT BETWEEN 0 AND 24 OR
   (p->'retention'->>'excerpt_days')::numeric NOT BETWEEN 0 AND 30 OR
   (p->'retention'->>'contact_days')::numeric NOT BETWEEN 0 AND 90 OR
   ((p->'retention'->>'excerpt_days')::numeric>0 AND NOT p->'allowed_operations' ? 'retain_excerpt') OR
   (p->>'permission_reference' IS NOT NULL AND
    NOT p->>'permission_reference' ~ '^[a-zA-Z0-9_-]{1,100}$') OR
   EXISTS(SELECT 1 FROM jsonb_each(p->'limits') e WHERE jsonb_typeof(e.value)<>'number') OR
   EXISTS(SELECT 1 FROM jsonb_each(p->'retention') e WHERE jsonb_typeof(e.value)<>'number'
     OR e.value::text !~ '^[0-9]+$') OR
   (p->'limits'->>'max_articles_per_job') !~ '^[0-9]+$' OR
   (p->>'valid_until')::timestamptz<>NEW.valid_until,true) THEN
   RAISE EXCEPTION 'PLATFORM_POLICY_CEILING';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER source_policy_guard BEFORE INSERT OR UPDATE ON emailmonitor.source_policies
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_source_policy();
CREATE FUNCTION emailmonitor.guard_source_policy_head() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF TG_OP='INSERT' AND NEW.current_version<>0 THEN RAISE EXCEPTION 'INITIAL_HEAD_REQUIRED'; END IF;
 IF TG_OP='UPDATE' AND ((NEW.organization_id,NEW.source_id) IS DISTINCT FROM
    (OLD.organization_id,OLD.source_id) OR NEW.current_version<>OLD.current_version+1 OR
    NOT EXISTS(SELECT 1 FROM emailmonitor.source_policies WHERE
      organization_id=NEW.organization_id AND source_id=NEW.source_id AND version=NEW.current_version))
    THEN RAISE EXCEPTION 'MONOTONIC_HEAD_REQUIRED'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER source_head_guard BEFORE INSERT OR UPDATE ON emailmonitor.source_policy_heads
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_source_policy_head();
ALTER TABLE emailmonitor.source_policy_heads ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.source_policy_heads FORCE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.source_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.source_policies FORCE ROW LEVEL SECURITY;
CREATE POLICY head_owner ON emailmonitor.source_policy_heads TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY policy_owner ON emailmonitor.source_policies TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY head_read ON emailmonitor.source_policy_heads FOR SELECT TO emailmonitor_runtime
 USING(emailmonitor.tenant_allowed(organization_id));
CREATE POLICY head_insert ON emailmonitor.source_policy_heads FOR INSERT TO emailmonitor_runtime
 WITH CHECK(emailmonitor.source_policy_manager(organization_id));
CREATE POLICY head_update ON emailmonitor.source_policy_heads FOR UPDATE TO emailmonitor_runtime
 USING(emailmonitor.source_policy_manager(organization_id))
 WITH CHECK(emailmonitor.source_policy_manager(organization_id));
CREATE POLICY policy_read ON emailmonitor.source_policies FOR SELECT TO emailmonitor_runtime
 USING(emailmonitor.tenant_allowed(organization_id));
CREATE POLICY policy_insert ON emailmonitor.source_policies FOR INSERT TO emailmonitor_runtime
 WITH CHECK(emailmonitor.source_policy_manager(organization_id));
CREATE POLICY policy_update ON emailmonitor.source_policies FOR UPDATE TO emailmonitor_runtime
 USING(emailmonitor.source_policy_manager(organization_id))
 WITH CHECK(emailmonitor.source_policy_manager(organization_id));
REVOKE ALL ON emailmonitor.source_catalog,emailmonitor.source_policy_heads,emailmonitor.source_policies
 FROM PUBLIC,emailmonitor_authenticator;
REVOKE ALL ON FUNCTION emailmonitor.source_policy_manager(uuid),emailmonitor.guard_source_policy(),emailmonitor.guard_source_policy_head()
 FROM PUBLIC,emailmonitor_authenticator;
GRANT SELECT ON emailmonitor.source_catalog TO emailmonitor_runtime;
GRANT SELECT,INSERT,UPDATE ON emailmonitor.source_policy_heads,emailmonitor.source_policies
 TO emailmonitor_runtime;
GRANT EXECUTE ON FUNCTION emailmonitor.source_policy_manager(uuid) TO emailmonitor_runtime;
RESET ROLE;
