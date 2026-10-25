-- Optional selection of existing registered source provenance only. No authority changes.
SET ROLE emailmonitor_owner;

CREATE OR REPLACE FUNCTION emailmonitor.result_filters_valid(p_filters jsonb) RETURNS boolean
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(jsonb_typeof(p_filters)='object'
 AND p_filters-'job_id'-'states'-'author_target'-'query'-'item_id'-'article_outcome_presence'-'paper_doi'-'source_id'='{}'::jsonb
 AND (NOT p_filters ? 'source_id' OR p_filters->'source_id'='null'::jsonb OR p_filters->'source_id'='"synthetic-publisher"'::jsonb)
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
 AND (p_filters->>'source_id' IS NULL OR EXISTS(SELECT 1 FROM emailmonitor.article_observations o WHERE o.organization_id=p_org AND o.job_id=b.job_id AND o.article_url=b.article_url AND o.source_id=p_filters->>'source_id'))
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
 AND (p_filters->>'source_id' IS NULL OR EXISTS(SELECT 1 FROM emailmonitor.association_batches b JOIN emailmonitor.article_observations o ON o.organization_id=b.organization_id AND o.job_id=b.job_id AND o.article_url=b.article_url WHERE b.organization_id=p_org AND b.id=item.batch_id AND o.source_id=p_filters->>'source_id'))
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
 IF p_filters->>'source_id' IS NULL AND p_filters->>'item_id' IS NULL AND presence='all' AND p_filters->>'paper_doi' IS NULL THEN
 RETURN QUERY SELECT * FROM emailmonitor.result_outcomes(p_org,(p_filters->>'job_id')::uuid,p_after_job,p_after_item,p_limit);
 RETURN;
 END IF;
 FOR item IN SELECT i.job_id,i.id FROM emailmonitor.execution_items i
 WHERE i.organization_id=p_org AND i.work_kind='article'
 AND (p_filters->>'job_id' IS NULL OR i.job_id=(p_filters->>'job_id')::uuid)
 AND (p_filters->>'item_id' IS NULL OR i.id=(p_filters->>'item_id')::uuid)
 AND emailmonitor.execution_read_allowed(p_org,i.job_id)
 AND (p_filters->>'source_id' IS NULL OR EXISTS(SELECT 1 FROM emailmonitor.discovery j WHERE j.organization_id=p_org AND j.job_id=i.job_id AND j.source_id=p_filters->>'source_id'))
 AND (p_filters->>'paper_doi' IS NULL OR emailmonitor.retained_paper_item_matches(p_org,i.job_id,i.id,p_filters->>'paper_doi'))
 AND (presence='all' OR emailmonitor.retained_article_binding(p_org,i.job_id,i.id,NULL,false)->>'presence'=presence)
 AND (p_after_job IS NULL OR (i.job_id,i.id)>(p_after_job,p_after_item))
 ORDER BY i.job_id,i.id LIMIT p_limit LOOP
 PERFORM emailmonitor.execution_read_fence(p_org,item.job_id);
 PERFORM 1 FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=item.job_id AND id=item.id FOR SHARE NOWAIT;
 IF (presence='all' OR emailmonitor.retained_article_binding(p_org,item.job_id,item.id,NULL,false)->>'presence'=presence)
 AND (p_filters->>'source_id' IS NULL OR EXISTS(SELECT 1 FROM emailmonitor.discovery j WHERE j.organization_id=p_org AND j.job_id=item.job_id AND j.source_id=p_filters->>'source_id'))
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
 OR p_request-'job_id'-'format'-'purpose'-'include_unresolved'-'include_article_outcomes'-'author_target'-'query'-'ttl_seconds'-'optional_contact_fields'-'item_id'-'article_outcome_presence'-'paper_doi'-'source_id'<>'{}'::jsonb
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
 || CASE WHEN p_request->>'source_id' IS NOT NULL THEN jsonb_build_object('source_id',p_request->'source_id') ELSE '{}'::jsonb END
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


CREATE OR REPLACE FUNCTION emailmonitor.service_schema_ready() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT (SELECT count(*)=1 AND min(version_num)='0020_retained_source_selection' FROM public.alembic_version)
$$;
RESET ROLE;
