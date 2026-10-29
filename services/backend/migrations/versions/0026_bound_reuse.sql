-- Reuse only existing validated XML/PDF originals through the private proof.
-- The authored HTML allowlist and all existing tenant, policy, retention and
-- source/target identity predicates are unchanged. No table or function grants.
SET ROLE emailmonitor_owner;
CREATE OR REPLACE FUNCTION emailmonitor.guard_retained_reuse() RETURNS trigger
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
  OR NOT COALESCE(((source.observation->>'route'='html' AND NEW.article_url IN
   ('https://synthetic.publisher.example/article-a.html',
    'https://synthetic.publisher.example/article-b.html',
    'https://synthetic.publisher.example/no-contact.html'))
  OR (source.observation->>'route' IN ('pdf','article_xml') AND
   emailmonitor.retained_reuse_bound_source(NEW.organization_id,source.job_id,b.id,NEW.article_url))),false)
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
  OR source.observation->>'route' NOT IN ('html','pdf','article_xml') OR source.observation->>'status' NOT IN ('observed','no_contact')
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

CREATE OR REPLACE FUNCTION emailmonitor.service_schema_ready() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT (SELECT count(*)=1 AND min(version_num)='0026_bound_reuse' FROM public.alembic_version)
$$;
RESET ROLE;
