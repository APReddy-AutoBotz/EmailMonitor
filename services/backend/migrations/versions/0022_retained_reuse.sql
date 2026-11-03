-- Local candidate. Reuse remains hard-disabled until real SQL and lifecycle proof.
-- Existing runtime role memberships and grants are unchanged.
SET ROLE emailmonitor_owner;
ALTER TABLE emailmonitor.article_observations
 ADD COLUMN reused_from_job uuid,
 ADD COLUMN reused_source_revision bigint,
 ADD COLUMN reused_source_batch uuid,
 ADD CONSTRAINT retained_reuse_shape CHECK (
  (reused_from_job IS NULL AND reused_source_revision IS NULL AND reused_source_batch IS NULL)
  OR (reused_from_job IS NOT NULL AND reused_source_revision IS NOT NULL
      AND reused_source_revision>0 AND reused_source_batch IS NOT NULL
      AND reused_from_job<>job_id)),
 ADD CONSTRAINT retained_reuse_source_observation_fk
  FOREIGN KEY(organization_id,reused_from_job,article_url)
  REFERENCES emailmonitor.article_observations(organization_id,job_id,article_url),
 ADD CONSTRAINT retained_reuse_source_batch_fk
  FOREIGN KEY(organization_id,reused_source_batch)
  REFERENCES emailmonitor.association_batches(organization_id,id),
 ADD CONSTRAINT retained_reuse_disabled CHECK (
  reused_from_job IS NULL AND reused_source_revision IS NULL AND reused_source_batch IS NULL);
CREATE INDEX retained_reuse_dependents ON emailmonitor.article_observations
 (organization_id,reused_from_job,job_id) WHERE reused_from_job IS NOT NULL;

-- Called only inside existing owner-definer fences, never as a new runtime grant.
-- A retained target fails closed if the exact original, batch or live policy no
-- longer exists. Source observations are required to be originals, so this
-- graph has one hop and the source privacy call cannot recurse through reuse.
CREATE FUNCTION emailmonitor.retained_reuse_current(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT NOT EXISTS(
  SELECT 1 FROM emailmonitor.article_observations t
  WHERE t.organization_id=p_org AND t.job_id=p_job AND t.reused_from_job IS NOT NULL
  AND NOT EXISTS(
   SELECT 1 FROM emailmonitor.article_observations s
   JOIN emailmonitor.association_batches b ON b.organization_id=s.organization_id
    AND b.job_id=s.job_id AND b.article_url=s.article_url AND b.id=t.reused_source_batch
   WHERE s.organization_id=t.organization_id AND s.job_id=t.reused_from_job
    AND s.article_url=t.article_url AND s.reused_from_job IS NULL
    AND NOT EXISTS(SELECT 1 FROM emailmonitor.article_observations prior
     WHERE prior.organization_id=s.organization_id AND prior.job_id=s.job_id
      AND prior.reused_from_job IS NOT NULL)
    AND s.revision=t.reused_source_revision AND b.source_revision=s.revision
    AND b.generation=s.generation AND b.policy_version=s.policy_version
    AND b.deletion_generation=s.deletion_generation AND b.sealed
    AND s.source_id=t.source_id AND s.policy_version=t.policy_version
    AND s.deletion_generation=t.deletion_generation
    AND s.source_digest=t.source_digest AND s.observation=t.observation
    AND s.observed_at=t.observed_at AND t.expires_at<=s.expires_at
    AND t.expires_at<=b.expires_at AND t.expires_at>clock_timestamp()
    AND CASE WHEN s.reused_from_job IS NULL AND NOT EXISTS(
     SELECT 1 FROM emailmonitor.article_observations prior
      WHERE prior.organization_id=s.organization_id AND prior.job_id=s.job_id
       AND prior.reused_from_job IS NOT NULL)
     THEN emailmonitor.privacy_job_state(p_org,s.job_id) ELSE false END
  )
 )
$$;
REVOKE ALL ON FUNCTION emailmonitor.retained_reuse_current(uuid,uuid)
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator,emailmonitor_worker,emailmonitor_publisher;

-- Keep the original observation validation, fixture admission and accounting
-- triggers in place. This later trigger checks the exact source and restores
-- original observation time/expiry after the original guard's timestamp write.
CREATE FUNCTION emailmonitor.guard_retained_reuse() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE source emailmonitor.article_observations; b emailmonitor.association_batches;
 target emailmonitor.jobs; d emailmonitor.discovery; cutoff timestamptz;
BEGIN
 IF TG_OP='UPDATE' THEN
  IF (NEW.reused_from_job,NEW.reused_source_revision,NEW.reused_source_batch)
   IS DISTINCT FROM (OLD.reused_from_job,OLD.reused_source_revision,OLD.reused_source_batch)
   OR OLD.reused_from_job IS NOT NULL THEN
   RAISE EXCEPTION 'REUSE_LINEAGE_IMMUTABLE' USING ERRCODE='EM009'; END IF;
 END IF;
 IF NEW.reused_from_job IS NULL THEN RETURN NEW; END IF;
 IF TG_OP<>'INSERT' OR NOT COALESCE(emailmonitor.human_work_tenant_allowed(NEW.organization_id),false)
  OR NOT COALESCE(emailmonitor.job_write_allowed(NEW.organization_id,NEW.job_id),false) THEN
  RAISE EXCEPTION 'REUSE_SCOPE_DENIED' USING ERRCODE='EM009'; END IF;
 SELECT * INTO target FROM emailmonitor.jobs WHERE organization_id=NEW.organization_id
  AND id=NEW.job_id FOR SHARE NOWAIT;
 SELECT * INTO d FROM emailmonitor.discovery WHERE organization_id=NEW.organization_id
  AND job_id=NEW.job_id FOR SHARE NOWAIT;
 SELECT * INTO source FROM emailmonitor.article_observations WHERE organization_id=NEW.organization_id
  AND job_id=NEW.reused_from_job AND article_url=NEW.article_url FOR SHARE NOWAIT;
 SELECT * INTO b FROM emailmonitor.association_batches WHERE organization_id=NEW.organization_id
  AND id=NEW.reused_source_batch FOR SHARE NOWAIT;
 IF source.job_id IS NOT NULL AND (source.reused_from_job IS NOT NULL OR EXISTS(
  SELECT 1 FROM emailmonitor.article_observations prior
   WHERE prior.organization_id=NEW.organization_id AND prior.job_id=source.job_id
    AND prior.reused_from_job IS NOT NULL)) THEN
  RAISE EXCEPTION 'REUSE_SCOPE_DENIED' USING ERRCODE='EM009'; END IF;
 IF jsonb_typeof(target.request->'reuse') IS DISTINCT FROM 'object'
  OR ((target.request->'reuse') - 'mode' - 'fresh_since') IS DISTINCT FROM '{}'::jsonb
  OR COALESCE(target.request->'reuse'->>'fresh_since','') !~
   '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})$'
 THEN RAISE EXCEPTION 'REUSE_SCOPE_DENIED' USING ERRCODE='EM009'; END IF;
 BEGIN
  cutoff:=(target.request->'reuse'->>'fresh_since')::timestamptz;
 EXCEPTION WHEN data_exception THEN
  RAISE EXCEPTION 'REUSE_SCOPE_DENIED' USING ERRCODE='EM009';
 END;
 IF target.id IS NULL OR target.state<>'draft' OR target.kind<>'extraction'
  OR target.request->'reuse'->>'mode' IS DISTINCT FROM 'verified_retained'
  OR target.request->'input'->>'type' IS DISTINCT FROM 'url'
  OR target.request->'input'->>'url' IS DISTINCT FROM NEW.article_url
  OR NEW.article_url NOT IN ('https://synthetic.publisher.example/article-a.html',
   'https://synthetic.publisher.example/article-b.html',
   'https://synthetic.publisher.example/no-contact.html')
  OR d.job_id IS NULL OR d.checkpoint->'articles' IS DISTINCT FROM jsonb_build_array(NEW.article_url)
  OR d.checkpoint->'discovery_complete' IS DISTINCT FROM 'true'::jsonb
  OR d.generation<>NEW.generation OR d.deletion_generation<>NEW.deletion_generation
  OR d.revision<>NEW.discovery_revision OR d.source_id<>NEW.source_id
  OR d.policy_version<>NEW.policy_version OR NEW.revision<>1
  OR cutoff IS NULL OR cutoff>clock_timestamp()
  OR source.job_id IS NULL OR source.job_id=NEW.job_id OR source.reused_from_job IS NOT NULL
  OR EXISTS(SELECT 1 FROM emailmonitor.article_observations prior
   WHERE prior.organization_id=NEW.organization_id AND prior.job_id=source.job_id
    AND prior.reused_from_job IS NOT NULL)
  OR source.revision<>NEW.reused_source_revision OR source.observed_at<cutoff
  OR source.observed_at>clock_timestamp() OR source.expires_at<=clock_timestamp()
  OR source.observation->>'route'<>'html' OR source.observation->>'status' NOT IN ('observed','no_contact')
  OR NOT COALESCE(emailmonitor.privacy_excerpt_allowed(NEW.organization_id,
   source.observed_at,source.observation),false)
  OR source.source_id<>NEW.source_id OR source.policy_version<>NEW.policy_version
  OR source.deletion_generation<>NEW.deletion_generation
  OR source.source_digest<>NEW.source_digest OR source.observation IS DISTINCT FROM NEW.observation
  OR b.id IS NULL OR b.job_id<>source.job_id OR b.article_url<>source.article_url
  OR b.source_revision<>source.revision OR NOT b.sealed OR b.expires_at<=clock_timestamp()
  OR NOT COALESCE(emailmonitor.association_visible(NEW.organization_id,b.id),false)
 THEN RAISE EXCEPTION 'REUSE_SCOPE_DENIED' USING ERRCODE='EM009'; END IF;
 PERFORM emailmonitor.association_parent_fence(NEW.organization_id,source.job_id,
  source.article_url,source.revision,false);
 NEW.observed_at:=source.observed_at;
 NEW.expires_at:=LEAST(source.expires_at,b.expires_at);
 RETURN NEW;
END $$;
CREATE TRIGGER zz_retained_reuse_guard BEFORE INSERT OR UPDATE ON emailmonitor.article_observations
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_retained_reuse();
REVOKE ALL ON FUNCTION emailmonitor.guard_retained_reuse()
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator,emailmonitor_worker,emailmonitor_publisher;

-- Add source-current fencing to both human and service lifecycle checks.
CREATE OR REPLACE FUNCTION emailmonitor.privacy_job_allowed(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.privacy_source_allowed(p_org) AND NOT EXISTS(SELECT 1 FROM emailmonitor.lifecycle_job_deadlines d WHERE d.organization_id=p_org AND d.job_id=p_job
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
$$;

CREATE OR REPLACE FUNCTION emailmonitor.privacy_job_state(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.privacy_source_state(p_org) AND NOT EXISTS(SELECT 1 FROM emailmonitor.lifecycle_job_deadlines d WHERE d.organization_id=p_org AND d.job_id=p_job
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
$$;

-- Purge dependent jobs first, bounded and resumable.
CREATE OR REPLACE FUNCTION emailmonitor.lifecycle_purge(p_org uuid,p_id uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE marker emailmonitor.deletion_tombstones; item record; remain boolean;
BEGIN
 PERFORM emailmonitor.lifecycle_scope(p_org);
 SELECT * INTO marker FROM emailmonitor.deletion_tombstones WHERE organization_id=p_org AND id=p_id FOR UPDATE;
 IF marker.id IS NULL THEN RAISE EXCEPTION 'LIFECYCLE_SCOPE_DENIED' USING ERRCODE='EM014'; END IF;
 IF marker.stage='purged' THEN RETURN emailmonitor.lifecycle_receipt(p_org,p_id); END IF;
 IF marker.job_id IS NOT NULL THEN
 -- Fence and purge at most ten direct dependents before the source receipt can
 -- become purged. Immutable original-only sources make the graph one hop.
 FOR item IN SELECT DISTINCT a.job_id FROM emailmonitor.article_observations a
 WHERE a.organization_id=p_org AND a.reused_from_job=marker.job_id ORDER BY a.job_id LIMIT 10 LOOP
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.deletion_tombstones WHERE organization_id=p_org AND job_id=item.job_id) THEN
 INSERT INTO emailmonitor.deletion_tombstones(organization_id,id,job_id,reason)
 VALUES(p_org,gen_random_uuid(),item.job_id,marker.reason);
 PERFORM emailmonitor.lifecycle_fence_job(p_org,item.job_id);
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,gen_random_uuid(),emailmonitor.job_actor(),'lifecycle.fenced',item.job_id);
 END IF;
 PERFORM emailmonitor.lifecycle_purge_job(p_org,item.job_id);
 UPDATE emailmonitor.deletion_tombstones SET stage='purged',purged_at=clock_timestamp()
 WHERE organization_id=p_org AND job_id=item.job_id AND stage<>'purged';
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,gen_random_uuid(),emailmonitor.job_actor(),'lifecycle.purged',item.job_id);
 END LOOP;
 IF EXISTS(SELECT 1 FROM emailmonitor.article_observations a
 WHERE a.organization_id=p_org AND a.reused_from_job=marker.job_id) THEN
 RETURN emailmonitor.lifecycle_receipt(p_org,p_id); END IF;
 PERFORM emailmonitor.lifecycle_purge_job(p_org,marker.job_id);
 ELSE
 -- A fixed bounded batch; tombstones preserve immediate refusal between calls.
 FOR item IN SELECT j.id FROM emailmonitor.jobs j WHERE j.organization_id=p_org AND NOT EXISTS(
 SELECT 1 FROM emailmonitor.deletion_tombstones d WHERE d.organization_id=p_org AND d.job_id=j.id AND d.stage='purged')
 ORDER BY CASE WHEN EXISTS(SELECT 1 FROM emailmonitor.article_observations a
 WHERE a.organization_id=p_org AND a.reused_from_job=j.id) THEN 1 ELSE 0 END,j.id LIMIT 10 LOOP
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.deletion_tombstones WHERE organization_id=p_org AND job_id=item.id) THEN
 INSERT INTO emailmonitor.deletion_tombstones(organization_id,id,job_id,reason) VALUES(p_org,gen_random_uuid(),item.id,marker.reason);
 PERFORM emailmonitor.lifecycle_fence_job(p_org,item.id); END IF;
 PERFORM emailmonitor.lifecycle_purge_job(p_org,item.id);
 UPDATE emailmonitor.deletion_tombstones SET stage='purged',purged_at=clock_timestamp() WHERE organization_id=p_org AND job_id=item.id;
 END LOOP;
 IF EXISTS(SELECT 1 FROM emailmonitor.jobs j WHERE j.organization_id=p_org AND NOT EXISTS(
 SELECT 1 FROM emailmonitor.deletion_tombstones d WHERE d.organization_id=p_org AND d.job_id=j.id AND d.stage='purged')) THEN
 RETURN emailmonitor.lifecycle_receipt(p_org,p_id); END IF;
 END IF;
 UPDATE emailmonitor.deletion_tombstones SET stage='purged',purged_at=clock_timestamp() WHERE organization_id=p_org AND id=p_id;
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,gen_random_uuid(),emailmonitor.job_actor(),'lifecycle.purged',COALESCE(marker.job_id,p_org));
 RETURN emailmonitor.lifecycle_receipt(p_org,p_id);
END $$;

-- Preserve legacy documents; disclose original time only for retained reuse.
CREATE OR REPLACE FUNCTION emailmonitor.result_contact_document(p_org uuid,p_batch uuid,p_association uuid)
 RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT jsonb_build_object('organization_id',a.organization_id,'job_id',b.job_id,'batch_id',a.batch_id,
 'association_id',a.id,'revision',a.revision,'candidate_id',a.candidate_id,'author_id',a.author_id,
 'author_name',au.display_name,'first_author',au.first_role,'corresponding_author',au.correspondence_role,
 'affiliations',COALESCE(au.record->'affiliations','[]'::jsonb),'raw_address',ca.raw_address,
 'normalized_address',ca.normalized_address,'state',a.state,'evidence_strength',a.record->'evidence_strength',
 'association_reason',a.record->'reason','evidence_ids',a.record->'evidence_ids','source_id','synthetic-publisher',
 'source_url',b.article_url,'policy_version',b.policy_version,'title',b.snapshot->'preferred_metadata'->'title',
 'observed_at',obs.observed_at,'syntax_status',ca.syntax_status,'identity_state','article_local_unresolved',
 'technical_status','not_checked','delivery_status','unverified','outreach_eligibility','not_assessed') || CASE WHEN obs.reused_from_job IS NOT NULL THEN jsonb_build_object('observation_origin','reused') ELSE '{}'::jsonb END
 FROM emailmonitor.author_email_associations a JOIN emailmonitor.association_batches b
 ON b.organization_id=a.organization_id AND b.id=a.batch_id JOIN emailmonitor.association_candidates ca
 ON ca.organization_id=a.organization_id AND ca.batch_id=a.batch_id AND ca.id=a.candidate_id
 LEFT JOIN emailmonitor.association_authors au ON au.organization_id=a.organization_id
 AND au.batch_id=a.batch_id AND au.id=a.author_id JOIN emailmonitor.article_observations obs
 ON obs.organization_id=b.organization_id AND obs.job_id=b.job_id AND obs.article_url=b.article_url
 WHERE a.organization_id=p_org AND a.batch_id=p_batch AND a.id=p_association
 AND a.state<>'suppressed' AND emailmonitor.association_visible(p_org,p_batch)
$$;

CREATE OR REPLACE FUNCTION emailmonitor.result_outcome_document(p_org uuid,p_job uuid,p_item uuid)
 RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT jsonb_build_object('organization_id',i.organization_id,'job_id',i.job_id,'item_id',i.id,
 'source_url',i.input_url,'state',i.state,'reason',i.reason,'batch_id',i.batch_id,'completed_at',i.completed_at,
 'inherited_job_id',i.inherited_job_id,'observation_status',obs.observation->'status',
 'technical_status','not_checked','outreach_eligibility','not_assessed') || CASE WHEN obs.reused_from_job IS NOT NULL THEN jsonb_build_object('observation_origin','reused','observed_at',obs.observed_at) ELSE '{}'::jsonb END
 FROM emailmonitor.execution_items i LEFT JOIN emailmonitor.article_observations obs
 ON obs.organization_id=i.organization_id AND obs.job_id=COALESCE(i.inherited_job_id,i.job_id)
 AND obs.article_url=i.input_url WHERE i.organization_id=p_org AND i.job_id=p_job AND i.id=p_item
 AND i.work_kind='article' AND emailmonitor.execution_read_allowed(p_org,p_job)
$$;

-- Publication revalidation must use the same outcome provenance projection.
CREATE OR REPLACE FUNCTION emailmonitor.publication_outcome_state(p_org uuid,p_job uuid,p_item uuid)
 RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT jsonb_build_object('organization_id',i.organization_id,'job_id',i.job_id,'item_id',i.id,
 'source_url',i.input_url,'state',i.state,'reason',i.reason,'batch_id',i.batch_id,'completed_at',i.completed_at,
 'inherited_job_id',i.inherited_job_id,'observation_status',obs.observation->'status',
 'technical_status','not_checked','outreach_eligibility','not_assessed') || CASE WHEN obs.reused_from_job IS NOT NULL THEN jsonb_build_object('observation_origin','reused','observed_at',obs.observed_at) ELSE '{}'::jsonb END
 FROM emailmonitor.execution_items i LEFT JOIN emailmonitor.article_observations obs
 ON obs.organization_id=i.organization_id AND obs.job_id=COALESCE(i.inherited_job_id,i.job_id)
 AND obs.article_url=i.input_url WHERE i.organization_id=p_org AND i.job_id=p_job AND i.id=p_item
 AND i.work_kind='article' AND emailmonitor.publication_job_state(p_org,p_job)
$$;

-- Audit reuse under the existing human work authority; no new grant.
CREATE OR REPLACE FUNCTION emailmonitor.work_audit(p_org uuid,p_resource uuid,p_action text,p_id uuid)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF p_action IS NULL OR p_action NOT IN ('discovery.planned','discovery.page_committed',
 'discovery.delivery.received','extraction.observation_committed','extraction.retained_reused')
 THEN RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 IF p_action='extraction.retained_reused' AND (
 NOT COALESCE(emailmonitor.human_work_tenant_allowed(p_org),false)
 OR NOT COALESCE(emailmonitor.job_write_allowed(p_org,p_resource),false)
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.article_observations a
 WHERE a.organization_id=p_org AND a.job_id=p_resource AND a.reused_from_job IS NOT NULL)
 OR NOT emailmonitor.retained_reuse_current(p_org,p_resource)) THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 IF emailmonitor.service_selected(p_org) THEN
 IF p_action NOT IN ('discovery.page_committed','extraction.observation_committed')
 OR NOT emailmonitor.service_scope_allowed(p_org,p_resource,'extraction')
 THEN RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 PERFORM emailmonitor.job_permission_fence(p_org,p_resource);
 IF NOT COALESCE(emailmonitor.execution_write_allowed(p_org,p_resource),false) THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 ELSE
 -- Human delivery receipts identify an outbox event, not a job. Preserve their
 -- original tenant/current-actor audit semantics without a service lease fence.
 IF NOT COALESCE(emailmonitor.human_work_tenant_allowed(p_org),false) THEN
 RAISE EXCEPTION 'SERVICE_AUTHORITY_DENIED' USING ERRCODE='EM017'; END IF;
 END IF;
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,p_id,emailmonitor.work_actor(p_org),p_action,p_resource);
END $$;

-- Reuse jobs must have their retained observation before any worker is started.
CREATE OR REPLACE FUNCTION emailmonitor.execution_start(p_org uuid,p_job uuid,p_revision bigint,p_event uuid)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
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
 INSERT INTO emailmonitor.execution_runs(organization_id,job_id,root_job_id,policy_version,deletion_generation,expires_at)
 VALUES(p_org,p_job,p_job,d.policy_version,d.deletion_generation,clock_timestamp()+make_interval(days=>days));
 UPDATE emailmonitor.jobs SET state='ready' WHERE organization_id=p_org AND id=p_job;
 UPDATE emailmonitor.jobs SET state='queued' WHERE organization_id=p_org AND id=p_job;
 PERFORM emailmonitor.execution_sync(p_org,p_job);
 PERFORM emailmonitor.execution_emit(p_org,p_job,p_event,'job.queued');
END $$;

-- Preserve ordinary retry; unsupported reuse continuation fails closed.
CREATE OR REPLACE FUNCTION emailmonitor.execution_retry(p_org uuid,p_job uuid,p_revision bigint,p_new uuid,p_event uuid)
 RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE child uuid;
BEGIN
 -- A continuation must not queue reuse without its own materialized observation.
 -- The bounded reuse continuation is not implemented; fail before creating it.
 IF EXISTS(SELECT 1 FROM emailmonitor.jobs j WHERE j.organization_id=p_org AND j.id=p_job
 AND j.request ? 'reuse') THEN
 PERFORM emailmonitor.execution_control_fence(p_org,p_job);
 RAISE EXCEPTION 'EXECUTION_RETRY_DENIED' USING ERRCODE='EM010'; END IF;
 child:=emailmonitor.execution_retry_pre_entitlement(p_org,p_job,p_revision,p_new,p_event);
 -- A continuation cannot acquire a larger captured plan through a tenant upgrade.
 INSERT INTO emailmonitor.job_entitlements(organization_id,job_id,configuration_revision,entitlements)
 SELECT organization_id,child,configuration_revision,entitlements FROM emailmonitor.job_entitlements
 WHERE organization_id=p_org AND job_id=p_job ON CONFLICT DO NOTHING;
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.job_entitlements WHERE organization_id=p_org AND job_id=child)
 THEN RAISE EXCEPTION 'ENTITLEMENT_SNAPSHOT_REQUIRED' USING ERRCODE='EM013'; END IF;
 RETURN child;
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.service_schema_ready() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT (SELECT count(*)=1 AND min(version_num)='0022_retained_reuse' FROM public.alembic_version)
$$;
RESET ROLE;
