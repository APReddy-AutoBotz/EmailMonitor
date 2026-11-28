-- OA-030 (document 92): Europe PMC becomes its own fixture-only catalog source.
-- No live network, role, grant widening or policy activation: the europe-pmc row is
-- execution_mode='fixture' on the synthetic fixture host, and each tenant must approve it
-- separately. Every replaced function is pg_get_functiondef() of a 0027 database edited by
-- exact, count-checked substitutions; with only synthetic-publisher rows present every
-- existing request behaves as before (results and exports default to synthetic-publisher).
SET ROLE emailmonitor_owner;

INSERT INTO emailmonitor.source_catalog(source_id,manifest_version,enabled,execution_mode,allowed_hosts,allowed_operations,support)
VALUES('europe-pmc','1.0.0',true,'fixture',ARRAY['synthetic.publisher.example'],
ARRAY['fetch_xml','extract_contacts','retain_excerpt','export_contacts'],'{"input_types": ["article"], "known_limits": ["Fixture mode only: committed synthetic JATS served from the synthetic fixture host", "No live Europe PMC connection"], "pdf_supported": false, "pdf_fixture_opt_in": false, "fixture_routes": ["/oa/PMC10293847.xml", "/oa/PMC1234567.xml", "/oa/PMC887766.xml", "/oa/PMC7700001.xml"], "routes_by_operation": {"fetch_xml": ["/oa/PMC10293847.xml", "/oa/PMC1234567.xml", "/oa/PMC887766.xml", "/oa/PMC7700001.xml"], "extract_contacts": ["/oa/PMC10293847.xml", "/oa/PMC1234567.xml", "/oa/PMC887766.xml", "/oa/PMC7700001.xml"], "retain_excerpt": ["/oa/PMC10293847.xml", "/oa/PMC1234567.xml", "/oa/PMC887766.xml", "/oa/PMC7700001.xml"], "export_contacts": ["/oa/PMC10293847.xml", "/oa/PMC1234567.xml", "/oa/PMC887766.xml", "/oa/PMC7700001.xml"]}, "open_access_documents": [{"source_id": "europe-pmc", "provider": "europe-pmc", "pmcid": "PMC10293847", "source_url": "https://synthetic.publisher.example/oa/PMC10293847.xml", "canonical_url": "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC10293847/fullTextXML", "content_digest": "da8488e0c0e6ec9f55535e4a5761e7ab574ff3d6af3e76b5e6862c6f2da2c603", "acquisition_mode": "controlled_fixture"}, {"source_id": "europe-pmc", "provider": "europe-pmc", "pmcid": "PMC1234567", "source_url": "https://synthetic.publisher.example/oa/PMC1234567.xml", "canonical_url": "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1234567/fullTextXML", "content_digest": "7e282973dddd8fa1d101ea66989d8873e0651e9ffe163ed9b905a8309b9ae4cf", "acquisition_mode": "controlled_fixture"}, {"source_id": "europe-pmc", "provider": "europe-pmc", "pmcid": "PMC887766", "source_url": "https://synthetic.publisher.example/oa/PMC887766.xml", "canonical_url": "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC887766/fullTextXML", "content_digest": "aadc9fa4d5424086271e225e6fd64c3efda367505ed51edf41333d26fa7696be", "acquisition_mode": "controlled_fixture"}, {"source_id": "europe-pmc", "provider": "europe-pmc", "pmcid": "PMC7700001", "source_url": "https://synthetic.publisher.example/oa/PMC7700001.xml", "canonical_url": "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC7700001/fullTextXML", "content_digest": "76a5fffb223ab16da05d29246c4f80f0def5cff431eecd2ee936d4c2a2fe575d", "acquisition_mode": "controlled_fixture"}], "extraction_implemented": false, "acquisition_implemented": false, "offline_html_observations_implemented": false}'::jsonb);

-- The registry moves: registered_open_access_document('synthetic-publisher',...) now returns
-- nothing, so new synthetic-labelled Open Access observations are refused. The synthetic
-- catalog keeps its /oa/ routes so retained 0027-era rows stay valid history.
UPDATE emailmonitor.source_catalog SET support=support-'open_access_documents'
WHERE source_id='synthetic-publisher' AND execution_mode='fixture' AND support ? 'open_access_documents';

ALTER TABLE emailmonitor.discovery DROP CONSTRAINT discovery_source_id_check;
ALTER TABLE emailmonitor.discovery ADD CONSTRAINT discovery_source_id_check CHECK ((source_id = ANY (ARRAY['synthetic-publisher'::text, 'europe-pmc'::text])));

ALTER TABLE emailmonitor.article_observations DROP CONSTRAINT article_observations_source_id_check;
ALTER TABLE emailmonitor.article_observations ADD CONSTRAINT article_observations_source_id_check CHECK ((source_id = ANY (ARRAY['synthetic-publisher'::text, 'europe-pmc'::text])));

ALTER TABLE emailmonitor.execution_runs DROP CONSTRAINT execution_runs_source_id_check;
ALTER TABLE emailmonitor.execution_runs ADD CONSTRAINT execution_runs_source_id_check CHECK ((source_id = ANY (ARRAY['synthetic-publisher'::text, 'europe-pmc'::text])));

-- The one source a results or export request is scoped to: the validated filter value,
-- otherwise the historical default. Any unknown value maps to the default, so filter
-- validation (result_filters_valid / export_request_validate) still decides the error.
CREATE FUNCTION emailmonitor.result_source(p_filters jsonb) RETURNS text
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN jsonb_typeof(p_filters)='object' AND p_filters->>'source_id' IN ('synthetic-publisher','europe-pmc')
 THEN p_filters->>'source_id' ELSE 'synthetic-publisher' END
$$;
REVOKE ALL ON FUNCTION emailmonitor.result_source(jsonb) FROM PUBLIC;

-- Non-locking: an export's source is fixed by its immutable stored request.
CREATE FUNCTION emailmonitor.export_source(p_org uuid,p_export uuid) RETURNS text
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE((SELECT emailmonitor.result_source(e.request) FROM emailmonitor.exports e
 WHERE e.organization_id=p_org AND e.id=p_export),'synthetic-publisher')
$$;
REVOKE ALL ON FUNCTION emailmonitor.export_source(uuid,uuid) FROM PUBLIC;

CREATE FUNCTION emailmonitor.discovery_source_fence(p_org uuid, p_job uuid, p_version bigint, p_source text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
BEGIN
 PERFORM emailmonitor.job_permission_fence(p_org,p_job);
 IF p_version IS NULL OR NOT COALESCE(emailmonitor.execution_write_allowed(p_org,p_job),false)
 THEN RAISE EXCEPTION 'EXECUTION_WORK_FENCE' USING ERRCODE='EM010'; END IF;
 -- Server-owned source only (the discovery row's source or the plan-time row being inserted).
 PERFORM 1 FROM emailmonitor.source_catalog WHERE source_id=p_source FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policy_heads WHERE organization_id=p_org
 AND source_id=p_source FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policies p JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
 WHERE p.organization_id=p_org AND p.source_id=p_source AND p.version=h.current_version FOR SHARE OF p;
 IF NOT COALESCE(emailmonitor.job_write_allowed(p_org,p_job),false) OR NOT EXISTS(
 SELECT 1 FROM emailmonitor.source_policies p JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
 JOIN emailmonitor.source_catalog s USING(source_id)
 WHERE p.organization_id=p_org AND p.source_id=p_source
 AND p.version=p_version AND p.version=h.current_version AND s.enabled
 AND p.state='approved' AND p.valid_until>clock_timestamp()) THEN RAISE EXCEPTION 'DISCOVERY_POLICY_FENCE' USING ERRCODE='EM006'; END IF;
END $function$;

REVOKE ALL ON FUNCTION emailmonitor.discovery_source_fence(uuid,uuid,bigint,text) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION emailmonitor.discovery_source_fence(uuid,uuid,bigint,text) TO emailmonitor_runtime,emailmonitor_worker;

CREATE FUNCTION emailmonitor.results_fence(p_org uuid, p_export boolean, p_requester uuid, p_policy boolean, p_source text)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE actor uuid; p emailmonitor.source_policies; s emailmonitor.source_catalog;
BEGIN
 IF NOT emailmonitor.privacy_source_allowed(p_org) OR NOT emailmonitor.privacy_source_allowed(p_org,p_source) OR (p_export AND EXISTS(SELECT 1 FROM emailmonitor.lifecycle_configuration WHERE organization_id=p_org AND (retention->>'export_hours')::integer=0)) THEN RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
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
 SELECT * INTO s FROM emailmonitor.source_catalog WHERE source_id=p_source FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.source_policy_heads WHERE organization_id=p_org
 AND source_id=p_source FOR SHARE NOWAIT;
 SELECT pp.* INTO p FROM emailmonitor.source_policies pp JOIN emailmonitor.source_policy_heads h
 USING(organization_id,source_id) WHERE pp.organization_id=p_org AND pp.source_id=p_source
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
END $function$;

REVOKE ALL ON FUNCTION emailmonitor.results_fence(uuid,boolean,uuid,boolean,text) FROM PUBLIC;

CREATE FUNCTION emailmonitor.export_entitlement_fence(p_org uuid, p_export uuid, p_source text)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE conf jsonb; saved jsonb;
BEGIN
 IF NOT COALESCE(emailmonitor.human_work_tenant_allowed(p_org),false) AND NOT emailmonitor.service_scope_allowed(p_org,p_export,'export') THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 PERFORM emailmonitor.results_fence(p_org,true,NULL,true,p_source);
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
END $function$;

REVOKE ALL ON FUNCTION emailmonitor.export_entitlement_fence(uuid,uuid,text) FROM PUBLIC;

CREATE FUNCTION emailmonitor.privacy_source_allowed(p_org uuid, p_source text)
 RETURNS boolean
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
 SELECT COALESCE(emailmonitor.work_tenant_allowed(p_org),false) AND NOT EXISTS(SELECT 1 FROM emailmonitor.deletion_tombstones WHERE organization_id=p_org AND job_id IS NULL)
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.privacy_suppressions WHERE organization_id=p_org AND active AND kind='source'
 AND digest=emailmonitor.privacy_digest(p_org,'source',p_source))
$function$;

REVOKE ALL ON FUNCTION emailmonitor.privacy_source_allowed(uuid,text) FROM PUBLIC;

CREATE FUNCTION emailmonitor.privacy_source_state(p_org uuid, p_source text)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
 SELECT NOT EXISTS(SELECT 1 FROM emailmonitor.deletion_tombstones WHERE organization_id=p_org AND job_id IS NULL)
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.privacy_suppressions WHERE organization_id=p_org AND active AND kind='source'
 AND digest=emailmonitor.privacy_digest(p_org,'source',p_source))
$function$;

REVOKE ALL ON FUNCTION emailmonitor.privacy_source_state(uuid,text) FROM PUBLIC;

CREATE OR REPLACE FUNCTION emailmonitor.discovery_source_fence(p_org uuid, p_job uuid, p_version bigint)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
BEGIN
 -- Non-locking source lookup; the explicit form then takes the existing locks in order.
 PERFORM emailmonitor.discovery_source_fence(p_org,p_job,p_version,COALESCE((SELECT x.source_id FROM emailmonitor.discovery x WHERE x.organization_id=p_org AND x.job_id=p_job),'synthetic-publisher'));
END $function$;

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
 PERFORM emailmonitor.discovery_source_fence(NEW.organization_id,NEW.job_id,NEW.policy_version,NEW.source_id);
 IF NEW.source_id='europe-pmc' AND emailmonitor.registered_open_access_document('europe-pmc',NEW.plan->>'start_url') IS NULL
 THEN RAISE EXCEPTION 'DISCOVERY_POLICY_FENCE' USING ERRCODE='EM006'; END IF;
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
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.execution_read_fence(p_org uuid, p_job uuid)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE actor uuid; v_source text;
BEGIN
 IF NOT COALESCE(emailmonitor.execution_read_allowed(p_org,p_job),false) THEN
 RAISE EXCEPTION 'EXECUTION_SCOPE_DENIED' USING ERRCODE='EM010'; END IF;
 PERFORM emailmonitor.work_authority_fence(p_org);
 actor:=emailmonitor.work_actor(p_org);
 -- Non-locking: a discovery row's source is immutable.
 v_source:=COALESCE((SELECT x.source_id FROM emailmonitor.discovery x WHERE x.organization_id=p_org AND x.job_id=p_job),'synthetic-publisher');
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE;
 PERFORM 1 FROM emailmonitor.identities WHERE id=actor FOR SHARE;
 PERFORM 1 FROM emailmonitor.sessions WHERE token_hash=current_setting('emailmonitor.session_hash',true) FOR SHARE;
 PERFORM 1 FROM emailmonitor.memberships WHERE organization_id=p_org AND identity_id=actor FOR SHARE;
 PERFORM 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR SHARE;
 PERFORM 1 FROM emailmonitor.execution_runs WHERE organization_id=p_org AND job_id=p_job FOR SHARE;
 PERFORM 1 FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_catalog WHERE source_id=v_source FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policy_heads WHERE organization_id=p_org AND source_id=v_source FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policies p JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
 WHERE p.organization_id=p_org AND p.source_id=v_source AND p.version=h.current_version FOR SHARE OF p;
 IF NOT COALESCE(emailmonitor.execution_read_allowed(p_org,p_job),false) OR NOT emailmonitor.work_authority_current(p_org) THEN
 RAISE EXCEPTION 'EXECUTION_SCOPE_DENIED' USING ERRCODE='EM010'; END IF;
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.association_parent_fence(p_org uuid, p_job uuid, p_url text, p_revision bigint, p_write boolean DEFAULT false)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE o emailmonitor.organizations; j emailmonitor.jobs; a emailmonitor.article_observations;
 p emailmonitor.source_policies; h emailmonitor.source_policy_heads; s emailmonitor.source_catalog;
 session_row emailmonitor.sessions; identity_row emailmonitor.identities; v_source text;
BEGIN
 IF NOT COALESCE(emailmonitor.human_work_tenant_allowed(p_org),false) AND
 NOT emailmonitor.service_job_visible(p_org,p_job) THEN
 RAISE EXCEPTION 'ASSOCIATION_DENIED' USING ERRCODE='EM009'; END IF;
 PERFORM emailmonitor.work_authority_fence(p_org);
 -- Non-locking source lookup from the observation row; the locks below keep their order.
 v_source:=(SELECT x.source_id FROM emailmonitor.article_observations x WHERE x.organization_id=p_org AND x.job_id=p_job AND x.article_url=p_url);
 SELECT * INTO o FROM emailmonitor.organizations WHERE id=p_org FOR SHARE;
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR SHARE;
 SELECT * INTO s FROM emailmonitor.source_catalog WHERE source_id=v_source FOR SHARE;
 SELECT * INTO h FROM emailmonitor.source_policy_heads WHERE organization_id=p_org AND source_id=v_source FOR SHARE;
 SELECT * INTO p FROM emailmonitor.source_policies WHERE organization_id=p_org AND source_id=v_source AND version=h.current_version FOR SHARE;
 SELECT * INTO a FROM emailmonitor.article_observations WHERE organization_id=p_org AND job_id=p_job AND article_url=p_url FOR SHARE;
 IF o.status IS DISTINCT FROM 'active' OR j.id IS NULL OR a.article_url IS NULL
 OR j.kind<>'extraction' OR a.source_id IS DISTINCT FROM v_source
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
 -- The observation's source is its job's server-chosen source; Europe PMC rows are
 -- registered Open Access documents only.
 IF NEW.source_id IS DISTINCT FROM d.source_id OR (NEW.source_id='europe-pmc' AND oa IS NULL)
 THEN RAISE EXCEPTION 'ARTICLE_OBSERVATION_FENCE'; END IF;
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
 AND source_id=NEW.source_id AND version=NEW.policy_version;
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
 WHERE p.organization_id=NEW.organization_id AND p.source_id=NEW.source_id
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
 OR COALESCE(jsonb_typeof(NEW.observation->'license_category'),'')<>'string'
 OR NEW.observation->>'license_category' NOT IN ('cc0','cc-by','cc-by-sa','cc-by-nd','cc-by-nc','cc-by-nc-sa','cc-by-nc-nd','public-domain','other','unknown')
 OR (SELECT array_agg(k ORDER BY k COLLATE "C") FROM jsonb_object_keys(NEW.observation) k) IS DISTINCT FROM ARRAY['acquisition_digest','article_pmcid','authors','binding','candidates','canonical_url','content_digest','excerpts_retained','full_text_provider','identity_association_implemented','isolation_profile','keywords','license_category','license_url','parser_version','preferred_metadata','reasons','requested_identifier','route','schema_version','status','url']::text[]
 OR jsonb_path_exists(NEW.observation,'$.**.excerpt ? (@.type() != "string")')
 OR COALESCE(jsonb_typeof(NEW.observation->'keywords'),'')<>'array'
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.observation->'keywords') kw
  WHERE jsonb_typeof(kw)<>'string' OR length(kw#>>'{}')>300)
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
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.observation->'reasons') r WHERE r IS DISTINCT FROM '"authors_truncated"'::jsonb)
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.observation->'candidates') c
  WHERE COALESCE(jsonb_typeof(c->'author_positions'),'')<>'array'
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(c->'author_positions') pos
   WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.observation->'authors') au WHERE au->'position'=pos)))
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
 AND a.source_id=(SELECT x.source_id FROM emailmonitor.discovery x WHERE x.organization_id=p_org AND x.job_id=a.job_id)
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

CREATE OR REPLACE FUNCTION emailmonitor.result_contact_document(p_org uuid, p_batch uuid, p_association uuid)
 RETURNS jsonb
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
 SELECT jsonb_build_object('organization_id',a.organization_id,'job_id',b.job_id,'batch_id',a.batch_id,
 'association_id',a.id,'revision',a.revision,'candidate_id',a.candidate_id,'author_id',a.author_id,
 'author_name',au.display_name,'first_author',au.first_role,'corresponding_author',au.correspondence_role,
 'affiliations',COALESCE(au.record->'affiliations','[]'::jsonb),'raw_address',ca.raw_address,
 'normalized_address',ca.normalized_address,'state',a.state,'evidence_strength',a.record->'evidence_strength',
 'association_reason',a.record->'reason','evidence_ids',a.record->'evidence_ids','source_id',obs.source_id,
 'source_url',b.article_url,'policy_version',b.policy_version,'title',b.snapshot->'preferred_metadata'->'title',
 'observed_at',obs.observed_at,'syntax_status',ca.syntax_status,'identity_state','article_local_unresolved',
 'technical_status','not_checked','delivery_status','unverified','outreach_eligibility','not_assessed') || CASE WHEN obs.reused_from_job IS NOT NULL THEN jsonb_build_object('observation_origin','reused') ELSE '{}'::jsonb END
 || CASE WHEN obs.observation->>'route'='jats_xml' THEN jsonb_build_object('license_category',obs.observation->'license_category') ELSE '{}'::jsonb END
 FROM emailmonitor.author_email_associations a JOIN emailmonitor.association_batches b
 ON b.organization_id=a.organization_id AND b.id=a.batch_id JOIN emailmonitor.association_candidates ca
 ON ca.organization_id=a.organization_id AND ca.batch_id=a.batch_id AND ca.id=a.candidate_id
 LEFT JOIN emailmonitor.association_authors au ON au.organization_id=a.organization_id
 AND au.batch_id=a.batch_id AND au.id=a.author_id JOIN emailmonitor.article_observations obs
 ON obs.organization_id=b.organization_id AND obs.job_id=b.job_id AND obs.article_url=b.article_url
 WHERE a.organization_id=p_org AND a.batch_id=p_batch AND a.id=p_association
 AND a.state<>'suppressed' AND emailmonitor.association_visible(p_org,p_batch)
$function$;

CREATE OR REPLACE FUNCTION emailmonitor.results_fence(p_org uuid, p_export boolean DEFAULT false, p_requester uuid DEFAULT NULL::uuid, p_policy boolean DEFAULT true)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
BEGIN
 RETURN emailmonitor.results_fence(p_org,p_export,p_requester,p_policy,'synthetic-publisher');
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.result_filters_valid(p_filters jsonb)
 RETURNS boolean
 LANGUAGE sql
 IMMUTABLE
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
 SELECT COALESCE(jsonb_typeof(p_filters)='object'
 AND p_filters-'job_id'-'states'-'author_target'-'query'-'item_id'-'article_outcome_presence'-'paper_doi'-'source_id'='{}'::jsonb
 AND (NOT p_filters ? 'source_id' OR p_filters->'source_id'='null'::jsonb OR p_filters->'source_id' IN ('"synthetic-publisher"'::jsonb,'"europe-pmc"'::jsonb))
 AND (NOT p_filters ? 'paper_doi' OR p_filters->'paper_doi'='null'::jsonb OR (jsonb_typeof(p_filters->'paper_doi')='string' AND emailmonitor.normalized_paper_doi(p_filters->>'paper_doi')=p_filters->>'paper_doi'))
 AND p_filters ?& ARRAY['job_id','states','author_target','query']
 AND (p_filters->'job_id'='null'::jsonb OR (jsonb_typeof(p_filters->'job_id')='string'
 AND p_filters->>'job_id' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'))
 AND (NOT p_filters ? 'item_id' OR p_filters->'item_id'='null'::jsonb OR (
 jsonb_typeof(p_filters->'item_id')='string' AND p_filters->>'job_id' IS NOT NULL
 AND p_filters->>'item_id' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'))
 AND (NOT p_filters ? 'article_outcome_presence' OR p_filters->>'article_outcome_presence'
 IN ('all','observed_candidate','completed_without_candidate','unresolved'))
 AND jsonb_typeof(p_filters->'states')='array' AND jsonb_array_length(p_filters->'states') BETWEEN 1 AND 4
 AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(p_filters->'states') x
 WHERE x NOT IN ('accepted','needs_review','unmatched','rejected'))
 AND jsonb_array_length(p_filters->'states')=(SELECT count(DISTINCT x)
 FROM jsonb_array_elements_text(p_filters->'states') x)
 AND p_filters->>'author_target' IN ('all','first','corresponding')
 AND jsonb_typeof(p_filters->'query')='string' AND length(p_filters->>'query')<=100
 AND p_filters->>'query' !~ '[[:cntrl:]]',false)
$function$;

CREATE OR REPLACE FUNCTION emailmonitor.result_contacts(p_org uuid, p_filters jsonb, p_after_batch uuid DEFAULT NULL::uuid, p_after_association uuid DEFAULT NULL::uuid, p_limit integer DEFAULT 51)
 RETURNS SETOF jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE item record; selected_batch uuid;
BEGIN
 PERFORM emailmonitor.results_fence(p_org,false,NULL,true,emailmonitor.result_source(p_filters));
 IF NOT COALESCE(emailmonitor.result_filters_valid(p_filters),false) OR p_limit IS NULL
 OR p_limit NOT BETWEEN 1 AND 2001 OR (p_after_batch IS NULL)<>(p_after_association IS NULL)
 THEN RAISE EXCEPTION 'RESULT_FILTERS_INVALID'; END IF;
 IF p_filters->>'job_id' IS NOT NULL THEN
 PERFORM emailmonitor.execution_read_fence(p_org,(p_filters->>'job_id')::uuid); END IF;
 PERFORM emailmonitor.retained_article_selection_fence(p_org,p_filters);
 IF p_filters->>'item_id' IS NOT NULL THEN
 selected_batch:=(emailmonitor.retained_article_binding(p_org,(p_filters->>'job_id')::uuid,
 (p_filters->>'item_id')::uuid,NULL,false)->>'batch_id')::uuid;
 END IF;
 FOR item IN SELECT a.batch_id,a.id FROM emailmonitor.author_email_associations a
 JOIN emailmonitor.association_batches b ON b.organization_id=a.organization_id AND b.id=a.batch_id
 LEFT JOIN emailmonitor.association_authors au ON au.organization_id=a.organization_id
 AND au.batch_id=a.batch_id AND au.id=a.author_id JOIN emailmonitor.association_candidates ca
 ON ca.organization_id=a.organization_id AND ca.batch_id=a.batch_id AND ca.id=a.candidate_id
 WHERE a.organization_id=p_org AND emailmonitor.association_visible(p_org,a.batch_id)
 AND EXISTS(SELECT 1 FROM emailmonitor.article_observations o WHERE o.organization_id=p_org AND o.job_id=b.job_id AND o.article_url=b.article_url AND o.source_id=emailmonitor.result_source(p_filters))
 AND a.state<>'suppressed' AND p_filters->'states' ? a.state
 AND (p_filters->>'job_id' IS NULL OR b.job_id=(p_filters->>'job_id')::uuid OR EXISTS(
 SELECT 1 FROM emailmonitor.execution_items i WHERE i.organization_id=p_org
 AND i.job_id=(p_filters->>'job_id')::uuid AND i.batch_id=a.batch_id))
 AND (p_filters->>'item_id' IS NULL OR a.batch_id=selected_batch)
 AND (p_filters->>'paper_doi' IS NULL OR emailmonitor.retained_paper_batch_matches(p_org,a.batch_id,p_filters->>'paper_doi'))
 AND (p_filters->>'author_target'='all' OR (p_filters->>'author_target'='first' AND au.first_role)
 OR (p_filters->>'author_target'='corresponding' AND au.correspondence_role))
 AND (p_filters->>'query'='' OR strpos(lower(COALESCE(au.display_name,'')),lower(p_filters->>'query'))>0
 OR strpos(lower(ca.raw_address),lower(p_filters->>'query'))>0
 OR strpos(lower(COALESCE(b.snapshot->'preferred_metadata'->>'title','')),lower(p_filters->>'query'))>0)
 AND (p_after_batch IS NULL OR (a.batch_id,a.id)>(p_after_batch,p_after_association))
 ORDER BY a.batch_id,a.id LIMIT p_limit LOOP
 PERFORM emailmonitor.lock_association_batch(p_org,item.batch_id);
 PERFORM 1 FROM emailmonitor.author_email_associations WHERE organization_id=p_org AND batch_id=item.batch_id AND id=item.id FOR SHARE NOWAIT;
 IF EXISTS(SELECT 1 FROM emailmonitor.author_email_associations a WHERE a.organization_id=p_org
 AND a.batch_id=item.batch_id AND a.id=item.id AND a.state<>'suppressed' AND p_filters->'states' ? a.state)
 AND EXISTS(SELECT 1 FROM emailmonitor.association_batches b JOIN emailmonitor.article_observations o ON o.organization_id=b.organization_id AND o.job_id=b.job_id AND o.article_url=b.article_url WHERE b.organization_id=p_org AND b.id=item.batch_id AND o.source_id=emailmonitor.result_source(p_filters))
 AND (p_filters->>'paper_doi' IS NULL OR emailmonitor.retained_paper_batch_matches(p_org,item.batch_id,p_filters->>'paper_doi'))
 THEN RETURN NEXT emailmonitor.result_contact_document(p_org,item.batch_id,item.id); END IF;
 END LOOP;
 IF p_filters->>'item_id' IS NOT NULL AND (emailmonitor.retained_article_binding(p_org,
 (p_filters->>'job_id')::uuid,(p_filters->>'item_id')::uuid,NULL,false)->>'batch_id')::uuid
 IS DISTINCT FROM selected_batch THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 PERFORM emailmonitor.results_fence(p_org,false,NULL,true,emailmonitor.result_source(p_filters));
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.result_outcomes_filtered(p_org uuid, p_filters jsonb, p_after_job uuid, p_after_item uuid, p_limit integer)
 RETURNS SETOF jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE item record; presence text:=COALESCE(p_filters->>'article_outcome_presence','all');
BEGIN
 PERFORM emailmonitor.results_fence(p_org,false,NULL,true,emailmonitor.result_source(p_filters));
 IF NOT COALESCE(emailmonitor.result_filters_valid(p_filters),false) OR p_limit IS NULL
 OR p_limit NOT BETWEEN 1 AND 2001 OR (p_after_job IS NULL)<>(p_after_item IS NULL)
 THEN RAISE EXCEPTION 'RESULT_FILTERS_INVALID'; END IF;
 IF p_filters->>'job_id' IS NOT NULL THEN PERFORM emailmonitor.execution_read_fence(p_org,(p_filters->>'job_id')::uuid); END IF;
 PERFORM emailmonitor.retained_article_selection_fence(p_org,p_filters);
 IF p_filters->>'source_id' IS NULL AND p_filters->>'item_id' IS NULL AND presence='all' AND p_filters->>'paper_doi' IS NULL THEN
 RETURN QUERY SELECT * FROM emailmonitor.result_outcomes(p_org,(p_filters->>'job_id')::uuid,p_after_job,p_after_item,p_limit);
 RETURN;
 END IF;
 FOR item IN SELECT i.job_id,i.id FROM emailmonitor.execution_items i
 WHERE i.organization_id=p_org AND i.work_kind='article'
 AND (p_filters->>'job_id' IS NULL OR i.job_id=(p_filters->>'job_id')::uuid)
 AND (p_filters->>'item_id' IS NULL OR i.id=(p_filters->>'item_id')::uuid)
 AND emailmonitor.execution_read_allowed(p_org,i.job_id)
 AND EXISTS(SELECT 1 FROM emailmonitor.discovery j WHERE j.organization_id=p_org AND j.job_id=i.job_id AND j.source_id=emailmonitor.result_source(p_filters))
 AND (p_filters->>'paper_doi' IS NULL OR emailmonitor.retained_paper_item_matches(p_org,i.job_id,i.id,p_filters->>'paper_doi'))
 AND (presence='all' OR emailmonitor.retained_article_binding(p_org,i.job_id,i.id,NULL,false)->>'presence'=presence)
 AND (p_after_job IS NULL OR (i.job_id,i.id)>(p_after_job,p_after_item))
 ORDER BY i.job_id,i.id LIMIT p_limit LOOP
 PERFORM emailmonitor.execution_read_fence(p_org,item.job_id);
 PERFORM 1 FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=item.job_id AND id=item.id FOR SHARE NOWAIT;
 IF (presence='all' OR emailmonitor.retained_article_binding(p_org,item.job_id,item.id,NULL,false)->>'presence'=presence)
 AND EXISTS(SELECT 1 FROM emailmonitor.discovery j WHERE j.organization_id=p_org AND j.job_id=item.job_id AND j.source_id=emailmonitor.result_source(p_filters))
 AND (p_filters->>'paper_doi' IS NULL OR emailmonitor.retained_paper_item_matches(p_org,item.job_id,item.id,p_filters->>'paper_doi')) THEN
 RETURN NEXT emailmonitor.result_outcome_document(p_org,item.job_id,item.id);
 END IF;
 END LOOP;
 PERFORM emailmonitor.results_fence(p_org,false,NULL,true,emailmonitor.result_source(p_filters));
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.result_outcomes(p_org uuid, p_job uuid DEFAULT NULL::uuid, p_after_job uuid DEFAULT NULL::uuid, p_after_item uuid DEFAULT NULL::uuid, p_limit integer DEFAULT 51)
 RETURNS SETOF jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE item record;
BEGIN
 PERFORM emailmonitor.results_fence(p_org);
 IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 2001 OR (p_after_job IS NULL)<>(p_after_item IS NULL)
 THEN RAISE EXCEPTION 'RESULT_FILTERS_INVALID'; END IF;
 IF p_job IS NOT NULL THEN PERFORM emailmonitor.execution_read_fence(p_org,p_job); END IF;
 FOR item IN SELECT i.job_id,i.id FROM emailmonitor.execution_items i
 WHERE i.organization_id=p_org AND i.work_kind='article' AND (p_job IS NULL OR i.job_id=p_job)
 AND emailmonitor.execution_read_allowed(p_org,i.job_id)
 AND EXISTS(SELECT 1 FROM emailmonitor.discovery d WHERE d.organization_id=p_org AND d.job_id=i.job_id AND d.source_id='synthetic-publisher')
 AND (p_after_job IS NULL OR (i.job_id,i.id)>(p_after_job,p_after_item))
 ORDER BY i.job_id,i.id LIMIT p_limit LOOP
 PERFORM emailmonitor.execution_read_fence(p_org,item.job_id);
 PERFORM 1 FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=item.job_id AND id=item.id FOR SHARE NOWAIT;
 RETURN NEXT emailmonitor.result_outcome_document(p_org,item.job_id,item.id);
 END LOOP;
 PERFORM emailmonitor.results_fence(p_org);
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.result_contact(p_org uuid, p_batch uuid, p_association uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE document jsonb; v_source text:=COALESCE((SELECT o.source_id FROM emailmonitor.association_batches bb JOIN emailmonitor.article_observations o ON o.organization_id=bb.organization_id AND o.job_id=bb.job_id AND o.article_url=bb.article_url WHERE bb.organization_id=p_org AND bb.id=p_batch),'synthetic-publisher');
BEGIN
 PERFORM emailmonitor.results_fence(p_org,false,NULL,true,v_source);
 PERFORM emailmonitor.lock_association_batch(p_org,p_batch);
 PERFORM 1 FROM emailmonitor.author_email_associations WHERE organization_id=p_org
 AND batch_id=p_batch AND id=p_association FOR SHARE NOWAIT;
 document:=emailmonitor.result_contact_document(p_org,p_batch,p_association);
 IF document IS NULL THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 PERFORM emailmonitor.results_fence(p_org,false,NULL,true,v_source);
 RETURN document;
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.result_evidence(p_org uuid, p_batch uuid, p_evidence uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE document jsonb; v_source text:=COALESCE((SELECT o.source_id FROM emailmonitor.association_batches bb JOIN emailmonitor.article_observations o ON o.organization_id=bb.organization_id AND o.job_id=bb.job_id AND o.article_url=bb.article_url WHERE bb.organization_id=p_org AND bb.id=p_batch),'synthetic-publisher');
BEGIN
 PERFORM emailmonitor.results_fence(p_org,false,NULL,true,v_source);
 PERFORM emailmonitor.lock_association_batch(p_org,p_batch);
 PERFORM 1 FROM emailmonitor.author_email_associations a JOIN emailmonitor.association_evidence_links link
 ON link.organization_id=a.organization_id AND link.batch_id=a.batch_id AND link.association_id=a.id
 WHERE link.organization_id=p_org AND link.batch_id=p_batch AND link.evidence_id=p_evidence
 ORDER BY a.id FOR SHARE OF a NOWAIT;
 SELECT jsonb_build_object('organization_id',b.organization_id,'batch_id',b.id,
 'source_url',b.article_url,'content_digest',b.snapshot->'content_digest','citation',e.record,
 'synthetic',true,'raw_document_available',false) INTO document
 FROM emailmonitor.association_batches b JOIN emailmonitor.association_evidence e
 ON e.organization_id=b.organization_id AND e.batch_id=b.id WHERE b.organization_id=p_org
 AND b.id=p_batch AND e.id=p_evidence AND emailmonitor.association_visible(p_org,p_batch)
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.association_evidence_links link
 JOIN emailmonitor.author_email_associations a ON a.organization_id=link.organization_id
 AND a.batch_id=link.batch_id AND a.id=link.association_id WHERE link.organization_id=p_org
 AND link.batch_id=p_batch AND link.evidence_id=p_evidence AND a.state='suppressed');
 IF document IS NULL THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 PERFORM emailmonitor.results_fence(p_org,false,NULL,true,v_source);
 RETURN document;
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.export_entitlement_fence(p_org uuid, p_export uuid DEFAULT NULL::uuid)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
BEGIN
 RETURN emailmonitor.export_entitlement_fence(p_org,p_export,emailmonitor.export_source(p_org,p_export));
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.exports_create(p_org uuid, p_id uuid, p_key text, p_request jsonb, p_event uuid)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE selected uuid;
BEGIN
 PERFORM emailmonitor.export_entitlement_fence(p_org,NULL,emailmonitor.result_source(p_request));
 selected:=emailmonitor.exports_create_pre_entitlement(p_org,p_id,p_key,p_request,p_event);
 INSERT INTO emailmonitor.export_entitlements SELECT p_org,selected,revision,configuration->'entitlements'
 FROM emailmonitor.tenant_configuration WHERE organization_id=p_org ON CONFLICT DO NOTHING;
 RETURN selected;
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.exports_preview(p_org uuid, p_request jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
BEGIN
 PERFORM emailmonitor.export_entitlement_fence(p_org,NULL,emailmonitor.result_source(p_request));
 RETURN emailmonitor.exports_preview_pre_entitlement(p_org,p_request);
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.export_lock(p_org uuid, p_export uuid)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE item record; requester uuid;
BEGIN
 IF NOT emailmonitor.work_export_allowed(p_org,p_export) THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 SELECT requested_by INTO requester FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export;
 PERFORM emailmonitor.results_fence(p_org,true,requester,true,emailmonitor.export_source(p_org,p_export));
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
 PERFORM emailmonitor.retained_export_article_lock(p_org,p_export);
 IF NOT emailmonitor.export_valid(p_org,p_export) THEN
 RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.exports_claim(p_org uuid, p_export uuid, p_event uuid, p_generation bigint, p_nonce uuid, p_seconds integer)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE e emailmonitor.exports;
BEGIN
 IF NOT emailmonitor.work_export_allowed(p_org,p_export) THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 PERFORM emailmonitor.results_fence(p_org,true,NULL,true,emailmonitor.export_source(p_org,p_export));
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
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.exports_claim_pre_admission(p_org uuid, p_export uuid, p_event uuid, p_generation bigint, p_nonce uuid, p_seconds integer)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE e emailmonitor.exports;
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true,NULL,true,emailmonitor.export_source(p_org,p_export));
 IF p_seconds IS NULL OR p_seconds NOT BETWEEN 1 AND 120 THEN RAISE EXCEPTION 'EXPORT_LEASE_INVALID'; END IF;
 SELECT * INTO e FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export FOR UPDATE NOWAIT;
 IF e.id IS NULL OR e.generation IS DISTINCT FROM p_generation OR NOT EXISTS(SELECT 1 FROM emailmonitor.export_outbox
 WHERE organization_id=p_org AND export_id=p_export AND event_id=p_event AND generation=p_generation)
 THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 UPDATE emailmonitor.export_outbox SET deliveries=deliveries+1 WHERE organization_id=p_org AND export_id=p_export;
 IF e.state NOT IN ('queued','running') OR (e.state='running' AND e.lease_until>clock_timestamp()) OR e.attempts>=3 THEN RETURN NULL; END IF;
 PERFORM emailmonitor.export_lock(p_org,p_export);
 UPDATE emailmonitor.exports SET state='running',reason='rendering',attempts=attempts+1,
 revision=revision+1,lease_nonce=p_nonce,lease_until=least(expires_at,clock_timestamp()+make_interval(secs=>p_seconds))
 WHERE organization_id=p_org AND id=p_export;
 RETURN e.snapshot;
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.exports_confirmed(p_org uuid, p_export uuid, p_event uuid)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true,NULL,true,emailmonitor.export_source(p_org,p_export));
 PERFORM emailmonitor.export_lock(p_org,p_export);
 UPDATE emailmonitor.export_outbox SET published_at=clock_timestamp() WHERE organization_id=p_org AND export_id=p_export
 AND event_id=p_event AND generation=(SELECT generation FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export);
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.exports_download_pre_entitlement(p_org uuid, p_export uuid)
 RETURNS TABLE(body bytea, mime text, extension text, digest text)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true,NULL,true,emailmonitor.export_source(p_org,p_export));
 PERFORM 1 FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export FOR SHARE NOWAIT;
 PERFORM emailmonitor.export_lock(p_org,p_export);
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export AND state='ready')
 THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 RETURN QUERY SELECT a.body,a.mime,a.extension,a.digest FROM emailmonitor.export_artifacts a
 JOIN emailmonitor.export_effects f ON f.organization_id=a.organization_id AND f.export_id=a.export_id AND f.digest=a.digest
 WHERE a.organization_id=p_org AND a.export_id=p_export AND a.digest=encode(sha256(a.body),'hex');
 IF NOT FOUND THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 PERFORM emailmonitor.export_lock(p_org,p_export);
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.exports_finish(p_org uuid, p_export uuid, p_generation bigint, p_nonce uuid, p_body bytea, p_mime text, p_extension text)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE cap integer;
BEGIN
 IF NOT emailmonitor.work_export_allowed(p_org,p_export) THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 PERFORM emailmonitor.results_fence(p_org,true,NULL,true,emailmonitor.export_source(p_org,p_export));
 PERFORM 1 FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export FOR UPDATE NOWAIT;
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 cap:=emailmonitor.export_entitlement_fence(p_org,p_export);
 IF p_body IS NULL OR octet_length(p_body)>cap THEN RAISE EXCEPTION 'EXPORT_ENTITLEMENT_DENIED' USING ERRCODE='EM013'; END IF;
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.admission_requests WHERE organization_id=p_org AND reference_id=p_export
 AND pool='export' AND state='active' AND generation=p_generation AND nonce=p_nonce AND lease_until>clock_timestamp()
 AND emailmonitor.work_ticket_owned(p_org,actor_id,session_hash,service_delegation)) THEN RETURN false; END IF;
 RETURN emailmonitor.exports_finish_pre_entitlement(p_org,p_export,p_generation,p_nonce,p_body,p_mime,p_extension);
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.exports_finish_pre_entitlement(p_org uuid, p_export uuid, p_generation bigint, p_nonce uuid, p_body bytea, p_mime text, p_extension text)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE e emailmonitor.exports; hash text; mime text; extension text;
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true,NULL,true,emailmonitor.export_source(p_org,p_export));
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
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.exports_preview_pre_entitlement(p_org uuid, p_request jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE filters jsonb; contacts integer; outcomes integer:=0;
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true,NULL,true,emailmonitor.result_source(p_request));
 PERFORM emailmonitor.export_request_validate(p_request);
 filters:=emailmonitor.retained_export_filters(p_request);
 SELECT count(*) INTO contacts FROM emailmonitor.result_contacts(p_org,filters,NULL,NULL,2001);
 IF (p_request->>'include_article_outcomes')::boolean THEN
 SELECT count(*) INTO outcomes FROM emailmonitor.result_outcomes_filtered(p_org,filters,NULL,NULL,2001);
 END IF;
 IF contacts>2000 OR outcomes>2000 THEN RAISE EXCEPTION 'EXPORT_REFINE_FILTERS'; END IF;
 RETURN jsonb_build_object('organization_id',p_org,'contacts',contacts,'article_outcomes',outcomes,
 'optional_contact_fields',COALESCE(p_request->'optional_contact_fields','["affiliations","article_title"]'::jsonb),
 'counts_may_change',true,'excluded_reasons',CASE WHEN (p_request->>'include_unresolved')::boolean
 THEN '["rejected_and_suppressed_excluded","unavailable_records_not_disclosed"]'::jsonb
 ELSE '["unaccepted_excluded_by_default","rejected_and_suppressed_excluded","unavailable_records_not_disclosed"]'::jsonb END);
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.exports_create_pre_entitlement(p_org uuid, p_id uuid, p_key text, p_request jsonb, p_event uuid)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE actor uuid; cached emailmonitor.export_requests; filters jsonb; contacts jsonb; outcomes jsonb;
 stamp timestamptz:=clock_timestamp(); expiry timestamptz; policy bigint; doc jsonb; item jsonb; bindings jsonb:='[]'; binding jsonb;
BEGIN
 actor:=emailmonitor.results_fence(p_org,true,NULL,true,emailmonitor.result_source(p_request));
 IF p_key IS NULL OR p_key!~'^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'EXPORT_REQUEST_INVALID'; END IF;
 PERFORM emailmonitor.export_request_validate(p_request);
 IF p_request->>'source_id' IS NULL THEN p_request:=p_request-'source_id'; END IF;
 IF p_request->>'paper_doi' IS NULL THEN p_request:=p_request-'paper_doi'; END IF;
 IF p_request->>'item_id' IS NULL THEN p_request:=p_request-'item_id'; END IF;
 IF COALESCE(p_request->>'article_outcome_presence','all')='all' THEN p_request:=p_request-'article_outcome_presence'; END IF;
 INSERT INTO emailmonitor.export_requests VALUES(p_org,actor,p_key,p_request,NULL,stamp+interval '24 hours') ON CONFLICT DO NOTHING;
 SELECT * INTO cached FROM emailmonitor.export_requests WHERE organization_id=p_org AND actor_id=actor AND key_hash=p_key FOR UPDATE;
 IF cached.expires_at>stamp THEN
 IF cached.request||jsonb_build_object('optional_contact_fields',COALESCE(cached.request->'optional_contact_fields','["affiliations","article_title"]'::jsonb))
 <>p_request||jsonb_build_object('optional_contact_fields',COALESCE(p_request->'optional_contact_fields','["affiliations","article_title"]'::jsonb)) THEN RAISE EXCEPTION 'EXPORT_KEY_CONFLICT' USING ERRCODE='EM409'; END IF;
 IF cached.export_id IS NOT NULL THEN RETURN cached.export_id; END IF;
 ELSE UPDATE emailmonitor.export_requests SET request=p_request,export_id=NULL,expires_at=stamp+interval '24 hours'
 WHERE organization_id=p_org AND actor_id=actor AND key_hash=p_key; END IF;
 filters:=emailmonitor.retained_export_filters(p_request);
 SELECT COALESCE(jsonb_agg(document),'[]'::jsonb) INTO contacts FROM emailmonitor.result_contacts(p_org,filters,NULL,NULL,2001) AS rows(document);
 IF jsonb_array_length(contacts)>2000 THEN RAISE EXCEPTION 'EXPORT_REFINE_FILTERS'; END IF;
 outcomes:='[]'::jsonb;
 IF (p_request->>'include_article_outcomes')::boolean THEN
 SELECT COALESCE(jsonb_agg(document),'[]'::jsonb) INTO outcomes FROM emailmonitor.result_outcomes_filtered(p_org,filters,NULL,NULL,2001) AS rows(document);
 IF jsonb_array_length(outcomes)>2000 THEN RAISE EXCEPTION 'EXPORT_REFINE_FILTERS'; END IF;
 END IF;
 SELECT pp.version,least(pp.valid_until,stamp+make_interval(secs=>(p_request->>'ttl_seconds')::integer))
 INTO policy,expiry FROM emailmonitor.source_policies pp JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
 WHERE pp.organization_id=p_org AND pp.source_id=emailmonitor.result_source(p_request) AND pp.version=h.current_version;
 SELECT least(expiry,COALESCE(min(b.expires_at),expiry)) INTO expiry FROM emailmonitor.association_batches b
 WHERE b.organization_id=p_org AND b.id IN(SELECT (x->>'batch_id')::uuid FROM jsonb_array_elements(contacts) x);
 SELECT least(expiry,COALESCE(min(r.expires_at),expiry)) INTO expiry FROM emailmonitor.execution_runs r
 WHERE r.organization_id=p_org AND r.job_id IN(SELECT (x->>'job_id')::uuid FROM jsonb_array_elements(outcomes) x);
 -- Capture exact child authority even when the Contact keeps its original job provenance.
 IF filters->>'paper_doi' IS NOT NULL OR filters->>'item_id' IS NOT NULL OR COALESCE(filters->>'article_outcome_presence','all')<>'all' THEN
 FOR item IN SELECT DISTINCT jsonb_build_object('job_id',x->'job_id','item_id',x->'item_id') FROM (
 SELECT value x FROM jsonb_array_elements(outcomes)
 UNION ALL SELECT jsonb_build_object('job_id',filters->'job_id','item_id',filters->'item_id') WHERE filters->>'item_id' IS NOT NULL) chosen LOOP
 binding:=emailmonitor.retained_article_binding(p_org,(item->>'job_id')::uuid,(item->>'item_id')::uuid);
 IF binding IS NULL THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 bindings:=bindings||jsonb_build_array(binding-ARRAY['presence','batch_id','expires_at']);
 expiry:=least(expiry,(binding->>'expires_at')::timestamptz);
 END LOOP;
 END IF;
 doc:=jsonb_build_object('schema_version','1.0','organization_id',p_org,'export_id',p_id,'requested_by',actor,
 'purpose',p_request->'purpose','filters',filters,'format',p_request->'format',
 'include_article_outcomes',p_request->'include_article_outcomes',
 'optional_contact_fields',COALESCE(p_request->'optional_contact_fields','["affiliations","article_title"]'::jsonb),'contacts',contacts,'article_outcomes',outcomes,
 'created_at',stamp,'expires_at',expiry,'synthetic',true,'technical_checks_performed',false,'outreach_approved',false);
 IF filters->>'paper_doi' IS NOT NULL OR filters->>'item_id' IS NOT NULL OR COALESCE(filters->>'article_outcome_presence','all')<>'all' THEN
 doc:=doc||jsonb_build_object('article_filter_bindings',bindings); END IF;
 INSERT INTO emailmonitor.exports(organization_id,id,requested_by,request,snapshot,state,reason,deletion_generation,policy_version,created_at,expires_at)
 SELECT p_org,p_id,actor,p_request,doc,'queued','scheduled',deletion_generation,policy,stamp,expiry FROM emailmonitor.organizations WHERE id=p_org;
 FOR item IN SELECT value FROM jsonb_array_elements(contacts) LOOP
 INSERT INTO emailmonitor.export_members VALUES(p_org,p_id,(item->>'batch_id')::uuid,(item->>'association_id')::uuid,(item->>'revision')::bigint);
 END LOOP;
 FOR item IN SELECT value FROM jsonb_array_elements(outcomes) LOOP
 INSERT INTO emailmonitor.export_outcomes SELECT p_org,p_id,(item->>'job_id')::uuid,(item->>'item_id')::uuid,row_version,item
 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=(item->>'job_id')::uuid;
 END LOOP;
 INSERT INTO emailmonitor.export_outbox(organization_id,export_id,event_id,generation) VALUES(p_org,p_id,p_event,1);
 INSERT INTO emailmonitor.export_events(organization_id,export_id,event_id,event_type) VALUES(p_org,p_id,p_event,'export.requested');
 UPDATE emailmonitor.export_requests SET export_id=p_id WHERE organization_id=p_org AND actor_id=actor AND key_hash=p_key;
 INSERT INTO emailmonitor.audit_events VALUES(p_org,p_event,actor,'export.requested',p_id,stamp);
 PERFORM emailmonitor.export_lock(p_org,p_id);
 RETURN p_id;
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.export_valid(p_org uuid, p_export uuid)
 RETURNS boolean
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
 SELECT emailmonitor.retained_export_article_valid(p_org,p_export) AND emailmonitor.privacy_source_allowed(p_org) AND emailmonitor.privacy_source_allowed(p_org,emailmonitor.export_source(p_org,p_export)) AND NOT EXISTS(SELECT 1 FROM emailmonitor.exports ee JOIN emailmonitor.lifecycle_configuration cc ON cc.organization_id=ee.organization_id WHERE ee.organization_id=p_org AND ee.id=p_export AND ee.created_at+make_interval(hours=>(cc.retention->>'export_hours')::integer)<=clock_timestamp()) AND COALESCE(EXISTS(SELECT 1 FROM emailmonitor.exports e JOIN emailmonitor.organizations o
 ON o.id=e.organization_id JOIN emailmonitor.memberships m ON m.organization_id=e.organization_id
 AND m.identity_id=e.requested_by JOIN emailmonitor.identities ii ON ii.id=m.identity_id
 JOIN emailmonitor.source_policy_heads h ON h.organization_id=e.organization_id AND h.source_id=emailmonitor.result_source(e.request)
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
$function$;

CREATE OR REPLACE FUNCTION emailmonitor.publication_export_state(p_org uuid, p_export uuid)
 RETURNS boolean
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
 SELECT emailmonitor.privacy_source_state(p_org) AND emailmonitor.privacy_source_state(p_org,emailmonitor.export_source(p_org,p_export)) AND NOT EXISTS(SELECT 1 FROM emailmonitor.exports ee JOIN emailmonitor.lifecycle_configuration cc ON cc.organization_id=ee.organization_id WHERE ee.organization_id=p_org AND ee.id=p_export AND ee.created_at+make_interval(hours=>(cc.retention->>'export_hours')::integer)<=clock_timestamp()) AND COALESCE(EXISTS(SELECT 1 FROM emailmonitor.exports e JOIN emailmonitor.organizations o
 ON o.id=e.organization_id JOIN emailmonitor.memberships m ON m.organization_id=e.organization_id
 AND m.identity_id=e.requested_by JOIN emailmonitor.identities ii ON ii.id=m.identity_id
 JOIN emailmonitor.source_policy_heads h ON h.organization_id=e.organization_id AND h.source_id=emailmonitor.result_source(e.request)
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
$function$;

CREATE OR REPLACE FUNCTION emailmonitor.privacy_canonical_allowed(p_kind text, p_value text)
 RETURNS boolean
 LANGUAGE plpgsql
 IMMUTABLE
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE domain_pattern text:='[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+';
 local_pattern text:=$pattern$[a-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*$pattern$;
BEGIN
 IF p_kind IS NULL OR p_value IS NULL OR length(p_value) NOT BETWEEN 1 AND 254 OR octet_length(p_value)<>length(p_value) THEN RETURN false; END IF;
 IF p_kind='source' THEN RETURN lower(p_value) IN ('synthetic-publisher','europe-pmc'); END IF;
 IF p_kind='domain' THEN RETURN lower(p_value) ~ ('^'||domain_pattern||'$'); END IF;
 IF p_kind='contact' THEN RETURN length(split_part(p_value,'@',1))<=64 AND lower(p_value) ~ ('^'||local_pattern||'@'||domain_pattern||'$'); END IF;
 RETURN false;
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.lifecycle_suppress(p_org uuid, p_id uuid, p_kind text, p_value text, p_reason text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
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
 ((p_kind='source' AND (lower(p_value)='synthetic-publisher' OR EXISTS(SELECT 1 FROM emailmonitor.discovery x WHERE x.organization_id=p_org AND x.job_id=j.id AND x.source_id=lower(p_value)))) OR (p_kind<>'source' AND EXISTS(SELECT 1 FROM emailmonitor.article_observations a WHERE a.organization_id=p_org AND a.job_id=j.id
 AND NOT emailmonitor.privacy_payload_allowed(p_org,a.observation)))) ORDER BY j.id LOOP
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.deletion_tombstones WHERE organization_id=p_org AND job_id=item.id) THEN
 INSERT INTO emailmonitor.deletion_tombstones(organization_id,id,job_id,reason) VALUES(p_org,gen_random_uuid(),item.id,'privacy_request');
 PERFORM emailmonitor.lifecycle_fence_job(p_org,item.id); END IF;
 END LOOP;
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,gen_random_uuid(),emailmonitor.job_actor(),'privacy.suppressed',found_id);
 RETURN emailmonitor.lifecycle_suppression_document(p_org,found_id);
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.privacy_job_allowed(p_org uuid, p_job uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
 SELECT emailmonitor.privacy_source_allowed(p_org) AND emailmonitor.privacy_source_allowed(p_org,COALESCE((SELECT x.source_id FROM emailmonitor.discovery x WHERE x.organization_id=p_org AND x.job_id=p_job),'synthetic-publisher')) AND NOT EXISTS(SELECT 1 FROM emailmonitor.lifecycle_job_deadlines d WHERE d.organization_id=p_org AND d.job_id=p_job
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
 AND emailmonitor.retained_reuse_current(p_org,p_job)
$function$;

CREATE OR REPLACE FUNCTION emailmonitor.privacy_job_state(p_org uuid, p_job uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
 SELECT emailmonitor.privacy_source_state(p_org) AND emailmonitor.privacy_source_state(p_org,COALESCE((SELECT x.source_id FROM emailmonitor.discovery x WHERE x.organization_id=p_org AND x.job_id=p_job),'synthetic-publisher')) AND NOT EXISTS(SELECT 1 FROM emailmonitor.lifecycle_job_deadlines d WHERE d.organization_id=p_org AND d.job_id=p_job
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
 AND emailmonitor.retained_reuse_current(p_org,p_job)
$function$;

CREATE OR REPLACE FUNCTION emailmonitor.execution_start(p_org uuid, p_job uuid, p_revision bigint, p_event uuid)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE j emailmonitor.jobs; d emailmonitor.discovery; days integer;
BEGIN
 PERFORM emailmonitor.execution_control_fence(p_org,p_job);
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 SELECT * INTO d FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job;
 IF p_revision IS NULL OR j.row_version<>p_revision THEN RAISE EXCEPTION 'EXECUTION_REVISION' USING ERRCODE='EM409'; END IF;
 IF j.state<>'draft' OR EXISTS(SELECT 1 FROM emailmonitor.execution_runs WHERE organization_id=p_org AND job_id=p_job)
 OR d.generation<>j.generation OR d.checkpoint->>'status' NOT IN ('pending','completed','partial')
 THEN RAISE EXCEPTION 'EXECUTION_START_DENIED' USING ERRCODE='EM010'; END IF;
 IF j.request ? 'reuse' AND NOT EXISTS(
 SELECT 1 FROM emailmonitor.article_observations a WHERE a.organization_id=p_org AND a.job_id=p_job
 AND a.article_url=j.request->'input'->>'url' AND a.reused_from_job IS NOT NULL
 AND emailmonitor.retained_reuse_current(p_org,p_job)) THEN
 RAISE EXCEPTION 'EXECUTION_START_DENIED' USING ERRCODE='EM010'; END IF;
 SELECT (policy->'retention'->>'contact_days')::integer INTO days FROM emailmonitor.source_policies
 WHERE organization_id=p_org AND source_id=d.source_id AND version=d.policy_version;
 INSERT INTO emailmonitor.execution_runs(organization_id,job_id,root_job_id,source_id,policy_version,deletion_generation,expires_at)
 VALUES(p_org,p_job,p_job,d.source_id,d.policy_version,d.deletion_generation,clock_timestamp()+make_interval(days=>days));
 UPDATE emailmonitor.jobs SET state='ready' WHERE organization_id=p_org AND id=p_job;
 UPDATE emailmonitor.jobs SET state='queued' WHERE organization_id=p_org AND id=p_job;
 PERFORM emailmonitor.execution_sync(p_org,p_job);
 PERFORM emailmonitor.execution_emit(p_org,p_job,p_event,'job.queued');
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.execution_retry_pre_entitlement(p_org uuid, p_job uuid, p_revision bigint, p_new uuid, p_event uuid)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'emailmonitor'
AS $function$
DECLARE j emailmonitor.jobs; d emailmonitor.discovery; r emailmonitor.execution_runs; chosen jsonb; actor uuid; prior uuid; retry_page boolean;
BEGIN
 PERFORM emailmonitor.execution_control_fence(p_org,p_job);
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 SELECT * INTO d FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job;
 SELECT * INTO r FROM emailmonitor.execution_runs WHERE organization_id=p_org AND job_id=p_job;
 IF p_revision IS NULL OR j.row_version<>p_revision THEN RAISE EXCEPTION 'EXECUTION_REVISION' USING ERRCODE='EM409'; END IF;
 IF j.state NOT IN ('completed_partial','failed','cancelled') OR r.job_id IS NULL
 OR r.expires_at<=clock_timestamp() OR p_new IS NULL OR p_event IS NULL
 THEN RAISE EXCEPTION 'EXECUTION_RETRY_DENIED' USING ERRCODE='EM010'; END IF;
 SELECT job_id INTO prior FROM emailmonitor.execution_runs WHERE organization_id=p_org AND retry_from=p_job;
 IF prior IS NOT NULL THEN RETURN prior; END IF;
 -- Only exhausted transient failures are eligible. Existing committed article
 -- receipts are inherited by reference when resuming failed pagination, never rerun.
 SELECT EXISTS(SELECT 1 FROM emailmonitor.execution_items WHERE organization_id=p_org
 AND job_id=p_job AND work_kind='discover' AND state='failed' AND reason='lease_exhausted'
 AND input_url=d.checkpoint->>'next_url') INTO retry_page;
 SELECT jsonb_agg(i.input_url ORDER BY i.input_url) INTO chosen
 FROM emailmonitor.execution_items i WHERE i.organization_id=p_org AND i.job_id=p_job
 AND i.work_kind='article' AND i.state='failed' AND i.reason='lease_exhausted'
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.execution_effects e WHERE e.organization_id=p_org
 AND e.root_job_id=r.root_job_id AND e.effect_id=md5(p_org::text||':'||r.root_job_id::text||':article:'||i.input_url)::uuid);
 IF NOT retry_page AND (chosen IS NULL OR jsonb_array_length(chosen) NOT BETWEEN 1 AND 4) THEN
 RAISE EXCEPTION 'EXECUTION_RETRY_DENIED' USING ERRCODE='EM010'; END IF;
 actor:=emailmonitor.job_actor();
 INSERT INTO emailmonitor.jobs(organization_id,id,created_by,kind,request,state,discovery_complete)
 VALUES(p_org,p_new,actor,'extraction',j.request,'draft',j.discovery_complete);
 INSERT INTO emailmonitor.discovery(organization_id,job_id,generation,deletion_generation,source_id,policy_version,
 plan,checkpoint,max_pages,max_articles,revision)
 VALUES(p_org,p_new,1,d.deletion_generation,d.source_id,d.policy_version,d.plan,d.checkpoint,d.max_pages,d.max_articles,1);
 INSERT INTO emailmonitor.execution_runs(organization_id,job_id,root_job_id,retry_from,source_id,policy_version,
 deletion_generation,selected_urls,expires_at)
 VALUES(p_org,p_new,r.root_job_id,p_job,r.source_id,r.policy_version,r.deletion_generation,CASE WHEN retry_page THEN NULL ELSE chosen END,r.expires_at);
 UPDATE emailmonitor.jobs SET state='ready' WHERE organization_id=p_org AND id=p_new;
 UPDATE emailmonitor.jobs SET state='queued' WHERE organization_id=p_org AND id=p_new;
 PERFORM emailmonitor.execution_sync(p_org,p_new);
 IF retry_page THEN
 UPDATE emailmonitor.execution_items n SET state=old.state,reason=old.reason,attempts=0,
 batch_id=old.batch_id,effect_id=old.effect_id,completed_at=old.completed_at,
 inherited_job_id=old.job_id,inherited_item_id=old.id
 FROM emailmonitor.execution_items old WHERE n.organization_id=p_org AND n.job_id=p_new
 AND old.organization_id=p_org AND old.job_id=p_job AND n.work_kind='article'
 AND old.work_kind='article' AND old.input_url=n.input_url
 AND old.state IN ('succeeded','no_contact','needs_review','unsupported','policy_blocked','access_blocked','skipped','cancelled');
 DELETE FROM emailmonitor.execution_outbox o USING emailmonitor.execution_items n
 WHERE o.organization_id=p_org AND o.job_id=p_new AND n.organization_id=o.organization_id
 AND n.job_id=o.job_id AND n.id=o.item_id AND n.inherited_job_id IS NOT NULL;
 END IF;
 PERFORM emailmonitor.execution_emit(p_org,p_new,p_event,'job.queued');
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,p_event,actor,'job.retry_continuation_created',p_new);
 RETURN p_new;
END $function$;

CREATE OR REPLACE FUNCTION emailmonitor.service_schema_ready() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT (SELECT count(*)=1 AND min(version_num)='0028_europe_pmc_source' FROM public.alembic_version)
$$;
RESET ROLE;
