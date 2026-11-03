SET ROLE emailmonitor_owner;

CREATE OR REPLACE FUNCTION emailmonitor.execution_confirmed(p_org uuid,p_job uuid,p_event uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE receipt_job emailmonitor.jobs; d emailmonitor.discovery; epoch bigint;
BEGIN
 -- The receipt changes only the outbox. Preserve execution_control_fence(false)
 -- predicates/order, but share the job fence with current worker authority reads.
 -- Control mutations still need an incompatible job lock until this commit.
 PERFORM emailmonitor.job_permission_fence(p_org,p_job);
 SELECT * INTO receipt_job FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR SHARE;
 SELECT * INTO d FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job FOR SHARE;
 SELECT deletion_generation INTO epoch FROM emailmonitor.organizations WHERE id=p_org;
 IF receipt_job.id IS NULL OR receipt_job.kind<>'extraction' OR d.job_id IS NULL OR d.deletion_generation<>epoch
 THEN RAISE EXCEPTION 'EXECUTION_SCOPE_DENIED' USING ERRCODE='EM010'; END IF;
 UPDATE emailmonitor.execution_outbox o SET published_at=COALESCE(published_at,clock_timestamp())
 WHERE o.organization_id=p_org AND o.job_id=p_job AND o.event_id=p_event
 AND EXISTS(SELECT 1 FROM emailmonitor.jobs j WHERE j.organization_id=p_org AND j.id=p_job AND j.generation=o.generation);
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.service_schema_ready() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT (SELECT count(*)=1 AND min(version_num)='0017_execution_receipt_lock' FROM public.alembic_version)
$$;
RESET ROLE;
