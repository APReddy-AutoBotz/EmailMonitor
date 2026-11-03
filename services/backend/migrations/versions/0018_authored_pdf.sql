-- Explicit opt-in for authored local bytes only. No external fetch or role/ACL changes.

SET ROLE emailmonitor_owner;

UPDATE emailmonitor.source_catalog SET allowed_operations=array_append(allowed_operations,'parse_fixture_pdf'), support=jsonb_set(jsonb_set(support,'{authored_pdf_digests}','{"https://synthetic.publisher.example/ambiguous.pdf": "7ff5d5fe802aa77b1ce845f9ebb2fcfbe98e556f96836716045e949ee7645306", "https://synthetic.publisher.example/article-a.pdf": "a216f8bde348256ee912f592956dfc66ea83b106e2f4c05b3c6a28f5e6cfd9cc", "https://synthetic.publisher.example/article-b.pdf": "e24a7228b39e04c6f56203317ef90300c6a8b622b16f3672c8cc83784d0d0b8a", "https://synthetic.publisher.example/corrupt.pdf": "bfdd8c6384be76b5ab1ed6f2aa9a2a3fdcb49c8f62ffda3bdcb85091bc14b111", "https://synthetic.publisher.example/encrypted.pdf": "4e253514d7bb1007937cc7456821c9b5393a275e748658847208590029e4b18e", "https://synthetic.publisher.example/no-contact.pdf": "3db38695a632f805b3b56571f12c133bbd80c56d4cddcbc812a025876e8e1d59", "https://synthetic.publisher.example/page-cap.pdf": "8e64ad429519fe6f45c17902e032e57f4d0568f3809475bb350f6f532878cb59", "https://synthetic.publisher.example/scanned.pdf": "a1c762aad46bd8f0eda32a51dee4d8026ac7800c38b4e1f04578d5d9ee98d089", "https://synthetic.publisher.example/wrapped.pdf": "ee5449815873cca0eca7e919b340d0598b1863f4bf439a9b4eef14fae6b893fb"}'::jsonb),'{pdf_fixture_opt_in}','true'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';

UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,'{routes_by_operation,parse_fixture_pdf}',COALESCE(support#>'{routes_by_operation,parse_fixture_pdf}','[]'::jsonb)||'["/ambiguous.pdf", "/article-a.pdf", "/article-b.pdf", "/corrupt.pdf", "/encrypted.pdf", "/no-contact.pdf", "/page-cap.pdf", "/scanned.pdf", "/wrapped.pdf"]'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';

UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,'{routes_by_operation,extract_contacts}',COALESCE(support#>'{routes_by_operation,extract_contacts}','[]'::jsonb)||'["/ambiguous.pdf", "/article-a.pdf", "/article-b.pdf", "/corrupt.pdf", "/encrypted.pdf", "/no-contact.pdf", "/page-cap.pdf", "/scanned.pdf", "/wrapped.pdf"]'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';

UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,'{routes_by_operation,retain_excerpt}',COALESCE(support#>'{routes_by_operation,retain_excerpt}','[]'::jsonb)||'["/ambiguous.pdf", "/article-a.pdf", "/article-b.pdf", "/corrupt.pdf", "/encrypted.pdf", "/no-contact.pdf", "/page-cap.pdf", "/scanned.pdf", "/wrapped.pdf"]'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';

UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,'{routes_by_operation,export_contacts}',COALESCE(support#>'{routes_by_operation,export_contacts}','[]'::jsonb)||'["/ambiguous.pdf", "/article-a.pdf", "/article-b.pdf", "/corrupt.pdf", "/encrypted.pdf", "/no-contact.pdf", "/page-cap.pdf", "/scanned.pdf", "/wrapped.pdf"]'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';

ALTER TABLE emailmonitor.execution_items DROP CONSTRAINT execution_items_reason_check;

ALTER TABLE emailmonitor.execution_items ADD CONSTRAINT execution_items_reason_check CHECK ((reason = ANY (ARRAY['scheduled'::text, 'leased'::text, 'observed'::text, 'no_contact'::text, 'requires_review'::text, 'browser_not_completed'::text, 'source_policy_changed'::text, 'worker_failure'::text, 'lease_exhausted'::text, 'user_cancelled'::text, 'pagination_committed'::text, 'quota_exhausted'::text, 'xml_partial'::text, 'xml_unsupported'::text,'pdf_partial'::text,'pdf_unsupported'::text])));

ALTER TABLE emailmonitor.article_observations DROP CONSTRAINT article_observations_article_url_check;

ALTER TABLE emailmonitor.article_observations ADD CONSTRAINT article_observations_article_url_check CHECK ((article_url = ANY (ARRAY['https://synthetic.publisher.example/article-a.html'::text, 'https://synthetic.publisher.example/article-b.html'::text, 'https://synthetic.publisher.example/tooltip.html'::text, 'https://synthetic.publisher.example/no-contact.html'::text, 'https://synthetic.publisher.example/article-xml.xml'::text, 'https://synthetic.publisher.example/provider-doi.xml'::text, 'https://synthetic.publisher.example/provider-pii.xml'::text ,'https://synthetic.publisher.example/ambiguous.pdf'::text,'https://synthetic.publisher.example/article-a.pdf'::text,'https://synthetic.publisher.example/article-b.pdf'::text,'https://synthetic.publisher.example/corrupt.pdf'::text,'https://synthetic.publisher.example/encrypted.pdf'::text,'https://synthetic.publisher.example/no-contact.pdf'::text,'https://synthetic.publisher.example/page-cap.pdf'::text,'https://synthetic.publisher.example/scanned.pdf'::text,'https://synthetic.publisher.example/wrapped.pdf'::text])));

ALTER TABLE emailmonitor.execution_items DROP CONSTRAINT execution_items_input_url_check;

ALTER TABLE emailmonitor.execution_items ADD CONSTRAINT execution_items_input_url_check CHECK ((input_url = ANY (ARRAY['https://synthetic.publisher.example/search-page-1.html'::text, 'https://synthetic.publisher.example/search-page-2.html'::text, 'https://synthetic.publisher.example/article-a.html'::text, 'https://synthetic.publisher.example/article-b.html'::text, 'https://synthetic.publisher.example/tooltip.html'::text, 'https://synthetic.publisher.example/no-contact.html'::text, 'https://synthetic.publisher.example/article-xml.xml'::text, 'https://synthetic.publisher.example/provider-search-0.json'::text, 'https://synthetic.publisher.example/provider-doi.xml'::text, 'https://synthetic.publisher.example/provider-pii.xml'::text ,'https://synthetic.publisher.example/ambiguous.pdf'::text,'https://synthetic.publisher.example/article-a.pdf'::text,'https://synthetic.publisher.example/article-b.pdf'::text,'https://synthetic.publisher.example/corrupt.pdf'::text,'https://synthetic.publisher.example/encrypted.pdf'::text,'https://synthetic.publisher.example/no-contact.pdf'::text,'https://synthetic.publisher.example/page-cap.pdf'::text,'https://synthetic.publisher.example/scanned.pdf'::text,'https://synthetic.publisher.example/wrapped.pdf'::text])));

CREATE OR REPLACE FUNCTION emailmonitor.guard_source_policy()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
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
   jsonb_array_length(p->'allowed_operations') NOT BETWEEN 1 AND 8 OR
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
END $function$
;

CREATE OR REPLACE FUNCTION emailmonitor.fixture_acquisition_operation(p_url text)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
 SELECT CASE WHEN p_url IN ('https://synthetic.publisher.example/article-xml.xml',
 'https://synthetic.publisher.example/provider-doi.xml','https://synthetic.publisher.example/provider-pii.xml') THEN 'fetch_xml'
 WHEN p_url='https://synthetic.publisher.example/provider-search-0.json' THEN 'search'
 WHEN p_url IN ('https://synthetic.publisher.example/ambiguous.pdf','https://synthetic.publisher.example/article-a.pdf','https://synthetic.publisher.example/article-b.pdf','https://synthetic.publisher.example/corrupt.pdf','https://synthetic.publisher.example/encrypted.pdf','https://synthetic.publisher.example/no-contact.pdf','https://synthetic.publisher.example/page-cap.pdf','https://synthetic.publisher.example/scanned.pdf','https://synthetic.publisher.example/wrapped.pdf') THEN 'parse_fixture_pdf' ELSE 'fetch_html' END
$function$
;

CREATE OR REPLACE FUNCTION emailmonitor.guard_discovery()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE parent emailmonitor.jobs;
BEGIN
 SELECT * INTO parent FROM emailmonitor.jobs WHERE organization_id=NEW.organization_id AND id=NEW.job_id FOR SHARE;
 IF TG_OP='UPDATE' AND NEW.generation<>OLD.generation THEN
 PERFORM emailmonitor.execution_control_fence(NEW.organization_id,NEW.job_id);
 IF parent.state<>'paused' OR NEW.generation<>parent.generation OR NEW.revision<>OLD.revision+1
 OR (to_jsonb(NEW)-'generation'-'revision') IS DISTINCT FROM (to_jsonb(OLD)-'generation'-'revision')
 THEN RAISE EXCEPTION 'DISCOVERY_REBASE_DENIED'; END IF;
 RETURN NEW;
 END IF;
 PERFORM emailmonitor.discovery_source_fence(NEW.organization_id,NEW.job_id,NEW.policy_version);
 SELECT * INTO parent FROM emailmonitor.jobs WHERE organization_id=NEW.organization_id AND id=NEW.job_id FOR SHARE;
 IF parent.state='running' AND NOT EXISTS(SELECT 1 FROM emailmonitor.execution_items i
 WHERE i.organization_id=NEW.organization_id AND i.job_id=NEW.job_id AND i.work_kind='discover'
 AND i.id::text=current_setting('emailmonitor.execution_item',true)
 AND i.input_url=OLD.checkpoint->>'next_url') THEN
 RAISE EXCEPTION 'EXECUTION_WORK_FENCE' USING ERRCODE='EM010'; END IF;
 IF parent.kind<>'extraction' OR NOT COALESCE(emailmonitor.execution_write_allowed(NEW.organization_id,NEW.job_id),false) OR NEW.generation<>parent.generation
 OR NEW.deletion_generation<>(SELECT deletion_generation FROM emailmonitor.organizations WHERE id=NEW.organization_id)
 THEN RAISE EXCEPTION 'DISCOVERY_JOB_FENCE'; END IF;
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.source_policies p
 JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
 JOIN emailmonitor.source_catalog s USING(source_id)
 WHERE p.organization_id=NEW.organization_id AND p.source_id=NEW.source_id
 AND p.version=NEW.policy_version AND p.version=h.current_version AND s.enabled
 AND p.state='approved' AND p.valid_until>clock_timestamp()
 AND p.policy->'allowed_operations' ? emailmonitor.fixture_acquisition_operation(NEW.plan->>'start_url')
 AND (NEW.plan->>'classification'<>'search_results' OR p.policy->'allowed_operations' ? 'search')
 AND NEW.max_articles<=(p.policy->'limits'->>'max_articles_per_job')::integer) THEN RAISE EXCEPTION 'DISCOVERY_POLICY_FENCE' USING ERRCODE='EM006'; END IF;
 IF NEW.plan->>'start_url' IN ('https://synthetic.publisher.example/ambiguous.pdf','https://synthetic.publisher.example/article-a.pdf','https://synthetic.publisher.example/article-b.pdf','https://synthetic.publisher.example/corrupt.pdf','https://synthetic.publisher.example/encrypted.pdf','https://synthetic.publisher.example/no-contact.pdf','https://synthetic.publisher.example/page-cap.pdf','https://synthetic.publisher.example/scanned.pdf','https://synthetic.publisher.example/wrapped.pdf') AND NOT COALESCE((parent.request->'options'->>'allow_pdf')::boolean,true) THEN RAISE EXCEPTION 'PDF_DISABLED' USING ERRCODE='EM006'; END IF;
 IF TG_OP='INSERT' THEN
 IF NEW.revision<>1 THEN RAISE EXCEPTION 'DISCOVERY_INITIAL_REVISION'; END IF;
 ELSE
 IF (NEW.organization_id,NEW.job_id,NEW.generation,NEW.deletion_generation,NEW.source_id,NEW.policy_version,NEW.plan,NEW.max_pages,NEW.max_articles)
 IS DISTINCT FROM (OLD.organization_id,OLD.job_id,OLD.generation,OLD.deletion_generation,OLD.source_id,OLD.policy_version,OLD.plan,OLD.max_pages,OLD.max_articles)
 THEN RAISE EXCEPTION 'DISCOVERY_PLAN_IMMUTABLE'; END IF;
 IF OLD.checkpoint->>'status'<>'pending' OR NEW.revision<>OLD.revision+1 THEN RAISE EXCEPTION 'DISCOVERY_REVISION_FENCE'; END IF;
 END IF;
 RETURN NEW;
END $function$
;

CREATE OR REPLACE FUNCTION emailmonitor.fixture_admission_claim(p_org uuid, p_job uuid, p_url text, p_nonce uuid, p_seconds integer)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE j emailmonitor.jobs; d emailmonitor.discovery; v_pool text; reference uuid; inherited boolean;
BEGIN
 IF NOT emailmonitor.work_execution_allowed(p_org,p_job)
 OR p_url NOT IN ('https://synthetic.publisher.example/search-page-1.html','https://synthetic.publisher.example/search-page-2.html',
 'https://synthetic.publisher.example/article-a.html','https://synthetic.publisher.example/article-b.html',
 'https://synthetic.publisher.example/tooltip.html','https://synthetic.publisher.example/no-contact.html','https://synthetic.publisher.example/article-xml.xml','https://synthetic.publisher.example/provider-search-0.json','https://synthetic.publisher.example/provider-doi.xml','https://synthetic.publisher.example/provider-pii.xml','https://synthetic.publisher.example/ambiguous.pdf','https://synthetic.publisher.example/article-a.pdf','https://synthetic.publisher.example/article-b.pdf','https://synthetic.publisher.example/corrupt.pdf','https://synthetic.publisher.example/encrypted.pdf','https://synthetic.publisher.example/no-contact.pdf','https://synthetic.publisher.example/page-cap.pdf','https://synthetic.publisher.example/scanned.pdf','https://synthetic.publisher.example/wrapped.pdf') THEN
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
END $function$
;

CREATE OR REPLACE FUNCTION emailmonitor.association_visible(p_org uuid, p_batch uuid)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
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
 AND (a.observation->>'route'<>'pdf' OR (p.policy->'allowed_operations' ? 'parse_fixture_pdf' AND 'parse_fixture_pdf'=ANY(s.allowed_operations)))
 AND (a.observation->>'route'<>'article_xml' OR (p.policy->'allowed_operations' ? 'fetch_xml' AND 'fetch_xml'=ANY(s.allowed_operations)))
 AND (a.observation->>'route'<>'browser_dom' OR (p.policy->'allowed_operations' ? 'browser' AND 'browser'=ANY(s.allowed_operations)))
 AND (NOT jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")') OR (
 p.policy->'allowed_operations' ? 'retain_excerpt' AND 'retain_excerpt'=ANY(s.allowed_operations) AND (p.policy->'retention'->>'excerpt_days')::integer>0)));
END $function$
;

CREATE OR REPLACE FUNCTION emailmonitor.publication_batch_state(p_org uuid, p_batch uuid)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
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
 AND (a.observation->>'route'<>'pdf' OR (p.policy->'allowed_operations' ? 'parse_fixture_pdf' AND 'parse_fixture_pdf'=ANY(s.allowed_operations)))
 AND (a.observation->>'route'<>'article_xml' OR (p.policy->'allowed_operations' ? 'fetch_xml' AND 'fetch_xml'=ANY(s.allowed_operations)))
 AND (a.observation->>'route'<>'browser_dom' OR (p.policy->'allowed_operations' ? 'browser' AND 'browser'=ANY(s.allowed_operations)))
 AND (NOT jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")') OR (
 p.policy->'allowed_operations' ? 'retain_excerpt' AND 'retain_excerpt'=ANY(s.allowed_operations) AND (p.policy->'retention'->>'excerpt_days')::integer>0)));
END $function$
;

CREATE OR REPLACE FUNCTION emailmonitor.retained_article_batch_current(p_org uuid, p_batch uuid)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE b emailmonitor.association_batches;
BEGIN
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
 AND (a.observation->>'route'<>'pdf' OR (p.policy->'allowed_operations' ? 'parse_fixture_pdf' AND 'parse_fixture_pdf'=ANY(s.allowed_operations)))
 AND (a.observation->>'route'<>'article_xml' OR (p.policy->'allowed_operations' ? 'fetch_xml' AND 'fetch_xml'=ANY(s.allowed_operations)))
 AND (a.observation->>'route'<>'browser_dom' OR (p.policy->'allowed_operations' ? 'browser' AND 'browser'=ANY(s.allowed_operations)))
 AND (NOT jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")') OR (
 p.policy->'allowed_operations' ? 'retain_excerpt' AND 'retain_excerpt'=ANY(s.allowed_operations) AND (p.policy->'retention'->>'excerpt_days')::integer>0)));
END $function$
;

CREATE OR REPLACE FUNCTION emailmonitor.association_parent_fence(p_org uuid, p_job uuid, p_url text, p_revision bigint, p_write boolean DEFAULT false)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
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
 OR (a.observation->>'route'='pdf' AND (NOT COALESCE(p.policy->'allowed_operations' ? 'parse_fixture_pdf',false) OR NOT COALESCE('parse_fixture_pdf'=ANY(s.allowed_operations),false)))
 OR (a.observation->>'route'='browser_dom' AND (NOT COALESCE(p.policy->'allowed_operations' ? 'browser',false) OR NOT COALESCE('browser'=ANY(s.allowed_operations),false)))
 OR (jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")') AND (
 NOT COALESCE(p.policy->'allowed_operations' ? 'retain_excerpt',false) OR NOT COALESCE('retain_excerpt'=ANY(s.allowed_operations),false) OR COALESCE((p.policy->'retention'->>'excerpt_days')::integer,0)<=0))
 THEN RAISE EXCEPTION 'ASSOCIATION_DENIED' USING ERRCODE='EM009'; END IF;
END $function$
;

CREATE OR REPLACE FUNCTION emailmonitor.retained_article_binding(p_org uuid, p_job uuid, p_item uuid, p_export uuid DEFAULT NULL::uuid, p_fingerprint boolean DEFAULT true)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE i emailmonitor.execution_items; b emailmonitor.association_batches;
 a emailmonitor.article_observations; original emailmonitor.execution_items;
 presence text:='unresolved'; source_binding jsonb:='null'; batch uuid; expiry timestamptz;
 candidate_count bigint; fingerprint text; revision bigint;
BEGIN
 IF p_export IS NULL THEN
 IF NOT COALESCE(emailmonitor.human_work_tenant_allowed(p_org),false)
 OR NOT COALESCE(emailmonitor.execution_read_allowed(p_org,p_job),false) THEN RETURN NULL; END IF;
 ELSE
 -- An export delegation can only recheck identities already captured by that export.
 IF NOT COALESCE(emailmonitor.work_export_allowed(p_org,p_export),false) OR NOT EXISTS(
 SELECT 1 FROM emailmonitor.exports e, jsonb_array_elements(COALESCE(e.snapshot->'article_filter_bindings','[]')) x
 WHERE e.organization_id=p_org AND e.id=p_export AND x->>'job_id'=p_job::text
 AND x->>'item_id'=p_item::text) THEN RETURN NULL; END IF;
 END IF;
 IF NOT COALESCE(emailmonitor.retained_article_job_current(p_org,p_job),false) THEN RETURN NULL; END IF;
 SELECT * INTO i FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=p_job AND id=p_item AND work_kind='article';
 IF i.id IS NULL THEN RETURN NULL; END IF;
 SELECT row_version INTO revision FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 SELECT expires_at INTO expiry FROM emailmonitor.execution_runs WHERE organization_id=p_org AND job_id=p_job;
 SELECT * INTO b FROM emailmonitor.association_batches WHERE organization_id=p_org AND id=i.batch_id;
 IF b.id IS NOT NULL AND b.article_url=i.input_url
 AND COALESCE(emailmonitor.retained_article_batch_current(p_org,b.id),false)
 AND (b.job_id=p_job OR COALESCE(emailmonitor.retained_article_job_current(p_org,b.job_id),false)) THEN
 -- Resolve the source by the batch's original job, never by immediate predecessor URL.
 SELECT * INTO a FROM emailmonitor.article_observations WHERE organization_id=p_org AND job_id=b.job_id AND article_url=b.article_url;
 SELECT * INTO original FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=b.job_id
 AND work_kind='article' AND input_url=b.article_url AND batch_id=b.id;
 SELECT count(*) INTO candidate_count FROM emailmonitor.association_candidates WHERE organization_id=p_org AND batch_id=b.id;
 IF original.id IS NOT NULL AND EXISTS(
 WITH RECURSIVE lineage AS (
 SELECT i.job_id,i.id,i.inherited_job_id,i.inherited_item_id,ARRAY[i.job_id] visited
 UNION ALL SELECT prior.job_id,prior.id,prior.inherited_job_id,prior.inherited_item_id,l.visited||prior.job_id
 FROM lineage l JOIN emailmonitor.execution_items prior ON prior.organization_id=p_org
 AND prior.job_id=l.inherited_job_id AND prior.id=l.inherited_item_id
 WHERE prior.work_kind='article' AND prior.input_url=i.input_url AND prior.batch_id=b.id
 AND NOT prior.job_id=ANY(l.visited) AND cardinality(l.visited)<1000)
 SELECT 1 FROM lineage WHERE job_id=b.job_id AND id=original.id
 AND inherited_job_id IS NULL AND inherited_item_id IS NULL)
 AND a.source_id='synthetic-publisher'
 AND a.observation->>'url'=i.input_url AND a.observation->>'schema_version'='1.0'
 AND b.snapshot->>'organization_id'=p_org::text AND b.snapshot->>'source_url'=i.input_url
 AND b.snapshot->>'content_digest'=a.observation->>'content_digest'
 AND b.snapshot->>'parser_version'=a.observation->>'parser_version'
 AND b.snapshot->>'observation_route'=a.observation->>'route'
 AND b.snapshot->>'observation_status'=a.observation->>'status'
 AND jsonb_typeof(b.snapshot->'candidates')='array'
 AND jsonb_array_length(b.snapshot->'candidates')=candidate_count
 AND (a.observation->>'route' NOT IN ('article_xml','pdf') OR a.observation->'binding'=jsonb_build_object(
 'organization',p_org,'job',b.job_id,'item',original.id,'generation',b.generation,
 'deletion_generation',b.deletion_generation,'policy_version',b.policy_version,'discovery_revision',a.discovery_revision))
 THEN
 batch:=b.id;
 presence:=emailmonitor.retained_observation_presence(a.observation,candidate_count);
 IF p_fingerprint THEN source_binding:=jsonb_build_object('job_id',b.job_id,'batch_id',b.id,'source_revision',a.revision,
 'generation',a.generation,'deletion_generation',a.deletion_generation,'policy_version',a.policy_version,
 'observation',encode(sha256(convert_to(a.observation::text,'UTF8')),'hex')); END IF;
 expiry:=least(expiry,b.expires_at,a.expires_at);
 END IF;
 END IF;
 IF p_fingerprint THEN fingerprint:=encode(sha256(convert_to(jsonb_build_object('job_revision',revision,
 'item',jsonb_build_object('job_id',i.job_id,'item_id',i.id,'url',i.input_url,'batch_id',i.batch_id,
 'inherited_job_id',i.inherited_job_id,'inherited_item_id',i.inherited_item_id,'state',i.state,
 'reason',i.reason,'completed_at',i.completed_at),'source',source_binding,'presence',presence)::text,'UTF8')),'hex'); END IF;
 RETURN jsonb_build_object('job_id',p_job,'item_id',p_item,'fingerprint',fingerprint,
 'presence',presence,'batch_id',batch,'expires_at',expiry);
END $function$
;

CREATE OR REPLACE FUNCTION emailmonitor.retained_observation_presence(p_document jsonb, p_candidates bigint)
 RETURNS text
 LANGUAGE plpgsql
 IMMUTABLE
 SET search_path TO 'pg_catalog'
AS $function$
DECLARE n integer; status text:=p_document->>'status'; route text:=p_document->>'route';
BEGIN
 IF jsonb_typeof(p_document->'candidates') IS DISTINCT FROM 'array'
 OR jsonb_typeof(p_document->'authors') IS DISTINCT FROM 'array' THEN RETURN 'unresolved'; END IF;
 n:=jsonb_array_length(p_document->'candidates');
 IF route='article_xml' THEN
 IF jsonb_typeof(p_document->'reasons') IS DISTINCT FROM 'array' THEN RETURN 'unresolved'; END IF;
 IF NOT COALESCE(p_document->>'parser_version'='elsevier-xml-head-v1'
 AND status IN ('observed','no_contact','partial','unsupported')
 AND (jsonb_array_length(p_document->'reasons')>0)=(status IN ('partial','unsupported')),false)
 THEN RETURN 'unresolved'; END IF;
 ELSIF route='pdf' THEN
 IF NOT COALESCE(p_document->>'parser_version'='pypdf-6.20.1-synthetic-v1'
 AND p_document->>'retention_profile'='authored-pdf-retention-v1'
 AND status IN ('observed','no_contact','partial','unsupported'),false) THEN RETURN 'unresolved'; END IF;
 IF status='no_contact' AND NOT COALESCE(p_document->'complete_scan'='true'::jsonb AND p_document->>'reason'='complete',false) THEN RETURN 'unresolved'; END IF;
 ELSIF NOT COALESCE(route IN ('html','browser_dom')
 AND p_document->>'parser_version'='synthetic-html-v1'
 AND status IN ('observed','no_contact','requires_browser'),false) THEN RETURN 'unresolved'; END IF;
 IF jsonb_array_length(p_document->'authors')=0 THEN RETURN 'unresolved'; END IF;
 -- Raw candidates, never accepted Contacts, syntax checks, or execution state.
 IF n>0 AND p_candidates>0 AND status IN ('observed','partial') THEN RETURN 'observed_candidate'; END IF;
 IF n=0 AND p_candidates=0 AND status='no_contact' THEN RETURN 'completed_without_candidate'; END IF;
 RETURN 'unresolved';
END $function$
;

CREATE OR REPLACE FUNCTION emailmonitor.execution_finish(p_org uuid, p_job uuid, p_item uuid, p_token uuid, p_batch uuid, p_failure text, p_event uuid)
 RETURNS text
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE i emailmonitor.execution_items; r emailmonitor.execution_runs; a emailmonitor.article_observations;
 b emailmonitor.association_batches; d emailmonitor.discovery; target text; why text; effect uuid;
BEGIN
 PERFORM emailmonitor.execution_control_fence(p_org,p_job,false);
 SELECT * INTO i FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=p_job AND id=p_item FOR UPDATE;
 SELECT * INTO r FROM emailmonitor.execution_runs WHERE organization_id=p_org AND job_id=p_job;
 IF i.id IS NULL OR i.state<>'running' OR i.lease_token IS DISTINCT FROM p_token
 OR p_item::text IS DISTINCT FROM current_setting('emailmonitor.execution_item',true)
 OR p_token::text IS DISTINCT FROM current_setting('emailmonitor.execution_token',true)
 OR NOT COALESCE(emailmonitor.execution_write_allowed(p_org,p_job),false)
 THEN RAISE EXCEPTION 'EXECUTION_WORK_FENCE' USING ERRCODE='EM010'; END IF;
 IF p_failure IS NOT NULL THEN
 IF p_batch IS NOT NULL OR p_failure NOT IN ('worker_failure','source_policy_changed')
 THEN RAISE EXCEPTION 'EXECUTION_FAILURE_INPUT'; END IF;
 IF p_failure='source_policy_changed' THEN
 IF COALESCE(emailmonitor.execution_read_allowed(p_org,p_job),false) THEN RAISE EXCEPTION 'POLICY_DENIAL_REQUIRED'; END IF;
 target:='policy_blocked'; why:='source_policy_changed';
 ELSE
 target:=CASE WHEN i.attempts<3 THEN 'retry_wait' ELSE 'failed' END;
 why:=CASE WHEN i.attempts<3 THEN 'worker_failure' ELSE 'lease_exhausted' END;
 END IF;
 ELSE
 IF NOT COALESCE(emailmonitor.execution_read_allowed(p_org,p_job),false) THEN RAISE EXCEPTION 'EXECUTION_SCOPE_DENIED' USING ERRCODE='EM010'; END IF;
 IF i.work_kind='discover' THEN
 SELECT * INTO d FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job;
 IF p_batch IS NOT NULL OR NOT (d.checkpoint->'pages' ? i.input_url) OR d.revision<=i.expected_discovery_revision
 THEN RAISE EXCEPTION 'COMMITTED_PAGE_REQUIRED'; END IF;
 target:='succeeded'; why:='pagination_committed';
 ELSE
 SELECT * INTO a FROM emailmonitor.article_observations WHERE organization_id=p_org AND job_id=p_job AND article_url=i.input_url;
 SELECT * INTO b FROM emailmonitor.association_batches WHERE organization_id=p_org AND id=p_batch;
 IF a.article_url IS NULL OR b.id IS NULL OR b.job_id<>p_job OR b.article_url<>i.input_url
 OR b.source_revision<>a.revision OR NOT COALESCE(emailmonitor.association_visible(p_org,p_batch),false)
 THEN RAISE EXCEPTION 'COMMITTED_ASSOCIATION_REQUIRED'; END IF;
 IF a.observation->>'status'='requires_browser' THEN target:='unsupported'; why:='browser_not_completed';
 ELSIF a.observation->>'status'='unsupported' THEN target:='unsupported'; why:=CASE WHEN a.observation->>'route'='pdf' THEN 'pdf_unsupported' ELSE 'xml_unsupported' END;
 ELSIF a.observation->>'status'='partial' THEN target:='unsupported'; why:=CASE WHEN a.observation->>'route'='pdf' THEN 'pdf_partial' ELSE 'xml_partial' END;
 ELSIF a.observation->>'status'='no_contact' THEN target:='no_contact'; why:='no_contact';
 ELSIF EXISTS(SELECT 1 FROM emailmonitor.author_email_associations x WHERE x.organization_id=p_org AND x.batch_id=p_batch
 AND x.state IN ('unmatched','needs_review')) THEN target:='needs_review'; why:='requires_review';
 ELSE target:='succeeded'; why:='observed'; END IF;
 effect:=md5(p_org::text||':'||r.root_job_id::text||':article:'||i.input_url)::uuid;
 INSERT INTO emailmonitor.execution_effects VALUES(p_org,r.root_job_id,effect,p_job,p_item,p_batch) ON CONFLICT DO NOTHING;
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.execution_effects WHERE organization_id=p_org AND root_job_id=r.root_job_id
 AND effect_id=effect AND job_id=p_job AND item_id=p_item AND batch_id=p_batch)
 THEN RAISE EXCEPTION 'EFFECT_IDENTITY_CONFLICT'; END IF;
 END IF;
 END IF;
 UPDATE emailmonitor.execution_items SET state=target,reason=why,batch_id=p_batch,effect_id=effect,
 lease_token=NULL,lease_until=NULL,lease_generation=NULL,lease_deletion_generation=NULL,
 completed_at=CASE WHEN target='retry_wait' THEN NULL ELSE clock_timestamp() END
 WHERE organization_id=p_org AND job_id=p_job AND id=p_item;
 IF target='retry_wait' THEN
 UPDATE emailmonitor.execution_outbox SET published_at=NULL WHERE organization_id=p_org AND job_id=p_job
 AND item_id=p_item AND generation=i.lease_generation;
 END IF;
 PERFORM emailmonitor.execution_sync(p_org,p_job);
 IF p_failure='source_policy_changed' THEN
 UPDATE emailmonitor.execution_items SET state='policy_blocked',reason='source_policy_changed',
 lease_token=NULL,lease_until=NULL,lease_generation=NULL,lease_deletion_generation=NULL,
 completed_at=clock_timestamp() WHERE organization_id=p_org AND job_id=p_job
 AND state IN ('pending','running','retry_wait');
 END IF;
 PERFORM emailmonitor.execution_emit(p_org,p_job,p_event,CASE WHEN i.work_kind='discover' THEN 'job.discovery_progress' ELSE 'job.item_terminal' END,p_item);
 PERFORM emailmonitor.execution_settle(p_org,p_job,md5(p_event::text||':finished')::uuid);
 RETURN target;
END $function$
;

CREATE OR REPLACE FUNCTION emailmonitor.guard_article_observation()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE d emailmonitor.discovery; j emailmonitor.jobs; source_hash text; p jsonb; days integer; registered jsonb; provider_url text; provider_fingerprint text;
BEGIN
 registered:=emailmonitor.registered_provider_document(NEW.source_id,NEW.article_url);
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

 OR NEW.observation->>'identity_association_implemented' IS DISTINCT FROM 'false'
 OR NOT COALESCE((((NEW.article_url='https://synthetic.publisher.example/article-xml.xml' OR registered IS NOT NULL)
 AND NEW.observation->>'parser_version'='elsevier-xml-head-v1'
 AND NEW.observation->>'route'='article_xml'
 AND NEW.observation->>'status' IN ('observed','no_contact','partial','unsupported'))
 OR ((NEW.article_url<>'https://synthetic.publisher.example/article-xml.xml' AND registered IS NULL AND NEW.article_url NOT IN ('https://synthetic.publisher.example/ambiguous.pdf','https://synthetic.publisher.example/article-a.pdf','https://synthetic.publisher.example/article-b.pdf','https://synthetic.publisher.example/corrupt.pdf','https://synthetic.publisher.example/encrypted.pdf','https://synthetic.publisher.example/no-contact.pdf','https://synthetic.publisher.example/page-cap.pdf','https://synthetic.publisher.example/scanned.pdf','https://synthetic.publisher.example/wrapped.pdf'))
 AND NEW.observation->>'parser_version'='synthetic-html-v1'
 AND NEW.observation->>'route' IN ('html','browser_dom')
 AND NEW.observation->>'status' IN ('observed','no_contact','requires_browser'))
 OR (NEW.article_url IN ('https://synthetic.publisher.example/ambiguous.pdf','https://synthetic.publisher.example/article-a.pdf','https://synthetic.publisher.example/article-b.pdf','https://synthetic.publisher.example/corrupt.pdf','https://synthetic.publisher.example/encrypted.pdf','https://synthetic.publisher.example/no-contact.pdf','https://synthetic.publisher.example/page-cap.pdf','https://synthetic.publisher.example/scanned.pdf','https://synthetic.publisher.example/wrapped.pdf') AND NEW.observation->>'route'='pdf' AND NEW.observation->>'parser_version'='pypdf-6.20.1-synthetic-v1' AND NEW.observation->>'status' IN ('observed','no_contact','partial','unsupported'))),false)
 OR COALESCE(jsonb_typeof(NEW.observation->'authors'),'')<>'array'
 OR COALESCE(jsonb_typeof(NEW.observation->'candidates'),'')<>'array'
 OR jsonb_array_length(NEW.observation->'authors') NOT BETWEEN (CASE WHEN NEW.observation->>'status'='unsupported' THEN 0 ELSE 1 END) AND 100
 OR jsonb_array_length(NEW.observation->'candidates')>100
 OR COALESCE(NEW.observation->>'content_digest','') !~ '^[0-9a-f]{64}$'
 THEN RAISE EXCEPTION 'ARTICLE_OBSERVATION_FENCE'; END IF;
 SELECT policy INTO p FROM emailmonitor.source_policies WHERE organization_id=NEW.organization_id
 AND source_id='synthetic-publisher' AND version=NEW.policy_version;
 IF j.request->>'purpose' IS DISTINCT FROM p->>'purpose'
 OR NOT (p->'allowed_operations' ? 'extract_contacts')
 OR (p->'retention'->>'contact_days')::integer<=0
 OR NOT (p->'allowed_operations' ? emailmonitor.fixture_acquisition_operation(NEW.article_url))
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
 WHEN 'https://synthetic.publisher.example/ambiguous.pdf' THEN '7ff5d5fe802aa77b1ce845f9ebb2fcfbe98e556f96836716045e949ee7645306'
 WHEN 'https://synthetic.publisher.example/article-a.pdf' THEN 'a216f8bde348256ee912f592956dfc66ea83b106e2f4c05b3c6a28f5e6cfd9cc'
 WHEN 'https://synthetic.publisher.example/article-b.pdf' THEN 'e24a7228b39e04c6f56203317ef90300c6a8b622b16f3672c8cc83784d0d0b8a'
 WHEN 'https://synthetic.publisher.example/corrupt.pdf' THEN 'bfdd8c6384be76b5ab1ed6f2aa9a2a3fdcb49c8f62ffda3bdcb85091bc14b111'
 WHEN 'https://synthetic.publisher.example/encrypted.pdf' THEN '4e253514d7bb1007937cc7456821c9b5393a275e748658847208590029e4b18e'
 WHEN 'https://synthetic.publisher.example/no-contact.pdf' THEN '3db38695a632f805b3b56571f12c133bbd80c56d4cddcbc812a025876e8e1d59'
 WHEN 'https://synthetic.publisher.example/page-cap.pdf' THEN '8e64ad429519fe6f45c17902e032e57f4d0568f3809475bb350f6f532878cb59'
 WHEN 'https://synthetic.publisher.example/scanned.pdf' THEN 'a1c762aad46bd8f0eda32a51dee4d8026ac7800c38b4e1f04578d5d9ee98d089'
 WHEN 'https://synthetic.publisher.example/wrapped.pdf' THEN 'ee5449815873cca0eca7e919b340d0598b1863f4bf439a9b4eef14fae6b893fb'
 WHEN 'https://synthetic.publisher.example/article-xml.xml' THEN 'ecffa55455f07f6205a1bb2ab6bc30f7e2528845eae757a17c32d88c5fa4ec30'
 WHEN 'https://synthetic.publisher.example/article-a.html' THEN '33c3bddb62834da34acb300b7c0bd7bb4c8728fb57e5ece43b8fc4e81920c3f0'
 WHEN 'https://synthetic.publisher.example/article-b.html' THEN '87cd02138f7cc3dfa921ccdf9b2a1613e21529c1c89c3f36fcf36fd0ba8530b1'
 WHEN 'https://synthetic.publisher.example/tooltip.html' THEN 'f5ef425b50becc43b78b5a94c120c698d2c11d3d394325112d02355a0c27a893'
 WHEN 'https://synthetic.publisher.example/no-contact.html' THEN 'e743113b240ab1e931df471a9a3d8bd0137fc89157d69803a9238de3c8985b01' END;
 IF registered IS NOT NULL THEN source_hash:=registered->>'content_digest'; END IF;
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
 OR (NEW.observation->>'status' NOT IN ('observed','partial') AND jsonb_array_length(NEW.observation->'candidates')<>0)
 THEN RAISE EXCEPTION 'ARTICLE_OBSERVATION_PROVENANCE'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.observation->'candidates') candidate
 WHERE COALESCE(candidate->>'association_status','') NOT IN ('unmatched','needs_review')
 OR candidate->>'technical_status' IS DISTINCT FROM 'not_checked'
 OR candidate->>'delivery_status' IS DISTINCT FROM 'unverified'
 OR candidate->>'outreach_eligibility' IS DISTINCT FROM 'not_assessed')
 THEN RAISE EXCEPTION 'ARTICLE_OBSERVATION_NOT_ASSOCIATION'; END IF;


 IF NEW.observation->>'route'='pdf' AND (
 j.state<>'running' OR NEW.observation->>'content_digest' IS DISTINCT FROM source_hash
 OR NEW.observation->>'retention_profile' IS DISTINCT FROM 'authored-pdf-retention-v1'
 OR NEW.observation->>'input_mode' IS DISTINCT FROM 'authored_local_fixture'
 OR NEW.observation->>'isolation_profile' IS DISTINCT FROM 'network-none-parser-v1'
 OR NEW.observation->'ocr_implemented' IS DISTINCT FROM 'false'::jsonb
 OR NOT COALESCE((j.request->'options'->>'allow_pdf')::boolean,true)
 OR octet_length(NEW.observation::text)>131072
 OR NEW.observation->'binding' IS DISTINCT FROM jsonb_build_object(
 'organization',NEW.organization_id,'job',NEW.job_id,'item',current_setting('emailmonitor.execution_item',true),
 'generation',NEW.generation,'deletion_generation',NEW.deletion_generation,
 'policy_version',NEW.policy_version,'discovery_revision',NEW.discovery_revision)
 OR NEW.observation->'excerpts_retained' IS DISTINCT FROM to_jsonb(jsonb_path_exists(NEW.observation,'$.**.excerpt ? (@ != "")'))
 OR (NEW.observation->>'status' IN ('observed','no_contact') AND
 (NEW.observation->'complete_scan' IS DISTINCT FROM 'true'::jsonb OR NEW.observation->>'reason' IS DISTINCT FROM 'complete'))
 OR (NEW.observation->>'status'='partial' AND
 (NEW.observation->'complete_scan' IS DISTINCT FROM 'false'::jsonb OR NEW.observation->>'reason' IS DISTINCT FROM 'page_cap'))
 OR (NEW.observation->>'status'='unsupported' AND
 (jsonb_array_length(NEW.observation->'authors')<>0 OR jsonb_array_length(NEW.observation->'candidates')<>0
 OR NEW.observation->'complete_scan' IS DISTINCT FROM 'false'::jsonb)))
 THEN RAISE EXCEPTION 'PDF_OBSERVATION_PROVENANCE'; END IF;
 IF NEW.observation->>'route'='article_xml' AND (
 j.state<>'running' OR NEW.observation->>'content_digest' IS DISTINCT FROM source_hash
 OR NEW.observation->>'acquisition_digest' IS DISTINCT FROM source_hash
 OR NEW.observation->>'canonical_url' IS DISTINCT FROM CASE WHEN registered IS NULL THEN 'https://api.elsevier.com/content/article/doi/10.9999/synthetic.1' ELSE 'https://api.elsevier.com/content/article/'||(registered->'identifier'->>'kind')||'/'||(registered->'identifier'->>'value') END
 OR NEW.observation->'requested_identifier' IS DISTINCT FROM COALESCE(registered->'identifier','{"kind":"doi","value":"10.9999/synthetic.1"}'::jsonb)
 OR NEW.observation->>'source_profile' IS DISTINCT FROM COALESCE(registered->>'source_profile','article_retrieval_response')
 OR NEW.observation->>'isolation_profile' IS DISTINCT FROM 'network-none-parser-v1'
 OR NEW.observation->'preferred_metadata' IS DISTINCT FROM '{"title":null,"journal":null,"publication_date":null,"doi":null}'::jsonb
 OR NEW.observation->'binding' IS DISTINCT FROM jsonb_build_object(
 'organization',NEW.organization_id::text,'job',NEW.job_id::text,
 'item',current_setting('emailmonitor.execution_item',true),
 'generation',NEW.generation,'deletion_generation',NEW.deletion_generation,
 'policy_version',NEW.policy_version,'discovery_revision',NEW.discovery_revision)
 OR NEW.observation->'excerpts_retained' IS DISTINCT FROM to_jsonb(jsonb_path_exists(NEW.observation,'$.**.excerpt ? (@ != "")'))
 OR (NEW.observation->>'status' IN ('partial','unsupported') AND COALESCE(jsonb_array_length(NEW.observation->'reasons'),0)=0)
 OR (NEW.observation->>'status'='unsupported' AND jsonb_array_length(NEW.observation->'authors')<>0)
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.observation->'candidates') candidate WHERE
 COALESCE(jsonb_typeof(candidate->'association_evidence'),'')<>'array'
 OR (jsonb_array_length(candidate->'author_positions')>0)<>(jsonb_array_length(candidate->'association_evidence')>0))
 ) THEN RAISE EXCEPTION 'XML_OBSERVATION_PROVENANCE'; END IF;
 IF registered IS NULL THEN
 IF COALESCE(NEW.observation->'provider','null'::jsonb)<>'null'::jsonb THEN RAISE EXCEPTION 'PROVIDER_OBSERVATION_PROVENANCE'; END IF;
 ELSE
 provider_url:='https://api.elsevier.com/content/article/'||(registered->'identifier'->>'kind')||'/'||(registered->'identifier'->>'value')||'?view=FULL';
 provider_fingerprint:=CASE NEW.article_url WHEN 'https://synthetic.publisher.example/provider-doi.xml' THEN 'f41f2ceb619c6ad8d0eb1ca19854261f317825ecd5721a93fa53634de16bc7ea' WHEN 'https://synthetic.publisher.example/provider-pii.xml' THEN '1515cf9338a6f89e02d4ba88150828423f25ed87356e3bd13214b8b332e0ed92' END;
 IF provider_fingerprint IS NULL OR NEW.observation->'provider' IS DISTINCT FROM jsonb_build_object(
 'source_id',NEW.source_id,'acquisition_mode','controlled_fixture','transport_url',provider_url,
 'request_fingerprint',provider_fingerprint,'requested_view','FULL')
 THEN RAISE EXCEPTION 'PROVIDER_OBSERVATION_PROVENANCE'; END IF;
 END IF;
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
END $function$
;

CREATE OR REPLACE FUNCTION emailmonitor.service_schema_ready()
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
 SELECT (SELECT count(*)=1 AND min(version_num)='0018_authored_pdf' FROM public.alembic_version)
$function$
;

-- Additional restrictive release fence, including narrow service reads.
CREATE POLICY pdf_current ON emailmonitor.article_observations AS RESTRICTIVE FOR SELECT
USING (observation->>'route'<>'pdf' OR EXISTS(
 SELECT 1 FROM emailmonitor.source_policies p JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
 JOIN emailmonitor.source_catalog s USING(source_id)
 WHERE p.organization_id=article_observations.organization_id AND p.source_id=article_observations.source_id
 AND p.version=article_observations.policy_version AND p.version=h.current_version
 AND p.state='approved' AND p.valid_until>clock_timestamp() AND s.enabled
 AND p.policy->'allowed_operations' ? 'parse_fixture_pdf'
 AND 'parse_fixture_pdf'=ANY(s.allowed_operations)
 AND s.support->'routes_by_operation'->'parse_fixture_pdf' ? replace(article_observations.article_url,'https://synthetic.publisher.example','')));
CREATE OR REPLACE FUNCTION emailmonitor.guard_association_batch()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE a emailmonitor.article_observations;
BEGIN
 PERFORM emailmonitor.association_parent_fence(NEW.organization_id,NEW.job_id,NEW.article_url,NEW.source_revision,true);
 IF TG_OP='UPDATE' THEN
 IF (to_jsonb(NEW)-'sealed') IS DISTINCT FROM (to_jsonb(OLD)-'sealed') OR OLD.sealed OR NOT NEW.sealed
 THEN RAISE EXCEPTION 'ASSOCIATION_IMMUTABLE'; END IF;
 ELSE
 IF NEW.sealed OR NOT COALESCE(emailmonitor.job_write_allowed(NEW.organization_id,NEW.job_id),false)
 THEN RAISE EXCEPTION 'ASSOCIATION_DENIED' USING ERRCODE='EM009'; END IF;
 END IF;
 SELECT * INTO a FROM emailmonitor.article_observations WHERE organization_id=NEW.organization_id AND job_id=NEW.job_id AND article_url=NEW.article_url;
 IF NEW.snapshot->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
 OR NEW.snapshot->>'source_url' IS DISTINCT FROM NEW.article_url
 OR NEW.snapshot->>'content_digest' IS DISTINCT FROM a.observation->>'content_digest'
 OR NEW.snapshot->>'parser_version' IS DISTINCT FROM a.observation->>'parser_version'
 OR NEW.snapshot->>'observation_route' IS DISTINCT FROM a.observation->>'route'
 OR NEW.snapshot->>'observation_status' IS DISTINCT FROM a.observation->>'status'
 OR NEW.snapshot->'technical_network_checks' IS DISTINCT FROM 'false'::jsonb
 OR NEW.snapshot->'exports_available' IS DISTINCT FROM 'false'::jsonb
 OR NEW.snapshot->>'schema_version' IS DISTINCT FROM '1.0'
 OR COALESCE(jsonb_typeof(NEW.snapshot->'authors'),'')<>'array'
 OR COALESCE(jsonb_typeof(NEW.snapshot->'candidates'),'')<>'array'
 OR COALESCE(jsonb_typeof(NEW.snapshot->'evidence'),'')<>'array'
 OR COALESCE(jsonb_typeof(NEW.snapshot->'associations'),'')<>'array'
 OR jsonb_array_length(NEW.snapshot->'authors')>100 OR jsonb_array_length(NEW.snapshot->'candidates')>100
 OR jsonb_array_length(NEW.snapshot->'evidence')>2400 OR jsonb_array_length(NEW.snapshot->'associations')>10000
 THEN RAISE EXCEPTION 'ASSOCIATION_SNAPSHOT'; END IF;
 IF NEW.snapshot->'preferred_metadata' IS DISTINCT FROM a.observation->'preferred_metadata'
 OR jsonb_array_length(NEW.snapshot->'authors')<>jsonb_array_length(a.observation->'authors')
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.snapshot->'authors') x WHERE NOT EXISTS(
 SELECT 1 FROM jsonb_array_elements(a.observation->'authors') y
 WHERE x->'position'=y->'position' AND x->'display_name'=y->'display_name'
 AND x->'first'=y->'first' AND x->'corresponding'=y->'corresponding'
 AND x->'affiliations'=y->'affiliations' AND ((a.observation->>'route'='pdf' AND x->'orcid'='null'::jsonb AND x->>'kind'='unknown') OR (a.observation->>'route'<>'pdf' AND x->'orcid'=y->'orcid' AND x->'kind'=y->'author_kind'))))
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.snapshot->'candidates') x,
 jsonb_array_elements_text(x->'raw_variants') raw(value) WHERE NOT EXISTS(
 SELECT 1 FROM jsonb_array_elements(a.observation->'candidates') y WHERE y->>'raw_address'=raw.value))
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.snapshot->'evidence') x WHERE NOT EXISTS(
 SELECT 1 FROM jsonb_path_query(a.observation,'$.** ? (@.locator != null && @.excerpt != null)') y
 WHERE x->'locator'=y->'locator' AND x->'excerpt'=y->'excerpt' AND (
 (a.observation->>'route'='pdf' AND x->>'method'='pdf_text'
 AND x->'page'=y->'page' AND x->'anchor'=y->'anchor' AND x->'region'=y->'region'
 AND x->'coordinate_units'=y->'coordinate_units' AND x->'coordinate_origin'=y->'coordinate_origin'
 AND x->'region_precision'=y->'region_precision') OR
 (a.observation->>'route'<>'pdf' AND x->'method'=y->'kind'
 AND x->'page'='null'::jsonb AND x->'anchor'='null'::jsonb AND x->'region'='null'::jsonb
 AND x->'coordinate_units'='null'::jsonb AND x->'coordinate_origin'='null'::jsonb AND x->'region_precision'='null'::jsonb))))
 THEN RAISE EXCEPTION 'ASSOCIATION_SOURCE_PROVENANCE'; END IF;
 NEW.policy_version:=a.policy_version; NEW.generation:=a.generation; NEW.deletion_generation:=a.deletion_generation; NEW.expires_at:=a.expires_at;
 RETURN NEW;
END $function$
;
RESET ROLE;
