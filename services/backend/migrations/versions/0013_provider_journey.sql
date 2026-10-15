-- Controlled fixture bindings only. No live policy, role, grant or network activation.
SET ROLE emailmonitor_owner;

CREATE FUNCTION emailmonitor.fixture_acquisition_operation(p_url text) RETURNS text
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,emailmonitor AS $$
 SELECT CASE WHEN p_url IN ('https://synthetic.publisher.example/article-xml.xml',
 'https://synthetic.publisher.example/provider-doi.xml','https://synthetic.publisher.example/provider-pii.xml') THEN 'fetch_xml'
 WHEN p_url='https://synthetic.publisher.example/provider-search-0.json' THEN 'search'
 ELSE 'fetch_html' END
$$;
REVOKE ALL ON FUNCTION emailmonitor.fixture_acquisition_operation(text) FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;

CREATE FUNCTION emailmonitor.registered_provider_document(p_source text,p_url text) RETURNS jsonb
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT value FROM emailmonitor.source_catalog c,
 jsonb_array_elements(COALESCE(c.support->'provider_documents','[]'::jsonb)) value
 WHERE c.source_id=p_source AND c.execution_mode='fixture'
 AND value->>'source_id'=p_source AND value->>'source_url'=p_url
 AND value->>'acquisition_mode'='controlled_fixture'
$$;
REVOKE ALL ON FUNCTION emailmonitor.registered_provider_document(text,text) FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;

UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,'{provider_documents}','[{"source_id":"synthetic-publisher","source_url":"https://synthetic.publisher.example/provider-doi.xml","identifier":{"kind":"doi","value":"10.9999/synthetic.1"},"aliases":[{"kind":"pii","value":"S0000000000000001"}],"content_digest":"ecffa55455f07f6205a1bb2ab6bc30f7e2528845eae757a17c32d88c5fa4ec30","source_profile":"article_retrieval_response","acquisition_mode":"controlled_fixture"},{"source_id":"synthetic-publisher","source_url":"https://synthetic.publisher.example/provider-pii.xml","identifier":{"kind":"pii","value":"S0000000000000002"},"aliases":[],"content_digest":"183c0dd3f9a17199ed3ce5fd4de7b0eccfb912d636c7a84395077d5c29bb3aa8","source_profile":"xocs_document","acquisition_mode":"controlled_fixture"}]'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';
UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,'{fixture_routes}',(support#>'{fixture_routes}')||'["/provider-search-0.json", "/provider-doi.xml", "/provider-pii.xml"]'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';
UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,'{routes_by_operation,search}',(support#>'{routes_by_operation,search}')||'["/provider-search-0.json"]'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';
UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,'{routes_by_operation,fetch_xml}',(support#>'{routes_by_operation,fetch_xml}')||'["/provider-doi.xml", "/provider-pii.xml"]'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';
UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,'{routes_by_operation,extract_contacts}',(support#>'{routes_by_operation,extract_contacts}')||'["/provider-doi.xml", "/provider-pii.xml"]'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';
UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,'{routes_by_operation,retain_excerpt}',(support#>'{routes_by_operation,retain_excerpt}')||'["/provider-doi.xml", "/provider-pii.xml"]'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';
UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,'{routes_by_operation,export_contacts}',(support#>'{routes_by_operation,export_contacts}')||'["/provider-doi.xml", "/provider-pii.xml"]'::jsonb) WHERE source_id='synthetic-publisher' AND execution_mode='fixture';
ALTER TABLE emailmonitor.article_observations DROP CONSTRAINT article_observations_article_url_check;
ALTER TABLE emailmonitor.article_observations ADD CONSTRAINT article_observations_article_url_check CHECK(article_url IN ('https://synthetic.publisher.example/article-a.html','https://synthetic.publisher.example/article-b.html','https://synthetic.publisher.example/tooltip.html','https://synthetic.publisher.example/no-contact.html','https://synthetic.publisher.example/article-xml.xml','https://synthetic.publisher.example/provider-doi.xml','https://synthetic.publisher.example/provider-pii.xml'));
ALTER TABLE emailmonitor.execution_items DROP CONSTRAINT execution_items_input_url_check;
ALTER TABLE emailmonitor.execution_items ADD CONSTRAINT execution_items_input_url_check CHECK(input_url IN ('https://synthetic.publisher.example/search-page-1.html','https://synthetic.publisher.example/search-page-2.html','https://synthetic.publisher.example/article-a.html','https://synthetic.publisher.example/article-b.html','https://synthetic.publisher.example/tooltip.html','https://synthetic.publisher.example/no-contact.html','https://synthetic.publisher.example/article-xml.xml','https://synthetic.publisher.example/provider-search-0.json','https://synthetic.publisher.example/provider-doi.xml','https://synthetic.publisher.example/provider-pii.xml'));
-- Replace only the inherited route/kind relationship; all other item fences remain.
DO $$ DECLARE selected text; matches integer; BEGIN
 SELECT count(*),min(conname::text) INTO matches,selected FROM pg_constraint
 WHERE conrelid='emailmonitor.execution_items'::regclass AND contype='c'
 AND position('search-page-%.html' in pg_get_constraintdef(oid))>0;
 IF matches<>1 THEN RAISE EXCEPTION 'EXPECTED_EXECUTION_ROUTE_GUARD'; END IF;
 EXECUTE format('ALTER TABLE emailmonitor.execution_items DROP CONSTRAINT %I',selected);
END $$;
ALTER TABLE emailmonitor.execution_items ADD CONSTRAINT execution_item_route_kind CHECK(
 (work_kind='discover' AND input_url IN ('https://synthetic.publisher.example/search-page-1.html',
 'https://synthetic.publisher.example/search-page-2.html','https://synthetic.publisher.example/provider-search-0.json'))
 OR (work_kind='article' AND input_url NOT IN ('https://synthetic.publisher.example/search-page-1.html',
 'https://synthetic.publisher.example/search-page-2.html','https://synthetic.publisher.example/provider-search-0.json')));
ALTER TABLE emailmonitor.source_resource_requests DROP CONSTRAINT source_resource_requests_operation_check;
ALTER TABLE emailmonitor.source_resource_requests ADD CONSTRAINT source_resource_requests_operation_check CHECK(operation IN ('fetch_html','fetch_xml','browser','search'));

CREATE OR REPLACE FUNCTION emailmonitor.guard_discovery() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
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
 IF TG_OP='INSERT' THEN
 IF NEW.revision<>1 THEN RAISE EXCEPTION 'DISCOVERY_INITIAL_REVISION'; END IF;
 ELSE
 IF (NEW.organization_id,NEW.job_id,NEW.generation,NEW.deletion_generation,NEW.source_id,NEW.policy_version,NEW.plan,NEW.max_pages,NEW.max_articles)
 IS DISTINCT FROM (OLD.organization_id,OLD.job_id,OLD.generation,OLD.deletion_generation,OLD.source_id,OLD.policy_version,OLD.plan,OLD.max_pages,OLD.max_articles)
 THEN RAISE EXCEPTION 'DISCOVERY_PLAN_IMMUTABLE'; END IF;
 IF OLD.checkpoint->>'status'<>'pending' OR NEW.revision<>OLD.revision+1 THEN RAISE EXCEPTION 'DISCOVERY_REVISION_FENCE'; END IF;
 END IF;
 RETURN NEW;
END $$;

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
 AND p.policy->'allowed_operations' ? emailmonitor.fixture_acquisition_operation(d.plan->>'start_url') AND p.policy->'allowed_operations' ? 'extract_contacts'
 AND emailmonitor.fixture_acquisition_operation(d.plan->>'start_url')=ANY(s.allowed_operations) AND 'extract_contacts'=ANY(s.allowed_operations)
 AND 'synthetic.publisher.example'=ANY(s.allowed_hosts) AND p.policy->'allowed_hosts' ? 'synthetic.publisher.example'
 AND (p.policy->'retention'->>'contact_days')::integer>0) AND EXISTS(
 SELECT 1 FROM emailmonitor.sessions ss JOIN emailmonitor.identities ii ON ii.id=ss.identity_id
 WHERE ss.token_hash=current_setting('emailmonitor.session_hash',true) AND ss.revoked_at IS NULL
 AND ss.expires_at>statement_timestamp() AND ii.active AND ss.permission_revision=ii.permission_revision)
$$;

CREATE OR REPLACE FUNCTION emailmonitor.admission_try(p_org uuid,p_job uuid,p_reference uuid,p_pool text,p_generation bigint,p_nonce uuid,p_seconds integer)
 RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE stamp timestamptz:=clock_timestamp(); conf jsonb; saved jsonb; slots integer; active integer;
 pool_state emailmonitor.admission_pools; mine emailmonitor.admission_requests; chosen uuid; ticket uuid;
BEGIN
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) OR p_nonce IS NULL OR p_reference IS NULL
 OR p_generation IS NULL OR p_generation<1 OR p_seconds IS NULL OR p_seconds NOT BETWEEN 1 AND 120
 OR p_pool NOT IN ('fixture_io','parse','export','browser','http') THEN
 RAISE EXCEPTION 'ADMISSION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
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
 INSERT INTO emailmonitor.admission_requests(organization_id,id,pool,actor_id,session_hash,job_id,reference_id,generation,expires_at,state)
 VALUES(p_org,ticket,p_pool,emailmonitor.job_actor(),current_setting('emailmonitor.session_hash',true),p_job,p_reference,p_generation,stamp+interval '120 seconds','waiting')
 ON CONFLICT(organization_id,pool,reference_id,generation) DO UPDATE SET heartbeat_at=stamp,actor_id=EXCLUDED.actor_id,session_hash=EXCLUDED.session_hash
 WHERE admission_requests.state='waiting';
 SELECT * INTO mine FROM emailmonitor.admission_requests WHERE organization_id=p_org AND id=ticket;
 IF mine.state<>'waiting' THEN RETURN false; END IF;
 SELECT count(*) INTO active FROM emailmonitor.admission_requests WHERE admission_requests.pool=p_pool AND state='active';
 IF active>=pool_state.maximum OR (SELECT count(*) FROM emailmonitor.admission_requests
 WHERE organization_id=p_org AND admission_requests.pool=p_pool AND state='active')>=slots THEN RETURN false; END IF;
 SELECT a.id INTO chosen FROM emailmonitor.admission_requests a
 JOIN emailmonitor.organizations o ON o.id=a.organization_id AND o.status='active'
 JOIN emailmonitor.tenant_configuration c ON c.organization_id=a.organization_id
 LEFT JOIN emailmonitor.job_entitlements captured ON captured.organization_id=a.organization_id AND captured.job_id=a.job_id
 LEFT JOIN emailmonitor.export_entitlements exported ON p_pool='export' AND exported.organization_id=a.organization_id AND exported.export_id=a.reference_id
 WHERE a.pool=p_pool AND a.state='waiting' AND a.expires_at>stamp
 AND EXISTS(SELECT 1 FROM emailmonitor.memberships m JOIN emailmonitor.identities i ON i.id=m.identity_id
 JOIN emailmonitor.sessions ss ON ss.identity_id=i.id AND ss.token_hash=a.session_hash
 WHERE m.organization_id=a.organization_id AND m.identity_id=a.actor_id AND m.status='active' AND i.active
 AND ss.revoked_at IS NULL AND ss.expires_at>stamp AND ss.permission_revision=i.permission_revision
 AND m.role IN ('owner','admin','data_steward','operator') AND (p_pool<>'export' OR m.role<>'operator'))
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
 JOIN emailmonitor.sessions sess ON sess.token_hash=a.session_hash AND sess.identity_id=actor.id
 JOIN emailmonitor.source_catalog catalog ON catalog.source_id=d.source_id
 WHERE j.organization_id=a.organization_id AND j.id=a.job_id AND j.generation=a.generation
 AND j.state IN ('draft','queued','running') AND membership.status='active' AND actor.active
 AND sess.revoked_at IS NULL AND sess.expires_at>stamp AND sess.permission_revision=actor.permission_revision
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
 UPDATE emailmonitor.admission_requests SET state='active',nonce=p_nonce,
 lease_until=stamp+make_interval(secs=>p_seconds) WHERE organization_id=p_org AND id=ticket;
 UPDATE emailmonitor.admission_pools SET last_organization=p_org WHERE admission_pools.pool=p_pool;
 UPDATE emailmonitor.admission_mutex SET acquired=acquired+1 WHERE id;
 RETURN true;
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.fixture_admission_claim(p_org uuid,p_job uuid,p_url text,p_nonce uuid,p_seconds integer)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs; d emailmonitor.discovery; v_pool text; reference uuid; inherited boolean;
BEGIN
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false)
 OR emailmonitor.session_role(p_org) NOT IN ('owner','admin','data_steward','operator')
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
 OR p_operation NOT IN ('fetch_html','fetch_xml','browser','search') OR p_path IS NULL OR length(p_path)>512
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

CREATE OR REPLACE FUNCTION emailmonitor.network_entitlement_allowed(p_org uuid,p_operation text,p_job uuid DEFAULT NULL) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE conf jsonb; saved jsonb;
BEGIN
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE NOWAIT;
 IF NOT FOUND THEN RETURN false; END IF;
 IF p_job IS NOT NULL THEN PERFORM 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR SHARE NOWAIT; IF NOT FOUND THEN RETURN false; END IF; END IF;
 IF NOT emailmonitor.privacy_source_allowed(p_org) OR (p_job IS NOT NULL AND NOT emailmonitor.privacy_job_allowed(p_org,p_job)) THEN RETURN false; END IF;
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) OR emailmonitor.session_role(p_org) NOT IN ('owner','admin','data_steward','operator')
 OR p_operation IS NULL OR p_operation NOT IN ('fetch_html','fetch_xml','browser','search') THEN RETURN false; END IF;
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

CREATE OR REPLACE FUNCTION emailmonitor.guard_article_observation() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
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
 OR ((NEW.article_url<>'https://synthetic.publisher.example/article-xml.xml' AND registered IS NULL)
 AND NEW.observation->>'parser_version'='synthetic-html-v1'
 AND NEW.observation->>'route' IN ('html','browser_dom')
 AND NEW.observation->>'status' IN ('observed','no_contact','requires_browser'))),false)
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
 OR NOT (p->'allowed_operations' ? (CASE WHEN (NEW.article_url='https://synthetic.publisher.example/article-xml.xml' OR registered IS NOT NULL) THEN 'fetch_xml' ELSE 'fetch_html' END))
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
END $$;

RESET ROLE;
