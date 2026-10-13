-- Bounded synthetic UI preview/field selection; existing authority retained.
SET ROLE emailmonitor_owner;
CREATE FUNCTION emailmonitor.export_request_validate(p_request jsonb)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF p_request IS NULL
 OR jsonb_typeof(p_request) IS DISTINCT FROM 'object'
 OR p_request-'job_id'-'format'-'purpose'-'include_unresolved'-'include_article_outcomes'-'author_target'-'query'-'ttl_seconds'-'optional_contact_fields'<>'{}'::jsonb
 OR NOT p_request ?& ARRAY['job_id','format','purpose','include_unresolved','include_article_outcomes','author_target','query','ttl_seconds']
 OR NOT COALESCE(p_request->>'format' IN ('csv','xlsx'),false)
 OR p_request->>'purpose' IS DISTINCT FROM 'academic_contact_research'
 OR jsonb_typeof(p_request->'include_unresolved')<>'boolean' OR jsonb_typeof(p_request->'include_article_outcomes')<>'boolean'
 OR jsonb_typeof(p_request->'ttl_seconds')<>'number' OR p_request->>'ttl_seconds'!~'^[0-9]+$'
 OR (p_request->>'ttl_seconds')::integer NOT BETWEEN 1 AND 86400 THEN RAISE EXCEPTION 'EXPORT_REQUEST_INVALID'; END IF;
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
CREATE OR REPLACE FUNCTION emailmonitor.exports_create(p_org uuid,p_id uuid,p_key text,p_request jsonb,p_event uuid)
 RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE actor uuid; cached emailmonitor.export_requests; filters jsonb; contacts jsonb; outcomes jsonb;
 stamp timestamptz:=clock_timestamp(); expiry timestamptz; policy bigint; doc jsonb; item jsonb;
BEGIN
 actor:=emailmonitor.results_fence(p_org,true);
 IF p_key IS NULL OR p_key!~'^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'EXPORT_REQUEST_INVALID'; END IF;
 PERFORM emailmonitor.export_request_validate(p_request);
 INSERT INTO emailmonitor.export_requests VALUES(p_org,actor,p_key,p_request,NULL,stamp+interval '24 hours') ON CONFLICT DO NOTHING;
 SELECT * INTO cached FROM emailmonitor.export_requests WHERE organization_id=p_org AND actor_id=actor AND key_hash=p_key FOR UPDATE;
 IF cached.expires_at>stamp THEN
 IF cached.request||jsonb_build_object('optional_contact_fields',COALESCE(cached.request->'optional_contact_fields','["affiliations","article_title"]'::jsonb))
 <>p_request||jsonb_build_object('optional_contact_fields',COALESCE(p_request->'optional_contact_fields','["affiliations","article_title"]'::jsonb)) THEN RAISE EXCEPTION 'EXPORT_KEY_CONFLICT' USING ERRCODE='EM409'; END IF;
 IF cached.export_id IS NOT NULL THEN RETURN cached.export_id; END IF;
 ELSE UPDATE emailmonitor.export_requests SET request=p_request,export_id=NULL,expires_at=stamp+interval '24 hours'
 WHERE organization_id=p_org AND actor_id=actor AND key_hash=p_key; END IF;
 filters:=jsonb_build_object('job_id',p_request->'job_id','states',CASE WHEN (p_request->>'include_unresolved')::boolean
 THEN '["accepted","needs_review","unmatched"]'::jsonb ELSE '["accepted"]'::jsonb END,
 'author_target',p_request->'author_target','query',p_request->'query');
 SELECT COALESCE(jsonb_agg(document),'[]'::jsonb) INTO contacts FROM emailmonitor.result_contacts(p_org,filters,NULL,NULL,2001) AS rows(document);
 IF jsonb_array_length(contacts)>2000 THEN RAISE EXCEPTION 'EXPORT_REFINE_FILTERS'; END IF;
 outcomes:='[]'::jsonb;
 IF (p_request->>'include_article_outcomes')::boolean THEN
 SELECT COALESCE(jsonb_agg(document),'[]'::jsonb) INTO outcomes FROM emailmonitor.result_outcomes(p_org,(p_request->>'job_id')::uuid,NULL,NULL,2001) AS rows(document);
 IF jsonb_array_length(outcomes)>2000 THEN RAISE EXCEPTION 'EXPORT_REFINE_FILTERS'; END IF;
 END IF;
 SELECT pp.version,least(pp.valid_until,stamp+make_interval(secs=>(p_request->>'ttl_seconds')::integer))
 INTO policy,expiry FROM emailmonitor.source_policies pp JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
 WHERE pp.organization_id=p_org AND pp.source_id='synthetic-publisher' AND pp.version=h.current_version;
 SELECT least(expiry,COALESCE(min(b.expires_at),expiry)) INTO expiry FROM emailmonitor.association_batches b
 WHERE b.organization_id=p_org AND b.id IN(SELECT (x->>'batch_id')::uuid FROM jsonb_array_elements(contacts) x);
 SELECT least(expiry,COALESCE(min(r.expires_at),expiry)) INTO expiry FROM emailmonitor.execution_runs r
 WHERE r.organization_id=p_org AND r.job_id IN(SELECT (x->>'job_id')::uuid FROM jsonb_array_elements(outcomes) x);
 doc:=jsonb_build_object('schema_version','1.0','organization_id',p_org,'export_id',p_id,'requested_by',actor,
 'purpose',p_request->'purpose','filters',filters,'format',p_request->'format',
 'include_article_outcomes',p_request->'include_article_outcomes',
 'optional_contact_fields',COALESCE(p_request->'optional_contact_fields','["affiliations","article_title"]'::jsonb),'contacts',contacts,'article_outcomes',outcomes,
 'created_at',stamp,'expires_at',expiry,'synthetic',true,'technical_checks_performed',false,'outreach_approved',false);
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
CREATE FUNCTION emailmonitor.exports_preview(p_org uuid,p_request jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE filters jsonb; contacts integer; outcomes integer:=0;
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true);
 PERFORM emailmonitor.export_request_validate(p_request);
 filters:=jsonb_build_object('job_id',p_request->'job_id','states',CASE WHEN (p_request->>'include_unresolved')::boolean
 THEN '["accepted","needs_review","unmatched"]'::jsonb ELSE '["accepted"]'::jsonb END,
 'author_target',p_request->'author_target','query',p_request->'query');
 SELECT count(*) INTO contacts FROM emailmonitor.result_contacts(p_org,filters,NULL,NULL,2001);
 IF (p_request->>'include_article_outcomes')::boolean THEN
 SELECT count(*) INTO outcomes FROM emailmonitor.result_outcomes(p_org,(p_request->>'job_id')::uuid,NULL,NULL,2001);
 END IF;
 IF contacts>2000 OR outcomes>2000 THEN RAISE EXCEPTION 'EXPORT_REFINE_FILTERS'; END IF;
 RETURN jsonb_build_object('organization_id',p_org,'contacts',contacts,'article_outcomes',outcomes,
 'optional_contact_fields',COALESCE(p_request->'optional_contact_fields','["affiliations","article_title"]'::jsonb),
 'counts_may_change',true,'excluded_reasons',CASE WHEN (p_request->>'include_unresolved')::boolean
 THEN '["rejected_and_suppressed_excluded","unavailable_records_not_disclosed"]'::jsonb
 ELSE '["unaccepted_excluded_by_default","rejected_and_suppressed_excluded","unavailable_records_not_disclosed"]'::jsonb END);
END $$;
REVOKE ALL ON FUNCTION emailmonitor.export_request_validate(jsonb),emailmonitor.exports_preview(uuid,jsonb)
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
GRANT EXECUTE ON FUNCTION emailmonitor.exports_preview(uuid,jsonb) TO emailmonitor_runtime;
RESET ROLE;
