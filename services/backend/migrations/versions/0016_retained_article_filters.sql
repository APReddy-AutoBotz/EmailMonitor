-- Bounded retained article selection/presence. No source, credential or role expansion.
SET ROLE emailmonitor_owner;

CREATE OR REPLACE FUNCTION emailmonitor.result_filters_valid(p_filters jsonb) RETURNS boolean
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT COALESCE(jsonb_typeof(p_filters)='object'
 AND p_filters-'job_id'-'states'-'author_target'-'query'-'item_id'-'article_outcome_presence'='{}'::jsonb
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
$$;

-- Owner-private predicates never grant job or batch reads. All callers below fence exact authority.
CREATE FUNCTION emailmonitor.retained_article_job_current(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.privacy_job_allowed(p_org,p_job) AND COALESCE(emailmonitor.work_tenant_allowed(p_org),false) AND EXISTS(
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

CREATE FUNCTION emailmonitor.retained_article_batch_current(p_org uuid,p_batch uuid) RETURNS boolean
 LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
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
 AND (a.observation->>'route'<>'article_xml' OR (p.policy->'allowed_operations' ? 'fetch_xml' AND 'fetch_xml'=ANY(s.allowed_operations)))
 AND (a.observation->>'route'<>'browser_dom' OR (p.policy->'allowed_operations' ? 'browser' AND 'browser'=ANY(s.allowed_operations)))
 AND (NOT jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")') OR (
 p.policy->'allowed_operations' ? 'retain_excerpt' AND 'retain_excerpt'=ANY(s.allowed_operations) AND (p.policy->'retention'->>'excerpt_days')::integer>0)));
END $$;

CREATE FUNCTION emailmonitor.retained_observation_presence(p_document jsonb,p_candidates bigint)
 RETURNS text LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
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
 ELSIF NOT COALESCE(route IN ('html','browser_dom')
 AND p_document->>'parser_version'='synthetic-html-v1'
 AND status IN ('observed','no_contact','requires_browser'),false) THEN RETURN 'unresolved'; END IF;
 IF jsonb_array_length(p_document->'authors')=0 THEN RETURN 'unresolved'; END IF;
 -- Raw candidates, never accepted Contacts, syntax checks, or execution state.
 IF n>0 AND p_candidates>0 AND status IN ('observed','partial') THEN RETURN 'observed_candidate'; END IF;
 IF n=0 AND p_candidates=0 AND status='no_contact' THEN RETURN 'completed_without_candidate'; END IF;
 RETURN 'unresolved';
END $$;

CREATE FUNCTION emailmonitor.retained_article_binding(p_org uuid,p_job uuid,p_item uuid,p_export uuid DEFAULT NULL,p_fingerprint boolean DEFAULT true)
 RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
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
 AND (a.observation->>'route'<>'article_xml' OR a.observation->'binding'=jsonb_build_object(
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
END $$;

CREATE FUNCTION emailmonitor.retained_article_selection_fence(p_org uuid,p_filters jsonb) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF p_filters->>'item_id' IS NULL THEN RETURN; END IF;
 PERFORM emailmonitor.execution_read_fence(p_org,(p_filters->>'job_id')::uuid);
 PERFORM 1 FROM emailmonitor.execution_items WHERE organization_id=p_org
 AND job_id=(p_filters->>'job_id')::uuid AND id=(p_filters->>'item_id')::uuid AND work_kind='article' FOR SHARE NOWAIT;
 IF NOT FOUND THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.result_contacts(p_org uuid,p_filters jsonb,p_after_batch uuid DEFAULT NULL,
 p_after_association uuid DEFAULT NULL,p_limit integer DEFAULT 51) RETURNS SETOF jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE item record; selected_batch uuid;
BEGIN
 PERFORM emailmonitor.results_fence(p_org);
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
 AND a.state<>'suppressed' AND p_filters->'states' ? a.state
 AND (p_filters->>'job_id' IS NULL OR b.job_id=(p_filters->>'job_id')::uuid OR EXISTS(
 SELECT 1 FROM emailmonitor.execution_items i WHERE i.organization_id=p_org
 AND i.job_id=(p_filters->>'job_id')::uuid AND i.batch_id=a.batch_id))
 AND (p_filters->>'item_id' IS NULL OR a.batch_id=selected_batch)
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
 THEN RETURN NEXT emailmonitor.result_contact_document(p_org,item.batch_id,item.id); END IF;
 END LOOP;
 IF p_filters->>'item_id' IS NOT NULL AND (emailmonitor.retained_article_binding(p_org,
 (p_filters->>'job_id')::uuid,(p_filters->>'item_id')::uuid,NULL,false)->>'batch_id')::uuid
 IS DISTINCT FROM selected_batch THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 PERFORM emailmonitor.results_fence(p_org);
END $$;

-- Separate signature preserves the legacy five-argument entrypoint and NULL calls.
CREATE FUNCTION emailmonitor.result_outcomes_filtered(p_org uuid,p_filters jsonb,p_after_job uuid,
 p_after_item uuid,p_limit integer) RETURNS SETOF jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE item record; presence text:=COALESCE(p_filters->>'article_outcome_presence','all');
BEGIN
 PERFORM emailmonitor.results_fence(p_org);
 IF NOT COALESCE(emailmonitor.result_filters_valid(p_filters),false) OR p_limit IS NULL
 OR p_limit NOT BETWEEN 1 AND 2001 OR (p_after_job IS NULL)<>(p_after_item IS NULL)
 THEN RAISE EXCEPTION 'RESULT_FILTERS_INVALID'; END IF;
 IF p_filters->>'job_id' IS NOT NULL THEN PERFORM emailmonitor.execution_read_fence(p_org,(p_filters->>'job_id')::uuid); END IF;
 PERFORM emailmonitor.retained_article_selection_fence(p_org,p_filters);
 IF p_filters->>'item_id' IS NULL AND presence='all' THEN
 RETURN QUERY SELECT * FROM emailmonitor.result_outcomes(p_org,(p_filters->>'job_id')::uuid,p_after_job,p_after_item,p_limit);
 RETURN;
 END IF;
 FOR item IN SELECT i.job_id,i.id FROM emailmonitor.execution_items i
 WHERE i.organization_id=p_org AND i.work_kind='article'
 AND (p_filters->>'job_id' IS NULL OR i.job_id=(p_filters->>'job_id')::uuid)
 AND (p_filters->>'item_id' IS NULL OR i.id=(p_filters->>'item_id')::uuid)
 AND emailmonitor.execution_read_allowed(p_org,i.job_id)
 AND (presence='all' OR emailmonitor.retained_article_binding(p_org,i.job_id,i.id,NULL,false)->>'presence'=presence)
 AND (p_after_job IS NULL OR (i.job_id,i.id)>(p_after_job,p_after_item))
 ORDER BY i.job_id,i.id LIMIT p_limit LOOP
 PERFORM emailmonitor.execution_read_fence(p_org,item.job_id);
 PERFORM 1 FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=item.job_id AND id=item.id FOR SHARE NOWAIT;
 IF presence='all' OR emailmonitor.retained_article_binding(p_org,item.job_id,item.id,NULL,false)->>'presence'=presence THEN
 RETURN NEXT emailmonitor.result_outcome_document(p_org,item.job_id,item.id);
 END IF;
 END LOOP;
 PERFORM emailmonitor.results_fence(p_org);
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.export_request_validate(p_request jsonb)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF p_request IS NULL
 OR jsonb_typeof(p_request) IS DISTINCT FROM 'object'
 OR p_request-'job_id'-'format'-'purpose'-'include_unresolved'-'include_article_outcomes'-'author_target'-'query'-'ttl_seconds'-'optional_contact_fields'-'item_id'-'article_outcome_presence'<>'{}'::jsonb
 OR NOT p_request ?& ARRAY['job_id','format','purpose','include_unresolved','include_article_outcomes','author_target','query','ttl_seconds']
 OR NOT COALESCE(p_request->>'format' IN ('csv','xlsx'),false)
 OR p_request->>'purpose' IS DISTINCT FROM 'academic_contact_research'
 OR jsonb_typeof(p_request->'include_unresolved')<>'boolean' OR jsonb_typeof(p_request->'include_article_outcomes')<>'boolean'
 OR jsonb_typeof(p_request->'ttl_seconds')<>'number' OR p_request->>'ttl_seconds'!~'^[0-9]+$'
 OR (p_request->>'ttl_seconds')::integer NOT BETWEEN 1 AND 86400 THEN RAISE EXCEPTION 'EXPORT_REQUEST_INVALID'; END IF;
 IF NOT emailmonitor.result_filters_valid(jsonb_build_object('job_id',p_request->'job_id',
 'states','["accepted"]'::jsonb,'author_target',p_request->'author_target','query',p_request->'query')
 ||(p_request-ARRAY['format','purpose','include_unresolved','include_article_outcomes','ttl_seconds','optional_contact_fields']))
 THEN RAISE EXCEPTION 'EXPORT_REQUEST_INVALID'; END IF;
 IF p_request ? 'optional_contact_fields' THEN
 IF jsonb_typeof(p_request->'optional_contact_fields') IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'EXPORT_REQUEST_INVALID'; END IF;
 IF jsonb_array_length(p_request->'optional_contact_fields')>2 OR EXISTS(
 SELECT 1 FROM jsonb_array_elements(p_request->'optional_contact_fields') x
 WHERE jsonb_typeof(x)<>'string' OR x#>>'{}' NOT IN ('affiliations','article_title'))
 OR (SELECT count(*) FROM jsonb_array_elements(p_request->'optional_contact_fields'))<>
 (SELECT count(DISTINCT value) FROM jsonb_array_elements(p_request->'optional_contact_fields'))
 THEN RAISE EXCEPTION 'EXPORT_REQUEST_INVALID'; END IF;
 END IF;
END $$;

CREATE FUNCTION emailmonitor.retained_export_filters(p_request jsonb) RETURNS jsonb
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object('job_id',p_request->'job_id','states',CASE WHEN (p_request->>'include_unresolved')::boolean
 THEN '["accepted","needs_review","unmatched"]'::jsonb ELSE '["accepted"]'::jsonb END,
 'author_target',p_request->'author_target','query',p_request->'query')
 || CASE WHEN p_request->>'item_id' IS NOT NULL THEN jsonb_build_object('item_id',p_request->'item_id') ELSE '{}'::jsonb END
 || CASE WHEN COALESCE(p_request->>'article_outcome_presence','all')<>'all'
 THEN jsonb_build_object('article_outcome_presence',p_request->'article_outcome_presence') ELSE '{}'::jsonb END
$$;

CREATE OR REPLACE FUNCTION emailmonitor.exports_create_pre_entitlement(p_org uuid,p_id uuid,p_key text,p_request jsonb,p_event uuid)
 RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE actor uuid; cached emailmonitor.export_requests; filters jsonb; contacts jsonb; outcomes jsonb;
 stamp timestamptz:=clock_timestamp(); expiry timestamptz; policy bigint; doc jsonb; item jsonb; bindings jsonb:='[]'; binding jsonb;
BEGIN
 actor:=emailmonitor.results_fence(p_org,true);
 IF p_key IS NULL OR p_key!~'^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'EXPORT_REQUEST_INVALID'; END IF;
 PERFORM emailmonitor.export_request_validate(p_request);
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
 WHERE pp.organization_id=p_org AND pp.source_id='synthetic-publisher' AND pp.version=h.current_version;
 SELECT least(expiry,COALESCE(min(b.expires_at),expiry)) INTO expiry FROM emailmonitor.association_batches b
 WHERE b.organization_id=p_org AND b.id IN(SELECT (x->>'batch_id')::uuid FROM jsonb_array_elements(contacts) x);
 SELECT least(expiry,COALESCE(min(r.expires_at),expiry)) INTO expiry FROM emailmonitor.execution_runs r
 WHERE r.organization_id=p_org AND r.job_id IN(SELECT (x->>'job_id')::uuid FROM jsonb_array_elements(outcomes) x);
 -- Capture exact child authority even when the Contact keeps its original job provenance.
 IF filters->>'item_id' IS NOT NULL OR COALESCE(filters->>'article_outcome_presence','all')<>'all' THEN
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
 IF filters->>'item_id' IS NOT NULL OR COALESCE(filters->>'article_outcome_presence','all')<>'all' THEN
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
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.exports_preview_pre_entitlement(p_org uuid,p_request jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE filters jsonb; contacts integer; outcomes integer:=0;
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true);
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
END $$;

CREATE FUNCTION emailmonitor.retained_export_article_valid(p_org uuid,p_export uuid) RETURNS boolean
 LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE e emailmonitor.exports; captured jsonb; current_binding jsonb; expected jsonb; actual jsonb;
BEGIN
 IF NOT COALESCE(emailmonitor.work_export_allowed(p_org,p_export),false) THEN RETURN false; END IF;
 SELECT * INTO e FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export;
 IF e.id IS NULL THEN RETURN false; END IF;
 IF e.snapshot->'filters'->>'item_id' IS NULL
 AND COALESCE(e.snapshot->'filters'->>'article_outcome_presence','all')='all' THEN
 RETURN NOT e.snapshot ? 'article_filter_bindings'; END IF;
 IF jsonb_typeof(e.snapshot->'article_filter_bindings') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 SELECT COALESCE(jsonb_agg(x ORDER BY x::text),'[]') INTO expected FROM (
 SELECT DISTINCT jsonb_build_object('job_id',y->'job_id','item_id',y->'item_id') x FROM (
 SELECT value y FROM jsonb_array_elements(e.snapshot->'article_outcomes')
 UNION ALL SELECT jsonb_build_object('job_id',e.snapshot->'filters'->'job_id','item_id',e.snapshot->'filters'->'item_id')
 WHERE e.snapshot->'filters'->>'item_id' IS NOT NULL) chosen) unique_items;
 SELECT COALESCE(jsonb_agg(x-'fingerprint' ORDER BY (x-'fingerprint')::text),'[]') INTO actual
 FROM jsonb_array_elements(e.snapshot->'article_filter_bindings') x;
 IF actual IS DISTINCT FROM expected THEN RETURN false; END IF;
 FOR captured IN SELECT value FROM jsonb_array_elements(e.snapshot->'article_filter_bindings') LOOP
 current_binding:=emailmonitor.retained_article_binding(p_org,(captured->>'job_id')::uuid,(captured->>'item_id')::uuid,p_export);
 IF current_binding IS NULL OR current_binding->>'fingerprint' IS DISTINCT FROM captured->>'fingerprint' THEN RETURN false; END IF;
 IF COALESCE(e.snapshot->'filters'->>'article_outcome_presence','all')<>'all'
 AND EXISTS(SELECT 1 FROM jsonb_array_elements(e.snapshot->'article_outcomes') o
 WHERE o->>'job_id'=captured->>'job_id' AND o->>'item_id'=captured->>'item_id')
 AND current_binding->>'presence' IS DISTINCT FROM e.snapshot->'filters'->>'article_outcome_presence' THEN RETURN false; END IF;
 IF captured->>'item_id'=e.snapshot->'filters'->>'item_id' AND EXISTS(
 SELECT 1 FROM jsonb_array_elements(e.snapshot->'contacts') c
 WHERE c->>'batch_id' IS DISTINCT FROM current_binding->>'batch_id') THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$;

CREATE FUNCTION emailmonitor.retained_export_article_lock(p_org uuid,p_export uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE item record;
BEGIN
 IF NOT COALESCE(emailmonitor.work_export_allowed(p_org,p_export),false) THEN
 RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 FOR item IN SELECT i.job_id,i.id,i.batch_id,b.job_id source_job,b.article_url FROM emailmonitor.exports e,
 jsonb_array_elements(COALESCE(e.snapshot->'article_filter_bindings','[]')) x
 JOIN emailmonitor.execution_items i ON i.organization_id=p_org AND i.job_id=(x->>'job_id')::uuid AND i.id=(x->>'item_id')::uuid
 LEFT JOIN emailmonitor.association_batches b ON b.organization_id=i.organization_id AND b.id=i.batch_id
 WHERE e.organization_id=p_org AND e.id=p_export ORDER BY i.job_id,i.id LOOP
 PERFORM 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id IN (item.job_id,item.source_job) ORDER BY id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id IN (item.job_id,item.source_job) ORDER BY job_id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.execution_runs WHERE organization_id=p_org AND job_id IN (item.job_id,item.source_job) ORDER BY job_id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=item.job_id AND id=item.id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.association_batches WHERE organization_id=p_org AND id=item.batch_id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.article_observations WHERE organization_id=p_org AND job_id=item.source_job AND article_url=item.article_url FOR SHARE NOWAIT;
 END LOOP;
 IF NOT emailmonitor.retained_export_article_valid(p_org,p_export) THEN
 RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.export_valid(p_org uuid,p_export uuid) RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.retained_export_article_valid(p_org,p_export) AND emailmonitor.privacy_source_allowed(p_org) AND NOT EXISTS(SELECT 1 FROM emailmonitor.exports ee JOIN emailmonitor.lifecycle_configuration cc ON cc.organization_id=ee.organization_id WHERE ee.organization_id=p_org AND ee.id=p_export AND ee.created_at+make_interval(hours=>(cc.retention->>'export_hours')::integer)<=clock_timestamp()) AND COALESCE(EXISTS(SELECT 1 FROM emailmonitor.exports e JOIN emailmonitor.organizations o
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
 PERFORM emailmonitor.retained_export_article_lock(p_org,p_export);
 IF NOT emailmonitor.export_valid(p_org,p_export) THEN
 RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.service_schema_ready() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT (SELECT count(*)=1 AND min(version_num)='0016_retained_article_filters' FROM public.alembic_version)
$$;

-- Existing owners/ACLs survive CREATE OR REPLACE; new helpers remain owner-private.
REVOKE ALL ON FUNCTION emailmonitor.retained_article_job_current(uuid,uuid),
 emailmonitor.retained_article_batch_current(uuid,uuid),emailmonitor.retained_observation_presence(jsonb,bigint),
 emailmonitor.retained_article_binding(uuid,uuid,uuid,uuid,boolean),emailmonitor.retained_article_selection_fence(uuid,jsonb),
 emailmonitor.retained_export_filters(jsonb),emailmonitor.retained_export_article_valid(uuid,uuid),
 emailmonitor.retained_export_article_lock(uuid,uuid),emailmonitor.result_outcomes_filtered(uuid,jsonb,uuid,uuid,integer)
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator,emailmonitor_worker,emailmonitor_publisher;
GRANT EXECUTE ON FUNCTION emailmonitor.result_outcomes_filtered(uuid,jsonb,uuid,uuid,integer) TO emailmonitor_runtime;
RESET ROLE;
