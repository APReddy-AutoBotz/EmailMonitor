-- Synthetic discovery state only. Extraction jobs remain draft until later slices.
SET ROLE emailmonitor_owner;
CREATE TABLE emailmonitor.discovery (
 organization_id uuid NOT NULL, job_id uuid NOT NULL,
 generation bigint NOT NULL CHECK(generation>0), deletion_generation bigint NOT NULL CHECK(deletion_generation>0),
 source_id text NOT NULL CHECK(source_id='synthetic-publisher'), policy_version bigint NOT NULL CHECK(policy_version>0),
 plan jsonb NOT NULL CHECK(jsonb_typeof(plan)='object' AND octet_length(plan::text)<=16384),
 checkpoint jsonb NOT NULL CHECK(jsonb_typeof(checkpoint)='object' AND octet_length(checkpoint::text)<=1048576),
 max_pages integer NOT NULL CHECK(max_pages BETWEEN 1 AND 1000), max_articles integer NOT NULL CHECK(max_articles BETWEEN 1 AND 500),
 revision bigint NOT NULL DEFAULT 1 CHECK(revision>0),
 PRIMARY KEY(organization_id,job_id),
 FOREIGN KEY(organization_id,job_id) REFERENCES emailmonitor.jobs,
 FOREIGN KEY(organization_id,source_id,policy_version) REFERENCES emailmonitor.source_policies
);
CREATE FUNCTION emailmonitor.discovery_source_fence(p_org uuid,p_job uuid,p_version bigint)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 PERFORM emailmonitor.job_permission_fence(p_org,p_job);
 IF p_version IS NULL OR NOT EXISTS(SELECT 1 FROM emailmonitor.jobs
 WHERE organization_id=p_org AND id=p_job AND kind='extraction' AND state='draft')
 THEN RAISE EXCEPTION 'DISCOVERY_JOB_FENCE'; END IF;
 -- Exact server-owned source only; no arbitrary SQL/source arguments or data returned.
 PERFORM 1 FROM emailmonitor.source_catalog WHERE source_id='synthetic-publisher' FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policy_heads WHERE organization_id=p_org
 AND source_id='synthetic-publisher' FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policies p JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
 WHERE p.organization_id=p_org AND p.source_id='synthetic-publisher' AND p.version=h.current_version FOR SHARE OF p;
 IF NOT COALESCE(emailmonitor.job_write_allowed(p_org,p_job),false) OR NOT EXISTS(
 SELECT 1 FROM emailmonitor.source_policies p JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
 JOIN emailmonitor.source_catalog s USING(source_id)
 WHERE p.organization_id=p_org AND p.source_id='synthetic-publisher'
 AND p.version=p_version AND p.version=h.current_version AND s.enabled
 AND p.state='approved' AND p.valid_until>clock_timestamp()) THEN RAISE EXCEPTION 'DISCOVERY_POLICY_FENCE' USING ERRCODE='EM006'; END IF;
END $$;
REVOKE ALL ON FUNCTION emailmonitor.discovery_source_fence(uuid,uuid,bigint) FROM PUBLIC,emailmonitor_authenticator;
GRANT EXECUTE ON FUNCTION emailmonitor.discovery_source_fence(uuid,uuid,bigint) TO emailmonitor_runtime;
CREATE FUNCTION emailmonitor.guard_discovery() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
DECLARE parent emailmonitor.jobs;
BEGIN
 PERFORM emailmonitor.discovery_source_fence(NEW.organization_id,NEW.job_id,NEW.policy_version);
 SELECT * INTO parent FROM emailmonitor.jobs WHERE organization_id=NEW.organization_id AND id=NEW.job_id FOR SHARE;
 IF parent.kind<>'extraction' OR parent.state<>'draft' OR NEW.generation<>parent.generation
 OR NEW.deletion_generation<>(SELECT deletion_generation FROM emailmonitor.organizations WHERE id=NEW.organization_id)
 THEN RAISE EXCEPTION 'DISCOVERY_JOB_FENCE'; END IF;
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.source_policies p
 JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
 JOIN emailmonitor.source_catalog s USING(source_id)
 WHERE p.organization_id=NEW.organization_id AND p.source_id=NEW.source_id
 AND p.version=NEW.policy_version AND p.version=h.current_version AND s.enabled
 AND p.state='approved' AND p.valid_until>clock_timestamp()
 AND p.policy->'allowed_operations' ? 'fetch_html'
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
CREATE TRIGGER discovery_guard BEFORE INSERT OR UPDATE ON emailmonitor.discovery
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_discovery();
ALTER TABLE emailmonitor.discovery ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.discovery FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.discovery TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_read ON emailmonitor.discovery FOR SELECT TO emailmonitor_runtime USING(emailmonitor.tenant_allowed(organization_id));
CREATE POLICY job_insert ON emailmonitor.discovery FOR INSERT TO emailmonitor_runtime WITH CHECK(emailmonitor.job_write_allowed(organization_id,job_id));
CREATE POLICY job_update ON emailmonitor.discovery FOR UPDATE TO emailmonitor_runtime USING(emailmonitor.job_write_allowed(organization_id,job_id)) WITH CHECK(emailmonitor.job_write_allowed(organization_id,job_id));
REVOKE ALL ON emailmonitor.discovery FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT SELECT,INSERT,UPDATE ON emailmonitor.discovery TO emailmonitor_runtime;
REVOKE ALL ON FUNCTION emailmonitor.guard_discovery() FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
CREATE TABLE emailmonitor.discovery_outbox (
 organization_id uuid NOT NULL, job_id uuid NOT NULL, event_id uuid NOT NULL,
 generation bigint NOT NULL CHECK(generation>0), revision bigint NOT NULL CHECK(revision>0),
 published_at timestamptz, PRIMARY KEY(organization_id,event_id),
 UNIQUE(organization_id,job_id,generation,revision),
 FOREIGN KEY(organization_id,job_id) REFERENCES emailmonitor.discovery
);
CREATE FUNCTION emailmonitor.guard_discovery_outbox() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 PERFORM emailmonitor.job_permission_fence(NEW.organization_id,NEW.job_id);
 IF TG_OP='INSERT' THEN
 IF NEW.published_at IS NOT NULL OR NOT EXISTS(SELECT 1 FROM emailmonitor.discovery d
 JOIN emailmonitor.jobs j ON (j.organization_id,j.id)=(d.organization_id,d.job_id)
 WHERE d.organization_id=NEW.organization_id AND d.job_id=NEW.job_id
 AND d.generation=NEW.generation AND d.revision=NEW.revision
 AND d.checkpoint->>'status'='pending' AND j.state='draft')
 THEN RAISE EXCEPTION 'DISCOVERY_OUTBOX_FENCE'; END IF;
 ELSE
 IF (NEW.organization_id,NEW.job_id,NEW.event_id,NEW.generation,NEW.revision)
 IS DISTINCT FROM (OLD.organization_id,OLD.job_id,OLD.event_id,OLD.generation,OLD.revision)
 OR OLD.published_at IS NOT NULL OR NEW.published_at IS NULL
 THEN RAISE EXCEPTION 'DISCOVERY_OUTBOX_IMMUTABLE'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER discovery_outbox_guard BEFORE INSERT OR UPDATE ON emailmonitor.discovery_outbox
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_discovery_outbox();
ALTER TABLE emailmonitor.discovery_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.discovery_outbox FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.discovery_outbox TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_read ON emailmonitor.discovery_outbox FOR SELECT TO emailmonitor_runtime USING(emailmonitor.tenant_allowed(organization_id));
CREATE POLICY job_insert ON emailmonitor.discovery_outbox FOR INSERT TO emailmonitor_runtime WITH CHECK(emailmonitor.job_write_allowed(organization_id,job_id));
CREATE POLICY job_update ON emailmonitor.discovery_outbox FOR UPDATE TO emailmonitor_runtime USING(emailmonitor.job_write_allowed(organization_id,job_id)) WITH CHECK(emailmonitor.job_write_allowed(organization_id,job_id));
REVOKE ALL ON emailmonitor.discovery_outbox FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT SELECT,INSERT,UPDATE ON emailmonitor.discovery_outbox TO emailmonitor_runtime;
REVOKE ALL ON FUNCTION emailmonitor.guard_discovery_outbox() FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
RESET ROLE;
