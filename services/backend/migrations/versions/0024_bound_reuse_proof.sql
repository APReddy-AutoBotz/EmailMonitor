-- Add a private proof for a future retained XML/PDF adapter. This migration
-- does not admit any new route: the existing 0022 insert guard still refuses
-- every non-HTML reuse. The ordinary observation/worker permissions are unchanged.
SET ROLE emailmonitor_owner;
CREATE FUNCTION emailmonitor.retained_reuse_bound_source(
 p_org uuid,p_job uuid,p_batch uuid,p_url text) RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT EXISTS(
  SELECT 1 FROM emailmonitor.article_observations a
  JOIN emailmonitor.association_batches b ON b.organization_id=a.organization_id
   AND b.job_id=a.job_id AND b.article_url=a.article_url AND b.id=p_batch
   AND b.source_revision=a.revision AND b.generation=a.generation
   AND b.policy_version=a.policy_version AND b.deletion_generation=a.deletion_generation
  JOIN emailmonitor.execution_items i ON i.organization_id=a.organization_id
   AND i.job_id=a.job_id AND i.input_url=a.article_url AND i.work_kind='article'
   AND i.id::text=a.observation->'binding'->>'item' AND i.batch_id=b.id
   AND i.inherited_job_id IS NULL AND i.inherited_item_id IS NULL
   AND i.state IN ('succeeded','needs_review','no_contact')
  WHERE a.organization_id=p_org AND a.job_id=p_job AND a.article_url=p_url
   AND a.reused_from_job IS NULL AND b.sealed
   AND a.expires_at>clock_timestamp() AND b.expires_at>clock_timestamp()
   AND a.observation->>'route' IN ('pdf','article_xml')
   AND a.observation->>'status' IN ('observed','no_contact')
   AND a.observation->>'url'=a.article_url
   AND a.source_digest=a.observation->>'content_digest'
   AND (a.observation->>'route'<>'article_xml'
    OR (a.observation->>'acquisition_digest'=a.source_digest
     AND (a.observation->'provider' IS NULL OR a.observation->'provider'='null'::jsonb
      OR a.observation->'provider'->>'source_id'=a.source_id)))
   AND a.observation->'binding'=jsonb_build_object(
    'organization',a.organization_id,'job',a.job_id,'item',i.id,
    'generation',a.generation,'deletion_generation',a.deletion_generation,
    'policy_version',a.policy_version,'discovery_revision',a.discovery_revision)
 )
$$;
REVOKE ALL ON FUNCTION emailmonitor.retained_reuse_bound_source(uuid,uuid,uuid,text)
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator,emailmonitor_worker,emailmonitor_publisher;

CREATE OR REPLACE FUNCTION emailmonitor.retained_reuse_current(p_org uuid,p_job uuid) RETURNS boolean
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
    AND CASE WHEN t.observation->>'route' IN ('pdf','article_xml')
     THEN emailmonitor.retained_reuse_bound_source(p_org,s.job_id,b.id,s.article_url)
     ELSE true END
    AND CASE WHEN s.reused_from_job IS NULL AND NOT EXISTS(
     SELECT 1 FROM emailmonitor.article_observations prior
      WHERE prior.organization_id=s.organization_id AND prior.job_id=s.job_id
       AND prior.reused_from_job IS NOT NULL)
     THEN emailmonitor.privacy_job_state(p_org,s.job_id) ELSE false END
  )
 )
$$;

CREATE OR REPLACE FUNCTION emailmonitor.service_schema_ready() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT (SELECT count(*)=1 AND min(version_num)='0024_bound_reuse_proof' FROM public.alembic_version)
$$;
RESET ROLE;
