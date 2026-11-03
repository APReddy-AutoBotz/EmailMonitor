-- Synthetic retained data only. No source acquisition, external storage or production enablement.
SET ROLE emailmonitor_owner;
CREATE FUNCTION emailmonitor.results_fence(p_org uuid,p_export boolean DEFAULT false,
 p_requester uuid DEFAULT NULL,p_policy boolean DEFAULT true) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE actor uuid; p emailmonitor.source_policies; s emailmonitor.source_catalog;
BEGIN
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) THEN
 RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 actor:=emailmonitor.job_actor();
 -- NOWAIT refuses contention rather than introducing a reverse-lock wait against
 -- existing membership triggers; current authority is rechecked after every lock.
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.memberships WHERE organization_id=p_org
 AND identity_id IN (actor,COALESCE(p_requester,actor)) ORDER BY identity_id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.identities WHERE id IN (actor,COALESCE(p_requester,actor))
 ORDER BY id FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.sessions WHERE token_hash=current_setting('emailmonitor.session_hash',true)
 FOR SHARE NOWAIT;
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) OR NOT EXISTS(
 SELECT 1 FROM emailmonitor.organizations WHERE id=p_org AND status='active') OR NOT EXISTS(
 SELECT 1 FROM emailmonitor.sessions ss JOIN emailmonitor.identities ii ON ii.id=ss.identity_id
 WHERE ss.token_hash=current_setting('emailmonitor.session_hash',true) AND ss.revoked_at IS NULL
 AND ss.expires_at>clock_timestamp() AND ii.active AND ss.permission_revision=ii.permission_revision)
 OR (p_export AND emailmonitor.session_role(p_org) NOT IN ('owner','admin','data_steward'))
 OR (p_requester IS NOT NULL AND NOT EXISTS(SELECT 1 FROM emailmonitor.memberships m
 JOIN emailmonitor.identities ii ON ii.id=m.identity_id WHERE m.organization_id=p_org
 AND m.identity_id=p_requester AND m.status='active' AND ii.active
 AND m.role IN ('owner','admin','data_steward')))
 THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 IF p_policy THEN
 SELECT * INTO s FROM emailmonitor.source_catalog WHERE source_id='synthetic-publisher' FOR SHARE NOWAIT;
 PERFORM 1 FROM emailmonitor.source_policy_heads WHERE organization_id=p_org
 AND source_id='synthetic-publisher' FOR SHARE NOWAIT;
 SELECT pp.* INTO p FROM emailmonitor.source_policies pp JOIN emailmonitor.source_policy_heads h
 USING(organization_id,source_id) WHERE pp.organization_id=p_org AND pp.source_id='synthetic-publisher'
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
END $$;
CREATE FUNCTION emailmonitor.result_filters_valid(p_filters jsonb) RETURNS boolean
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT COALESCE(jsonb_typeof(p_filters)='object'
 AND p_filters-'job_id'-'states'-'author_target'-'query'='{}'::jsonb
 AND p_filters ?& ARRAY['job_id','states','author_target','query']
 AND (p_filters->'job_id'='null'::jsonb OR (jsonb_typeof(p_filters->'job_id')='string'
 AND p_filters->>'job_id' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'))
 AND jsonb_typeof(p_filters->'states')='array' AND jsonb_array_length(p_filters->'states') BETWEEN 1 AND 4
 AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(p_filters->'states') x
 WHERE x NOT IN ('accepted','needs_review','unmatched','rejected'))
 AND jsonb_array_length(p_filters->'states')=(SELECT count(DISTINCT x)
 FROM jsonb_array_elements_text(p_filters->'states') x)
 AND p_filters->>'author_target' IN ('all','first','corresponding')
 AND jsonb_typeof(p_filters->'query')='string' AND length(p_filters->>'query')<=100
 AND p_filters->>'query' !~ '[[:cntrl:]]',false)
$$;
CREATE FUNCTION emailmonitor.result_contact_document(p_org uuid,p_batch uuid,p_association uuid)
 RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT jsonb_build_object('organization_id',a.organization_id,'job_id',b.job_id,'batch_id',a.batch_id,
 'association_id',a.id,'revision',a.revision,'candidate_id',a.candidate_id,'author_id',a.author_id,
 'author_name',au.display_name,'first_author',au.first_role,'corresponding_author',au.correspondence_role,
 'affiliations',COALESCE(au.record->'affiliations','[]'::jsonb),'raw_address',ca.raw_address,
 'normalized_address',ca.normalized_address,'state',a.state,'evidence_strength',a.record->'evidence_strength',
 'association_reason',a.record->'reason','evidence_ids',a.record->'evidence_ids','source_id','synthetic-publisher',
 'source_url',b.article_url,'policy_version',b.policy_version,'title',b.snapshot->'preferred_metadata'->'title',
 'observed_at',obs.observed_at,'syntax_status',ca.syntax_status,'identity_state','article_local_unresolved',
 'technical_status','not_checked','delivery_status','unverified','outreach_eligibility','not_assessed')
 FROM emailmonitor.author_email_associations a JOIN emailmonitor.association_batches b
 ON b.organization_id=a.organization_id AND b.id=a.batch_id JOIN emailmonitor.association_candidates ca
 ON ca.organization_id=a.organization_id AND ca.batch_id=a.batch_id AND ca.id=a.candidate_id
 LEFT JOIN emailmonitor.association_authors au ON au.organization_id=a.organization_id
 AND au.batch_id=a.batch_id AND au.id=a.author_id JOIN emailmonitor.article_observations obs
 ON obs.organization_id=b.organization_id AND obs.job_id=b.job_id AND obs.article_url=b.article_url
 WHERE a.organization_id=p_org AND a.batch_id=p_batch AND a.id=p_association
 AND a.state<>'suppressed' AND emailmonitor.association_visible(p_org,p_batch)
$$;
CREATE FUNCTION emailmonitor.result_contacts(p_org uuid,p_filters jsonb,p_after_batch uuid DEFAULT NULL,
 p_after_association uuid DEFAULT NULL,p_limit integer DEFAULT 51) RETURNS SETOF jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE item record;
BEGIN
 PERFORM emailmonitor.results_fence(p_org);
 IF NOT COALESCE(emailmonitor.result_filters_valid(p_filters),false) OR p_limit IS NULL
 OR p_limit NOT BETWEEN 1 AND 2001 OR (p_after_batch IS NULL)<>(p_after_association IS NULL)
 THEN RAISE EXCEPTION 'RESULT_FILTERS_INVALID'; END IF;
 IF p_filters->>'job_id' IS NOT NULL THEN
 PERFORM emailmonitor.execution_read_fence(p_org,(p_filters->>'job_id')::uuid); END IF;
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
 PERFORM emailmonitor.results_fence(p_org);
END $$;
CREATE FUNCTION emailmonitor.result_outcome_document(p_org uuid,p_job uuid,p_item uuid)
 RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT jsonb_build_object('organization_id',i.organization_id,'job_id',i.job_id,'item_id',i.id,
 'source_url',i.input_url,'state',i.state,'reason',i.reason,'batch_id',i.batch_id,'completed_at',i.completed_at,
 'inherited_job_id',i.inherited_job_id,'observation_status',obs.observation->'status',
 'technical_status','not_checked','outreach_eligibility','not_assessed')
 FROM emailmonitor.execution_items i LEFT JOIN emailmonitor.article_observations obs
 ON obs.organization_id=i.organization_id AND obs.job_id=COALESCE(i.inherited_job_id,i.job_id)
 AND obs.article_url=i.input_url WHERE i.organization_id=p_org AND i.job_id=p_job AND i.id=p_item
 AND i.work_kind='article' AND emailmonitor.execution_read_allowed(p_org,p_job)
$$;
CREATE FUNCTION emailmonitor.result_outcomes(p_org uuid,p_job uuid DEFAULT NULL,p_after_job uuid DEFAULT NULL,
 p_after_item uuid DEFAULT NULL,p_limit integer DEFAULT 51) RETURNS SETOF jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE item record;
BEGIN
 PERFORM emailmonitor.results_fence(p_org);
 IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 2001 OR (p_after_job IS NULL)<>(p_after_item IS NULL)
 THEN RAISE EXCEPTION 'RESULT_FILTERS_INVALID'; END IF;
 IF p_job IS NOT NULL THEN PERFORM emailmonitor.execution_read_fence(p_org,p_job); END IF;
 FOR item IN SELECT i.job_id,i.id FROM emailmonitor.execution_items i
 WHERE i.organization_id=p_org AND i.work_kind='article' AND (p_job IS NULL OR i.job_id=p_job)
 AND emailmonitor.execution_read_allowed(p_org,i.job_id)
 AND (p_after_job IS NULL OR (i.job_id,i.id)>(p_after_job,p_after_item))
 ORDER BY i.job_id,i.id LIMIT p_limit LOOP
 PERFORM emailmonitor.execution_read_fence(p_org,item.job_id);
 PERFORM 1 FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=item.job_id AND id=item.id FOR SHARE NOWAIT;
 RETURN NEXT emailmonitor.result_outcome_document(p_org,item.job_id,item.id);
 END LOOP;
 PERFORM emailmonitor.results_fence(p_org);
END $$;
CREATE FUNCTION emailmonitor.result_contact(p_org uuid,p_batch uuid,p_association uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE document jsonb;
BEGIN
 PERFORM emailmonitor.results_fence(p_org);
 PERFORM emailmonitor.lock_association_batch(p_org,p_batch);
 PERFORM 1 FROM emailmonitor.author_email_associations WHERE organization_id=p_org
 AND batch_id=p_batch AND id=p_association FOR SHARE NOWAIT;
 document:=emailmonitor.result_contact_document(p_org,p_batch,p_association);
 IF document IS NULL THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 PERFORM emailmonitor.results_fence(p_org);
 RETURN document;
END $$;
CREATE FUNCTION emailmonitor.result_evidence(p_org uuid,p_batch uuid,p_evidence uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE document jsonb;
BEGIN
 PERFORM emailmonitor.results_fence(p_org);
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
 PERFORM emailmonitor.results_fence(p_org);
 RETURN document;
END $$;
CREATE TABLE emailmonitor.exports (
 organization_id uuid NOT NULL REFERENCES emailmonitor.organizations(id), id uuid NOT NULL,
 requested_by uuid NOT NULL REFERENCES emailmonitor.identities(id), request jsonb NOT NULL,
 snapshot jsonb NOT NULL CHECK(octet_length(snapshot::text)<=2097152),
 state text NOT NULL CHECK(state IN ('queued','running','ready','failed','revoked','expired')),
 reason text NOT NULL, revision bigint NOT NULL DEFAULT 1, generation bigint NOT NULL DEFAULT 1,
 deletion_generation bigint NOT NULL, policy_version bigint NOT NULL,
 created_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 lease_nonce uuid, lease_until timestamptz, attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
 PRIMARY KEY(organization_id,id), CHECK(expires_at>created_at AND expires_at<=created_at+interval '24 hours')
);
CREATE TABLE emailmonitor.export_members (
 organization_id uuid NOT NULL, export_id uuid NOT NULL, batch_id uuid NOT NULL,
 association_id uuid NOT NULL, association_revision bigint NOT NULL,
 PRIMARY KEY(organization_id,export_id,batch_id,association_id),
 FOREIGN KEY(organization_id,export_id) REFERENCES emailmonitor.exports(organization_id,id),
 FOREIGN KEY(organization_id,batch_id,association_id) REFERENCES emailmonitor.author_email_associations(organization_id,batch_id,id)
);
CREATE TABLE emailmonitor.export_outcomes (
 organization_id uuid NOT NULL, export_id uuid NOT NULL, job_id uuid NOT NULL,item_id uuid NOT NULL,
 job_revision bigint NOT NULL, document jsonb NOT NULL,
 PRIMARY KEY(organization_id,export_id,job_id,item_id),
 FOREIGN KEY(organization_id,export_id) REFERENCES emailmonitor.exports(organization_id,id),
 FOREIGN KEY(organization_id,job_id,item_id) REFERENCES emailmonitor.execution_items(organization_id,job_id,id)
);
CREATE TABLE emailmonitor.export_artifacts (
 organization_id uuid NOT NULL,export_id uuid NOT NULL,body bytea NOT NULL CHECK(octet_length(body)<=8388608),
 mime text NOT NULL,extension text NOT NULL,digest text NOT NULL,
 PRIMARY KEY(organization_id,export_id),
 FOREIGN KEY(organization_id,export_id) REFERENCES emailmonitor.exports(organization_id,id)
);
CREATE TABLE emailmonitor.export_requests (
 organization_id uuid NOT NULL,actor_id uuid NOT NULL,key_hash text NOT NULL CHECK(key_hash~'^[0-9a-f]{64}$'),
 request jsonb NOT NULL,export_id uuid,expires_at timestamptz NOT NULL,
 PRIMARY KEY(organization_id,actor_id,key_hash),
 FOREIGN KEY(organization_id,export_id) REFERENCES emailmonitor.exports(organization_id,id)
);
CREATE TABLE emailmonitor.export_outbox (
 organization_id uuid NOT NULL,export_id uuid NOT NULL,event_id uuid NOT NULL,generation bigint NOT NULL,
 published_at timestamptz,deliveries bigint NOT NULL DEFAULT 0,
 PRIMARY KEY(organization_id,export_id),UNIQUE(organization_id,event_id),
 FOREIGN KEY(organization_id,export_id) REFERENCES emailmonitor.exports(organization_id,id)
);
CREATE TABLE emailmonitor.export_effects (
 organization_id uuid NOT NULL,export_id uuid NOT NULL,generation bigint NOT NULL,digest text NOT NULL,
 committed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(organization_id,export_id),
 FOREIGN KEY(organization_id,export_id) REFERENCES emailmonitor.exports(organization_id,id)
);
CREATE TABLE emailmonitor.export_events (
 organization_id uuid NOT NULL,export_id uuid NOT NULL,event_id uuid NOT NULL,
 event_type text NOT NULL CHECK(event_type IN ('export.requested','export.ready','export.revoked','export.expired')),
 occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(organization_id,event_id),
 FOREIGN KEY(organization_id,export_id) REFERENCES emailmonitor.exports(organization_id,id)
);
CREATE FUNCTION emailmonitor.export_valid(p_org uuid,p_export uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(EXISTS(SELECT 1 FROM emailmonitor.exports e JOIN emailmonitor.organizations o
 ON o.id=e.organization_id JOIN emailmonitor.memberships m ON m.organization_id=e.organization_id
 AND m.identity_id=e.requested_by JOIN emailmonitor.identities ii ON ii.id=m.identity_id
 JOIN emailmonitor.source_policy_heads h ON h.organization_id=e.organization_id AND h.source_id='synthetic-publisher'
 JOIN emailmonitor.source_policies p ON p.organization_id=h.organization_id AND p.source_id=h.source_id AND p.version=h.current_version
 JOIN emailmonitor.source_catalog s ON s.source_id=h.source_id
 WHERE e.organization_id=p_org AND e.id=p_export AND emailmonitor.tenant_allowed(p_org)
 AND emailmonitor.session_role(p_org) IN ('owner','admin','data_steward')
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
CREATE FUNCTION emailmonitor.export_lock(p_org uuid,p_export uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE item record; requester uuid;
BEGIN
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
 IF NOT emailmonitor.export_valid(p_org,p_export) THEN
 RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
END $$;
CREATE FUNCTION emailmonitor.export_metadata(p_org uuid,p_export uuid) RETURNS jsonb
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT jsonb_build_object('organization_id',e.organization_id,'id',e.id,'requested_by',e.requested_by,
 'format',e.request->'format','purpose',e.request->'purpose','state',e.state,'reason',e.reason,
 'revision',e.revision,'generation',e.generation,'contacts',jsonb_array_length(e.snapshot->'contacts'),
 'article_outcomes',jsonb_array_length(e.snapshot->'article_outcomes'),'created_at',e.created_at,
 'expires_at',e.expires_at,'download_available',e.state='ready' AND emailmonitor.export_valid(p_org,p_export),
 'synthetic',true,'production_enabled',false) FROM emailmonitor.exports e WHERE e.organization_id=p_org
 AND e.id=p_export AND emailmonitor.tenant_allowed(p_org)
 AND emailmonitor.session_role(p_org) IN ('owner','admin','data_steward')
$$;
CREATE FUNCTION emailmonitor.exports_create(p_org uuid,p_id uuid,p_key text,p_request jsonb,p_event uuid)
 RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE actor uuid; cached emailmonitor.export_requests; filters jsonb; contacts jsonb; outcomes jsonb;
 stamp timestamptz:=clock_timestamp(); expiry timestamptz; policy bigint; doc jsonb; item jsonb;
BEGIN
 actor:=emailmonitor.results_fence(p_org,true);
 IF p_key IS NULL OR p_key!~'^[0-9a-f]{64}$' OR p_request IS NULL
 OR jsonb_typeof(p_request) IS DISTINCT FROM 'object'
 OR p_request-'job_id'-'format'-'purpose'-'include_unresolved'-'include_article_outcomes'-'author_target'-'query'-'ttl_seconds'<>'{}'::jsonb
 OR NOT p_request ?& ARRAY['job_id','format','purpose','include_unresolved','include_article_outcomes','author_target','query','ttl_seconds']
 OR NOT COALESCE(p_request->>'format' IN ('csv','xlsx'),false)
 OR p_request->>'purpose' IS DISTINCT FROM 'academic_contact_research'
 OR jsonb_typeof(p_request->'include_unresolved')<>'boolean' OR jsonb_typeof(p_request->'include_article_outcomes')<>'boolean'
 OR jsonb_typeof(p_request->'ttl_seconds')<>'number' OR p_request->>'ttl_seconds'!~'^[0-9]+$'
 OR (p_request->>'ttl_seconds')::integer NOT BETWEEN 1 AND 86400 THEN RAISE EXCEPTION 'EXPORT_REQUEST_INVALID'; END IF;
 INSERT INTO emailmonitor.export_requests VALUES(p_org,actor,p_key,p_request,NULL,stamp+interval '24 hours') ON CONFLICT DO NOTHING;
 SELECT * INTO cached FROM emailmonitor.export_requests WHERE organization_id=p_org AND actor_id=actor AND key_hash=p_key FOR UPDATE;
 IF cached.expires_at>stamp THEN
 IF cached.request<>p_request THEN RAISE EXCEPTION 'EXPORT_KEY_CONFLICT' USING ERRCODE='EM409'; END IF;
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
 'include_article_outcomes',p_request->'include_article_outcomes','contacts',contacts,'article_outcomes',outcomes,
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
CREATE FUNCTION emailmonitor.exports_claim(p_org uuid,p_export uuid,p_event uuid,p_generation bigint,p_nonce uuid,p_seconds integer)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE e emailmonitor.exports;
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true);
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
END $$;
CREATE FUNCTION emailmonitor.exports_finish(p_org uuid,p_export uuid,p_generation bigint,p_nonce uuid,p_body bytea,p_mime text,p_extension text)
 RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE e emailmonitor.exports; hash text; mime text; extension text;
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true);
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
 VALUES(p_org,p_nonce,emailmonitor.job_actor(),'export.ready',p_export);
 INSERT INTO emailmonitor.export_events(organization_id,export_id,event_id,event_type) VALUES(p_org,p_export,p_nonce,'export.ready');
 PERFORM emailmonitor.export_lock(p_org,p_export);
 RETURN true;
END $$;
CREATE FUNCTION emailmonitor.exports_fail(p_org uuid,p_export uuid,p_generation bigint,p_nonce uuid,p_reason text)
 RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true,NULL,false);
 IF p_reason IS NULL OR p_reason NOT IN ('unsafe_csv_cell','unsupported_text','render_limit','snapshot_changed','worker_failure')
 THEN RAISE EXCEPTION 'EXPORT_FAILURE_INVALID'; END IF;
 UPDATE emailmonitor.exports SET state='failed',reason=p_reason,revision=revision+1,lease_nonce=NULL,lease_until=NULL
 WHERE organization_id=p_org AND id=p_export AND generation=p_generation AND lease_nonce=p_nonce
 AND state='running' AND lease_until>clock_timestamp();
 RETURN FOUND;
END $$;
CREATE FUNCTION emailmonitor.exports_reconcile(p_org uuid,p_export uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE e emailmonitor.exports;
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true,NULL,false);
 SELECT * INTO e FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export FOR UPDATE NOWAIT;
 IF e.id IS NULL THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 IF e.state IN ('failed','revoked','expired') THEN RETURN; END IF;
 IF e.expires_at<=clock_timestamp() THEN
 UPDATE emailmonitor.exports SET state='expired',reason='expired',generation=generation+1,revision=revision+1,
 lease_nonce=NULL,lease_until=NULL WHERE organization_id=p_org AND id=p_export;
 DELETE FROM emailmonitor.export_artifacts WHERE organization_id=p_org AND export_id=p_export;
 RETURN;
 END IF;
 IF e.state='ready' THEN RETURN; END IF;
 IF NOT emailmonitor.export_valid(p_org,p_export) THEN
 UPDATE emailmonitor.exports SET state='failed',reason='snapshot_changed',generation=generation+1,
 revision=revision+1,lease_nonce=NULL,lease_until=NULL WHERE organization_id=p_org AND id=p_export;
 RETURN;
 END IF;
 IF e.state='running' AND e.lease_until>clock_timestamp() THEN RETURN; END IF;
 IF e.attempts>=3 THEN
 UPDATE emailmonitor.exports SET state='failed',reason='worker_failure',revision=revision+1,
 lease_nonce=NULL,lease_until=NULL WHERE organization_id=p_org AND id=p_export;
 ELSE
 UPDATE emailmonitor.exports SET state='queued',reason='scheduled',revision=revision+1,
 lease_nonce=NULL,lease_until=NULL WHERE organization_id=p_org AND id=p_export;
 UPDATE emailmonitor.export_outbox SET published_at=NULL WHERE organization_id=p_org AND export_id=p_export;
 END IF;
END $$;
CREATE FUNCTION emailmonitor.exports_revoke(p_org uuid,p_export uuid,p_revision bigint,p_event uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE e emailmonitor.exports; actor uuid;
BEGIN
 actor:=emailmonitor.results_fence(p_org,true,NULL,false);
 SELECT * INTO e FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export FOR UPDATE NOWAIT;
 IF e.id IS NULL THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 IF e.revision IS DISTINCT FROM p_revision THEN RAISE EXCEPTION 'EXPORT_REVISION' USING ERRCODE='EM409'; END IF;
 IF e.state='revoked' THEN RETURN; END IF;
 UPDATE emailmonitor.exports SET state='revoked',reason='user_revoked',generation=generation+1,revision=revision+1,
 lease_nonce=NULL,lease_until=NULL WHERE organization_id=p_org AND id=p_export;
 DELETE FROM emailmonitor.export_artifacts WHERE organization_id=p_org AND export_id=p_export;
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id) VALUES(p_org,p_event,actor,'export.revoked',p_export);
 INSERT INTO emailmonitor.export_events(organization_id,export_id,event_id,event_type) VALUES(p_org,p_export,p_event,'export.revoked');
END $$;
CREATE FUNCTION emailmonitor.exports_download(p_org uuid,p_export uuid) RETURNS TABLE(body bytea,mime text,extension text,digest text)
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true);
 PERFORM 1 FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export FOR SHARE NOWAIT;
 PERFORM emailmonitor.export_lock(p_org,p_export);
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export AND state='ready')
 THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 RETURN QUERY SELECT a.body,a.mime,a.extension,a.digest FROM emailmonitor.export_artifacts a
 JOIN emailmonitor.export_effects f ON f.organization_id=a.organization_id AND f.export_id=a.export_id AND f.digest=a.digest
 WHERE a.organization_id=p_org AND a.export_id=p_export AND a.digest=encode(sha256(a.body),'hex');
 IF NOT FOUND THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 PERFORM emailmonitor.export_lock(p_org,p_export);
END $$;
CREATE FUNCTION emailmonitor.exports_confirmed(p_org uuid,p_export uuid,p_event uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true);
 PERFORM emailmonitor.export_lock(p_org,p_export);
 UPDATE emailmonitor.export_outbox SET published_at=clock_timestamp() WHERE organization_id=p_org AND export_id=p_export
 AND event_id=p_event AND generation=(SELECT generation FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export);
END $$;
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['exports','export_members','export_outcomes','export_artifacts','export_requests','export_outbox','export_effects','export_events'] LOOP
 EXECUTE format('ALTER TABLE emailmonitor.%I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('ALTER TABLE emailmonitor.%I FORCE ROW LEVEL SECURITY',t);
 EXECUTE format('CREATE POLICY owner_all ON emailmonitor.%I TO emailmonitor_owner USING(true) WITH CHECK(true)',t);
 EXECUTE format('CREATE POLICY tenant_read ON emailmonitor.%I FOR SELECT TO emailmonitor_runtime USING(emailmonitor.tenant_allowed(organization_id) AND emailmonitor.session_role(organization_id) IN (''owner'',''admin'',''data_steward''))',t);
 END LOOP;
END $$;
GRANT SELECT(organization_id,id,requested_by,state,reason,revision,generation,created_at,expires_at) ON emailmonitor.exports TO emailmonitor_runtime;
GRANT SELECT ON emailmonitor.export_outbox,emailmonitor.export_effects,emailmonitor.export_events TO emailmonitor_runtime;
DO $$ DECLARE f record; BEGIN
 FOR f IN SELECT oid::regprocedure AS signature FROM pg_proc WHERE pronamespace='emailmonitor'::regnamespace
 AND (proname LIKE 'result%' OR proname LIKE 'export%') LOOP
 EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator',f.signature);
 END LOOP;
END $$;
GRANT EXECUTE ON FUNCTION emailmonitor.result_contacts(uuid,jsonb,uuid,uuid,integer),
 emailmonitor.result_outcomes(uuid,uuid,uuid,uuid,integer),emailmonitor.result_contact(uuid,uuid,uuid),
 emailmonitor.result_evidence(uuid,uuid,uuid),emailmonitor.export_metadata(uuid,uuid),
 emailmonitor.exports_create(uuid,uuid,text,jsonb,uuid),emailmonitor.exports_claim(uuid,uuid,uuid,bigint,uuid,integer),
 emailmonitor.exports_finish(uuid,uuid,bigint,uuid,bytea,text,text),emailmonitor.exports_fail(uuid,uuid,bigint,uuid,text),
 emailmonitor.exports_reconcile(uuid,uuid),emailmonitor.exports_revoke(uuid,uuid,bigint,uuid),
 emailmonitor.exports_download(uuid,uuid),emailmonitor.exports_confirmed(uuid,uuid,uuid) TO emailmonitor_runtime;
RESET ROLE;
