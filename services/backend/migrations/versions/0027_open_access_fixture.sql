-- OA-029 (document 91): registered synthetic Open Access JATS fixtures under the
-- synthetic-publisher fixture source. Offline only: no live policy, role, grant or
-- network activation. Every pre-existing predicate is carried over unchanged; the
-- edits below only add the jats_xml route and its four registered article paths.
SET ROLE emailmonitor_owner;

CREATE FUNCTION emailmonitor.registered_open_access_document(p_source text,p_url text) RETURNS jsonb
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT value FROM emailmonitor.source_catalog c,
 jsonb_array_elements(COALESCE(c.support->'open_access_documents','[]'::jsonb)) value
 WHERE c.source_id=p_source AND c.execution_mode='fixture'
 AND value->>'source_id'=p_source AND value->>'source_url'=p_url
 AND value->>'provider'='europe-pmc' AND value->>'acquisition_mode'='controlled_fixture'
$$;
REVOKE ALL ON FUNCTION emailmonitor.registered_open_access_document(text,text) FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;

UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,'{open_access_documents}','[{"source_id":"synthetic-publisher","provider":"europe-pmc","pmcid":"PMC10293847","source_url":"https://synthetic.publisher.example/oa/PMC10293847.xml","canonical_url":"https://www.ebi.ac.uk/europepmc/webservices/rest/PMC10293847/fullTextXML","content_digest":"da8488e0c0e6ec9f55535e4a5761e7ab574ff3d6af3e76b5e6862c6f2da2c603","acquisition_mode":"controlled_fixture"},{"source_id":"synthetic-publisher","provider":"europe-pmc","pmcid":"PMC1234567","source_url":"https://synthetic.publisher.example/oa/PMC1234567.xml","canonical_url":"https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1234567/fullTextXML","content_digest":"7e282973dddd8fa1d101ea66989d8873e0651e9ffe163ed9b905a8309b9ae4cf","acquisition_mode":"controlled_fixture"},{"source_id":"synthetic-publisher","provider":"europe-pmc","pmcid":"PMC887766","source_url":"https://synthetic.publisher.example/oa/PMC887766.xml","canonical_url":"https://www.ebi.ac.uk/europepmc/webservices/rest/PMC887766/fullTextXML","content_digest":"aadc9fa4d5424086271e225e6fd64c3efda367505ed51edf41333d26fa7696be","acquisition_mode":"controlled_fixture"},{"source_id":"synthetic-publisher","provider":"europe-pmc","pmcid":"PMC7700001","source_url":"https://synthetic.publisher.example/oa/PMC7700001.xml","canonical_url":"https://www.ebi.ac.uk/europepmc/webservices/rest/PMC7700001/fullTextXML","content_digest":"76a5fffb223ab16da05d29246c4f80f0def5cff431eecd2ee936d4c2a2fe575d","acquisition_mode":"controlled_fixture"}]'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';

UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,'{fixture_routes}',(support#>'{fixture_routes}')||'["/oa/PMC10293847.xml", "/oa/PMC1234567.xml", "/oa/PMC887766.xml", "/oa/PMC7700001.xml"]'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';

UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,'{routes_by_operation,fetch_xml}',(support#>'{routes_by_operation,fetch_xml}')||'["/oa/PMC10293847.xml", "/oa/PMC1234567.xml", "/oa/PMC887766.xml", "/oa/PMC7700001.xml"]'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';

UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,'{routes_by_operation,extract_contacts}',(support#>'{routes_by_operation,extract_contacts}')||'["/oa/PMC10293847.xml", "/oa/PMC1234567.xml", "/oa/PMC887766.xml", "/oa/PMC7700001.xml"]'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';

UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,'{routes_by_operation,retain_excerpt}',(support#>'{routes_by_operation,retain_excerpt}')||'["/oa/PMC10293847.xml", "/oa/PMC1234567.xml", "/oa/PMC887766.xml", "/oa/PMC7700001.xml"]'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';

UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,'{routes_by_operation,export_contacts}',(support#>'{routes_by_operation,export_contacts}')||'["/oa/PMC10293847.xml", "/oa/PMC1234567.xml", "/oa/PMC887766.xml", "/oa/PMC7700001.xml"]'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';

ALTER TABLE emailmonitor.article_observations DROP CONSTRAINT article_observations_article_url_check;
ALTER TABLE emailmonitor.article_observations ADD CONSTRAINT article_observations_article_url_check CHECK ((article_url = ANY (ARRAY['https://synthetic.publisher.example/article-a.html'::text, 'https://synthetic.publisher.example/article-b.html'::text, 'https://synthetic.publisher.example/tooltip.html'::text, 'https://synthetic.publisher.example/no-contact.html'::text, 'https://synthetic.publisher.example/article-xml.xml'::text, 'https://synthetic.publisher.example/provider-doi.xml'::text, 'https://synthetic.publisher.example/provider-pii.xml'::text, 'https://synthetic.publisher.example/ambiguous.pdf'::text, 'https://synthetic.publisher.example/article-a.pdf'::text, 'https://synthetic.publisher.example/article-b.pdf'::text, 'https://synthetic.publisher.example/corrupt.pdf'::text, 'https://synthetic.publisher.example/encrypted.pdf'::text, 'https://synthetic.publisher.example/no-contact.pdf'::text, 'https://synthetic.publisher.example/page-cap.pdf'::text, 'https://synthetic.publisher.example/scanned.pdf'::text, 'https://synthetic.publisher.example/wrapped.pdf'::text, 'https://synthetic.publisher.example/oa/PMC10293847.xml'::text, 'https://synthetic.publisher.example/oa/PMC1234567.xml'::text, 'https://synthetic.publisher.example/oa/PMC887766.xml'::text, 'https://synthetic.publisher.example/oa/PMC7700001.xml'::text])));

ALTER TABLE emailmonitor.execution_items DROP CONSTRAINT execution_items_input_url_check;
ALTER TABLE emailmonitor.execution_items ADD CONSTRAINT execution_items_input_url_check CHECK ((input_url = ANY (ARRAY['https://synthetic.publisher.example/search-page-1.html'::text, 'https://synthetic.publisher.example/search-page-2.html'::text, 'https://synthetic.publisher.example/article-a.html'::text, 'https://synthetic.publisher.example/article-b.html'::text, 'https://synthetic.publisher.example/tooltip.html'::text, 'https://synthetic.publisher.example/no-contact.html'::text, 'https://synthetic.publisher.example/article-xml.xml'::text, 'https://synthetic.publisher.example/provider-search-0.json'::text, 'https://synthetic.publisher.example/provider-doi.xml'::text, 'https://synthetic.publisher.example/provider-pii.xml'::text, 'https://synthetic.publisher.example/ambiguous.pdf'::text, 'https://synthetic.publisher.example/article-a.pdf'::text, 'https://synthetic.publisher.example/article-b.pdf'::text, 'https://synthetic.publisher.example/corrupt.pdf'::text, 'https://synthetic.publisher.example/encrypted.pdf'::text, 'https://synthetic.publisher.example/no-contact.pdf'::text, 'https://synthetic.publisher.example/page-cap.pdf'::text, 'https://synthetic.publisher.example/scanned.pdf'::text, 'https://synthetic.publisher.example/wrapped.pdf'::text, 'https://synthetic.publisher.example/oa/PMC10293847.xml'::text, 'https://synthetic.publisher.example/oa/PMC1234567.xml'::text, 'https://synthetic.publisher.example/oa/PMC887766.xml'::text, 'https://synthetic.publisher.example/oa/PMC7700001.xml'::text])));

CREATE OR REPLACE FUNCTION emailmonitor.fixture_acquisition_operation(p_url text)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
 SELECT CASE WHEN p_url IN ('https://synthetic.publisher.example/article-xml.xml',
 'https://synthetic.publisher.example/provider-doi.xml','https://synthetic.publisher.example/provider-pii.xml','https://synthetic.publisher.example/oa/PMC10293847.xml','https://synthetic.publisher.example/oa/PMC1234567.xml','https://synthetic.publisher.example/oa/PMC887766.xml','https://synthetic.publisher.example/oa/PMC7700001.xml') THEN 'fetch_xml'
 WHEN p_url='https://synthetic.publisher.example/provider-search-0.json' THEN 'search'
 WHEN p_url IN ('https://synthetic.publisher.example/ambiguous.pdf','https://synthetic.publisher.example/article-a.pdf','https://synthetic.publisher.example/article-b.pdf','https://synthetic.publisher.example/corrupt.pdf','https://synthetic.publisher.example/encrypted.pdf','https://synthetic.publisher.example/no-contact.pdf','https://synthetic.publisher.example/page-cap.pdf','https://synthetic.publisher.example/scanned.pdf','https://synthetic.publisher.example/wrapped.pdf') THEN 'parse_fixture_pdf' ELSE 'fetch_html' END
$function$;

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
 'https://synthetic.publisher.example/tooltip.html','https://synthetic.publisher.example/no-contact.html','https://synthetic.publisher.example/article-xml.xml','https://synthetic.publisher.example/provider-search-0.json','https://synthetic.publisher.example/provider-doi.xml','https://synthetic.publisher.example/provider-pii.xml','https://synthetic.publisher.example/oa/PMC10293847.xml','https://synthetic.publisher.example/oa/PMC1234567.xml','https://synthetic.publisher.example/oa/PMC887766.xml','https://synthetic.publisher.example/oa/PMC7700001.xml','https://synthetic.publisher.example/ambiguous.pdf','https://synthetic.publisher.example/article-a.pdf','https://synthetic.publisher.example/article-b.pdf','https://synthetic.publisher.example/corrupt.pdf','https://synthetic.publisher.example/encrypted.pdf','https://synthetic.publisher.example/no-contact.pdf','https://synthetic.publisher.example/page-cap.pdf','https://synthetic.publisher.example/scanned.pdf','https://synthetic.publisher.example/wrapped.pdf') THEN
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
END $function$;

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
 AND (a.observation->>'route' NOT IN ('article_xml','jats_xml') OR (p.policy->'allowed_operations' ? 'fetch_xml' AND 'fetch_xml'=ANY(s.allowed_operations)))
 AND (a.observation->>'route'<>'browser_dom' OR (p.policy->'allowed_operations' ? 'browser' AND 'browser'=ANY(s.allowed_operations)))
 AND (NOT jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")') OR (
 p.policy->'allowed_operations' ? 'retain_excerpt' AND 'retain_excerpt'=ANY(s.allowed_operations) AND (p.policy->'retention'->>'excerpt_days')::integer>0)));
END $function$;

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
 AND (a.observation->>'route' NOT IN ('article_xml','jats_xml') OR (p.policy->'allowed_operations' ? 'fetch_xml' AND 'fetch_xml'=ANY(s.allowed_operations)))
 AND (a.observation->>'route'<>'browser_dom' OR (p.policy->'allowed_operations' ? 'browser' AND 'browser'=ANY(s.allowed_operations)))
 AND (NOT jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")') OR (
 p.policy->'allowed_operations' ? 'retain_excerpt' AND 'retain_excerpt'=ANY(s.allowed_operations) AND (p.policy->'retention'->>'excerpt_days')::integer>0)));
END $function$;

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
 AND (a.observation->>'route' NOT IN ('article_xml','jats_xml') OR (p.policy->'allowed_operations' ? 'fetch_xml' AND 'fetch_xml'=ANY(s.allowed_operations)))
 AND (a.observation->>'route'<>'browser_dom' OR (p.policy->'allowed_operations' ? 'browser' AND 'browser'=ANY(s.allowed_operations)))
 AND (NOT jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")') OR (
 p.policy->'allowed_operations' ? 'retain_excerpt' AND 'retain_excerpt'=ANY(s.allowed_operations) AND (p.policy->'retention'->>'excerpt_days')::integer>0)));
END $function$;

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
 AND (a.observation->>'route' NOT IN ('article_xml','pdf','jats_xml') OR a.observation->'binding'=jsonb_build_object(
 'organization',p_org,'job',b.job_id,'item',original.id,'generation',b.generation,
 'deletion_generation',b.deletion_generation,'policy_version',b.policy_version,'discovery_revision',a.discovery_revision)
 OR (a.reused_from_job IS NOT NULL
  AND emailmonitor.retained_reuse_current(p_org,a.job_id)
  AND emailmonitor.retained_reuse_bound_source(p_org,a.reused_from_job,
   a.reused_source_batch,a.article_url)))
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
END $function$;

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
 ELSIF route='jats_xml' THEN
 IF jsonb_typeof(p_document->'reasons') IS DISTINCT FROM 'array' THEN RETURN 'unresolved'; END IF;
 IF NOT COALESCE(p_document->>'parser_version'='open-access-jats-v2'
 AND status IN ('observed','no_contact','partial','unsupported')
 AND (jsonb_array_length(p_document->'reasons')>0)=(status='partial'),false)
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
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.guard_article_observation()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE d emailmonitor.discovery; j emailmonitor.jobs; source_hash text; p jsonb; days integer; registered jsonb; provider_url text; provider_fingerprint text; reuse_bound boolean:=false; oa jsonb;
BEGIN
 registered:=emailmonitor.registered_provider_document(NEW.source_id,NEW.article_url);
 oa:=emailmonitor.registered_open_access_document(NEW.source_id,NEW.article_url);
 IF NOT emailmonitor.privacy_payload_allowed(NEW.organization_id,NEW.observation) OR NOT emailmonitor.privacy_excerpt_allowed(NEW.organization_id,NEW.observed_at,NEW.observation) OR (jsonb_path_exists(NEW.observation,'$.**.excerpt ? (@ != "")') AND EXISTS(SELECT 1 FROM emailmonitor.lifecycle_job_deadlines deadline WHERE deadline.organization_id=NEW.organization_id AND deadline.job_id=NEW.job_id AND deadline.excerpt_deadline<=clock_timestamp())) THEN RAISE EXCEPTION 'PRIVACY_SUPPRESSED' USING ERRCODE='EM014'; END IF;
 PERFORM emailmonitor.discovery_source_fence(NEW.organization_id,NEW.job_id,NEW.policy_version);
 SELECT * INTO d FROM emailmonitor.discovery WHERE organization_id=NEW.organization_id
 AND job_id=NEW.job_id FOR SHARE;
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=NEW.organization_id
 AND id=NEW.job_id FOR SHARE;
 -- BEGIN staged bound-reuse-only checks.
 IF NEW.reused_from_job IS NOT NULL AND NEW.observation->>'route' IN ('pdf','article_xml') THEN
  IF TG_OP<>'INSERT' OR j.state<>'draft' OR NEW.reused_from_job=NEW.job_id
   OR NOT COALESCE(emailmonitor.human_work_tenant_allowed(NEW.organization_id),false)
   OR NOT COALESCE(emailmonitor.job_write_allowed(NEW.organization_id,NEW.job_id),false)
   OR j.request->'reuse'->>'mode' IS DISTINCT FROM 'verified_retained'
  THEN RAISE EXCEPTION 'REUSE_BOUND_SOURCE_DENIED' USING ERRCODE='EM009'; END IF;
  PERFORM emailmonitor.association_parent_fence(NEW.organization_id,NEW.reused_from_job,
   NEW.article_url,NEW.reused_source_revision,false);
  SELECT EXISTS(SELECT 1 FROM emailmonitor.article_observations original
   WHERE original.organization_id=NEW.organization_id AND original.job_id=NEW.reused_from_job
   AND original.article_url=NEW.article_url AND original.revision=NEW.reused_source_revision
   AND original.reused_from_job IS NULL AND original.source_id=NEW.source_id
   AND original.policy_version=NEW.policy_version
   AND original.deletion_generation=NEW.deletion_generation
   AND original.source_digest=NEW.source_digest AND original.observation=NEW.observation
   AND emailmonitor.privacy_job_allowed(NEW.organization_id,original.job_id)
   AND emailmonitor.association_visible(NEW.organization_id,NEW.reused_source_batch)
   AND emailmonitor.retained_reuse_bound_source(NEW.organization_id,original.job_id,
    NEW.reused_source_batch,NEW.article_url)) INTO reuse_bound;
  IF NOT reuse_bound THEN RAISE EXCEPTION 'REUSE_BOUND_SOURCE_DENIED' USING ERRCODE='EM009'; END IF;
 END IF;
 -- END staged bound-reuse-only checks.
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
 OR (oa IS NOT NULL AND NEW.observation->>'parser_version'='open-access-jats-v2'
 AND NEW.observation->>'route'='jats_xml'
 AND NEW.observation->>'status' IN ('observed','no_contact','partial','unsupported'))
 OR ((NEW.article_url<>'https://synthetic.publisher.example/article-xml.xml' AND registered IS NULL AND oa IS NULL AND NEW.article_url NOT IN ('https://synthetic.publisher.example/ambiguous.pdf','https://synthetic.publisher.example/article-a.pdf','https://synthetic.publisher.example/article-b.pdf','https://synthetic.publisher.example/corrupt.pdf','https://synthetic.publisher.example/encrypted.pdf','https://synthetic.publisher.example/no-contact.pdf','https://synthetic.publisher.example/page-cap.pdf','https://synthetic.publisher.example/scanned.pdf','https://synthetic.publisher.example/wrapped.pdf'))
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
 IF oa IS NOT NULL THEN source_hash:=oa->>'content_digest'; END IF;
 -- Exact new authored bytes; prior pinned bytes remain valid retained history.
 IF NEW.article_url='https://synthetic.publisher.example/article-a.html' AND NEW.source_digest='a776106710399f4aa596f42430b5a5283b0d0ea8efafd55460ef2c83782884df' THEN source_hash:='a776106710399f4aa596f42430b5a5283b0d0ea8efafd55460ef2c83782884df'; END IF;
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
 (j.state<>'running' AND NOT reuse_bound) OR NEW.observation->>'content_digest' IS DISTINCT FROM source_hash
 OR NEW.observation->>'retention_profile' IS DISTINCT FROM 'authored-pdf-retention-v1'
 OR NEW.observation->>'input_mode' IS DISTINCT FROM 'authored_local_fixture'
 OR NEW.observation->>'isolation_profile' IS DISTINCT FROM 'network-none-parser-v1'
 OR NEW.observation->'ocr_implemented' IS DISTINCT FROM 'false'::jsonb
 OR NOT COALESCE((j.request->'options'->>'allow_pdf')::boolean,true)
 OR octet_length(NEW.observation::text)>131072
 OR (NOT reuse_bound AND NEW.observation->'binding' IS DISTINCT FROM jsonb_build_object(
 'organization',NEW.organization_id,'job',NEW.job_id,'item',current_setting('emailmonitor.execution_item',true),
 'generation',NEW.generation,'deletion_generation',NEW.deletion_generation,
 'policy_version',NEW.policy_version,'discovery_revision',NEW.discovery_revision))
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
 (j.state<>'running' AND NOT reuse_bound) OR NEW.observation->>'content_digest' IS DISTINCT FROM source_hash
 OR NEW.observation->>'acquisition_digest' IS DISTINCT FROM source_hash
 OR NEW.observation->>'canonical_url' IS DISTINCT FROM CASE WHEN registered IS NULL THEN 'https://api.elsevier.com/content/article/doi/10.9999/synthetic.1' ELSE 'https://api.elsevier.com/content/article/'||(registered->'identifier'->>'kind')||'/'||(registered->'identifier'->>'value') END
 OR NEW.observation->'requested_identifier' IS DISTINCT FROM COALESCE(registered->'identifier','{"kind":"doi","value":"10.9999/synthetic.1"}'::jsonb)
 OR NEW.observation->>'source_profile' IS DISTINCT FROM COALESCE(registered->>'source_profile','article_retrieval_response')
 OR NEW.observation->>'isolation_profile' IS DISTINCT FROM 'network-none-parser-v1'
 OR NEW.observation->'preferred_metadata' IS DISTINCT FROM '{"title":null,"journal":null,"publication_date":null,"doi":null}'::jsonb
 OR (NOT reuse_bound AND NEW.observation->'binding' IS DISTINCT FROM jsonb_build_object(
 'organization',NEW.organization_id::text,'job',NEW.job_id::text,
 'item',current_setting('emailmonitor.execution_item',true),
 'generation',NEW.generation,'deletion_generation',NEW.deletion_generation,
 'policy_version',NEW.policy_version,'discovery_revision',NEW.discovery_revision))
 OR NEW.observation->'excerpts_retained' IS DISTINCT FROM to_jsonb(jsonb_path_exists(NEW.observation,'$.**.excerpt ? (@ != "")'))
 OR (NEW.observation->>'status' IN ('partial','unsupported') AND COALESCE(jsonb_array_length(NEW.observation->'reasons'),0)=0)
 OR (NEW.observation->>'status'='unsupported' AND jsonb_array_length(NEW.observation->'authors')<>0)
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.observation->'candidates') candidate WHERE
 COALESCE(jsonb_typeof(candidate->'association_evidence'),'')<>'array'
 OR (jsonb_array_length(candidate->'author_positions')>0)<>(jsonb_array_length(candidate->'association_evidence')>0))
 ) THEN RAISE EXCEPTION 'XML_OBSERVATION_PROVENANCE'; END IF;
 IF (oa IS NOT NULL)<>(NEW.observation->>'route' IS NOT DISTINCT FROM 'jats_xml')
 THEN RAISE EXCEPTION 'JATS_OBSERVATION_PROVENANCE'; END IF;
 IF oa IS NOT NULL AND (
 j.state<>'running' OR NEW.reused_from_job IS NOT NULL
 OR NEW.observation->>'content_digest' IS DISTINCT FROM source_hash
 OR NEW.observation->>'acquisition_digest' IS DISTINCT FROM source_hash
 OR NEW.observation->>'canonical_url' IS DISTINCT FROM oa->>'canonical_url'
 OR NEW.observation->'requested_identifier' IS DISTINCT FROM jsonb_build_object('kind','pmcid','value',oa->>'pmcid')
 OR NEW.observation->>'full_text_provider' IS DISTINCT FROM 'europe-pmc'
 OR NEW.observation->>'isolation_profile' IS DISTINCT FROM 'network-none-parser-v1'
 OR NEW.observation->>'license_category' IS NULL
 OR octet_length(NEW.observation::text)>131072
 OR NEW.observation->'binding' IS DISTINCT FROM jsonb_build_object(
 'organization',NEW.organization_id::text,'job',NEW.job_id::text,
 'item',current_setting('emailmonitor.execution_item',true),
 'generation',NEW.generation,'deletion_generation',NEW.deletion_generation,
 'policy_version',NEW.policy_version,'discovery_revision',NEW.discovery_revision)
 OR NEW.observation->'excerpts_retained' IS DISTINCT FROM to_jsonb(jsonb_path_exists(NEW.observation,'$.**.excerpt ? (@ != "")'))
 OR COALESCE(jsonb_typeof(NEW.observation->'reasons'),'')<>'array'
 OR (jsonb_array_length(NEW.observation->'reasons')>0)<>(NEW.observation->>'status'='partial')
 OR (NEW.observation->>'status'='unsupported' AND jsonb_array_length(NEW.observation->'authors')<>0)
 ) THEN RAISE EXCEPTION 'JATS_OBSERVATION_PROVENANCE'; END IF;
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
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.service_schema_ready() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT (SELECT count(*)=1 AND min(version_num)='0027_open_access_fixture' FROM public.alembic_version)
$$;
RESET ROLE;
