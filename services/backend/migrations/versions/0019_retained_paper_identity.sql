-- Tenant-local observed DOI selection; no source, role or policy expansion.
SET ROLE emailmonitor_owner;

CREATE FUNCTION emailmonitor.normalized_paper_doi(p_value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog AS $$
 SELECT CASE WHEN length(p_value)<=256 AND p_value COLLATE "C" ~ '^10\.[0-9]{4,9}/[A-Za-z0-9._;()/:-]+$'
 AND NOT EXISTS(SELECT 1 FROM unnest(string_to_array(p_value,'/')) x WHERE x IN ('','.','..'))
 THEN lower(p_value COLLATE "C") END
$$;

CREATE FUNCTION emailmonitor.observed_paper_doi(p_document jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog,emailmonitor AS $$
DECLARE chosen text; fact jsonb; seen boolean:=false;
BEGIN
 chosen:=emailmonitor.normalized_paper_doi(p_document->'preferred_metadata'->>'doi');
 IF chosen IS NULL OR jsonb_typeof(p_document->'metadata') IS DISTINCT FROM 'array' THEN RETURN NULL; END IF;
 FOR fact IN SELECT value FROM jsonb_array_elements(p_document->'metadata') LOOP
 IF fact->>'field'='doi' THEN
 IF jsonb_typeof(fact->'value') IS DISTINCT FROM 'string'
 OR emailmonitor.normalized_paper_doi(fact->>'value') IS DISTINCT FROM chosen
 OR jsonb_typeof(fact->'evidence') IS DISTINCT FROM 'object'
 OR COALESCE(length(fact->'evidence'->>'locator'),0)=0 THEN RETURN NULL; END IF;
 seen:=true;
 END IF;
 END LOOP;
 RETURN CASE WHEN seen THEN chosen END;
END $$;

-- Populate only the new derived column under the migration identity. Existing
-- payloads remain unchanged. Then let the owner trigger maintain it, avoiding
-- new runtime EXECUTE grants for the private derivation functions.
ALTER TABLE emailmonitor.article_observations ADD COLUMN paper_doi text
 GENERATED ALWAYS AS (emailmonitor.observed_paper_doi(observation)) STORED;
ALTER TABLE emailmonitor.article_observations ALTER COLUMN paper_doi DROP EXPRESSION;
CREATE FUNCTION emailmonitor.guard_retained_paper_doi() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 NEW.paper_doi:=emailmonitor.observed_paper_doi(NEW.observation);
 RETURN NEW;
END $$;
CREATE TRIGGER z_retained_paper_doi BEFORE INSERT OR UPDATE ON emailmonitor.article_observations
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_retained_paper_doi();
CREATE INDEX retained_paper_doi ON emailmonitor.article_observations
 (organization_id,paper_doi) WHERE paper_doi IS NOT NULL;

CREATE FUNCTION emailmonitor.retained_paper_batch_matches(p_org uuid,p_batch uuid,p_doi text)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(emailmonitor.retained_article_batch_current(p_org,p_batch),false) AND EXISTS(
 SELECT 1 FROM emailmonitor.association_batches b JOIN emailmonitor.article_observations a
 ON a.organization_id=b.organization_id AND a.job_id=b.job_id AND a.article_url=b.article_url
 WHERE b.organization_id=p_org AND b.id=p_batch AND b.sealed
 AND b.source_revision=a.revision AND b.generation=a.generation AND b.policy_version=a.policy_version
 AND b.deletion_generation=a.deletion_generation
 AND a.paper_doi=p_doi
 AND emailmonitor.normalized_paper_doi(b.snapshot->'preferred_metadata'->>'doi')=p_doi)
$$;

CREATE FUNCTION emailmonitor.retained_paper_item_matches(p_org uuid,p_job uuid,p_item uuid,p_doi text,p_export uuid DEFAULT NULL)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(emailmonitor.retained_paper_batch_matches(p_org,
 (emailmonitor.retained_article_binding(p_org,p_job,p_item,p_export,false)->>'batch_id')::uuid,p_doi),false)
$$;


CREATE OR REPLACE FUNCTION emailmonitor.result_filters_valid(p_filters jsonb) RETURNS boolean
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(jsonb_typeof(p_filters)='object'
 AND p_filters-'job_id'-'states'-'author_target'-'query'-'item_id'-'article_outcome_presence'-'paper_doi'='{}'::jsonb
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
$$;

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
 AND (p_filters->>'paper_doi' IS NULL OR emailmonitor.retained_paper_batch_matches(p_org,item.batch_id,p_filters->>'paper_doi'))
 THEN RETURN NEXT emailmonitor.result_contact_document(p_org,item.batch_id,item.id); END IF;
 END LOOP;
 IF p_filters->>'item_id' IS NOT NULL AND (emailmonitor.retained_article_binding(p_org,
 (p_filters->>'job_id')::uuid,(p_filters->>'item_id')::uuid,NULL,false)->>'batch_id')::uuid
 IS DISTINCT FROM selected_batch THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 PERFORM emailmonitor.results_fence(p_org);
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.result_outcomes_filtered(p_org uuid,p_filters jsonb,p_after_job uuid,
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
 IF p_filters->>'item_id' IS NULL AND presence='all' AND p_filters->>'paper_doi' IS NULL THEN
 RETURN QUERY SELECT * FROM emailmonitor.result_outcomes(p_org,(p_filters->>'job_id')::uuid,p_after_job,p_after_item,p_limit);
 RETURN;
 END IF;
 FOR item IN SELECT i.job_id,i.id FROM emailmonitor.execution_items i
 WHERE i.organization_id=p_org AND i.work_kind='article'
 AND (p_filters->>'job_id' IS NULL OR i.job_id=(p_filters->>'job_id')::uuid)
 AND (p_filters->>'item_id' IS NULL OR i.id=(p_filters->>'item_id')::uuid)
 AND emailmonitor.execution_read_allowed(p_org,i.job_id)
 AND (p_filters->>'paper_doi' IS NULL OR emailmonitor.retained_paper_item_matches(p_org,i.job_id,i.id,p_filters->>'paper_doi'))
 AND (presence='all' OR emailmonitor.retained_article_binding(p_org,i.job_id,i.id,NULL,false)->>'presence'=presence)
 AND (p_after_job IS NULL OR (i.job_id,i.id)>(p_after_job,p_after_item))
 ORDER BY i.job_id,i.id LIMIT p_limit LOOP
 PERFORM emailmonitor.execution_read_fence(p_org,item.job_id);
 PERFORM 1 FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=item.job_id AND id=item.id FOR SHARE NOWAIT;
 IF (presence='all' OR emailmonitor.retained_article_binding(p_org,item.job_id,item.id,NULL,false)->>'presence'=presence)
 AND (p_filters->>'paper_doi' IS NULL OR emailmonitor.retained_paper_item_matches(p_org,item.job_id,item.id,p_filters->>'paper_doi')) THEN
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
 OR p_request-'job_id'-'format'-'purpose'-'include_unresolved'-'include_article_outcomes'-'author_target'-'query'-'ttl_seconds'-'optional_contact_fields'-'item_id'-'article_outcome_presence'-'paper_doi'<>'{}'::jsonb
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

CREATE OR REPLACE FUNCTION emailmonitor.retained_export_filters(p_request jsonb) RETURNS jsonb
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object('job_id',p_request->'job_id','states',CASE WHEN (p_request->>'include_unresolved')::boolean
 THEN '["accepted","needs_review","unmatched"]'::jsonb ELSE '["accepted"]'::jsonb END,
 'author_target',p_request->'author_target','query',p_request->'query')
 || CASE WHEN p_request->>'paper_doi' IS NOT NULL THEN jsonb_build_object('paper_doi',p_request->'paper_doi') ELSE '{}'::jsonb END
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
 WHERE pp.organization_id=p_org AND pp.source_id='synthetic-publisher' AND pp.version=h.current_version;
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
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.retained_export_article_valid(p_org uuid,p_export uuid) RETURNS boolean
 LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE e emailmonitor.exports; captured jsonb; current_binding jsonb; expected jsonb; actual jsonb;
BEGIN
 IF NOT COALESCE(emailmonitor.work_export_allowed(p_org,p_export),false) THEN RETURN false; END IF;
 SELECT * INTO e FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export;
 IF e.id IS NULL THEN RETURN false; END IF;
 IF e.snapshot->'filters'->>'paper_doi' IS NOT NULL AND EXISTS(
 SELECT 1 FROM jsonb_array_elements(e.snapshot->'contacts') c
 WHERE NOT emailmonitor.retained_paper_batch_matches(p_org,(c->>'batch_id')::uuid,e.snapshot->'filters'->>'paper_doi')) THEN RETURN false; END IF;
 IF e.snapshot->'filters'->>'paper_doi' IS NULL AND e.snapshot->'filters'->>'item_id' IS NULL
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
 IF e.snapshot->'filters'->>'paper_doi' IS NOT NULL
 AND EXISTS(SELECT 1 FROM jsonb_array_elements(e.snapshot->'article_outcomes') o WHERE o->>'job_id'=captured->>'job_id' AND o->>'item_id'=captured->>'item_id')
 AND NOT emailmonitor.retained_paper_batch_matches(p_org,(current_binding->>'batch_id')::uuid,e.snapshot->'filters'->>'paper_doi') THEN RETURN false; END IF;
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

CREATE OR REPLACE FUNCTION emailmonitor.service_schema_ready() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT (SELECT count(*)=1 AND min(version_num)='0019_retained_paper_identity' FROM public.alembic_version)
$$;
REVOKE ALL ON FUNCTION emailmonitor.normalized_paper_doi(text),emailmonitor.observed_paper_doi(jsonb),
 emailmonitor.guard_retained_paper_doi(),emailmonitor.retained_paper_batch_matches(uuid,uuid,text),emailmonitor.retained_paper_item_matches(uuid,uuid,uuid,text,uuid)
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator,emailmonitor_publisher,emailmonitor_worker;
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
RESET ROLE;
