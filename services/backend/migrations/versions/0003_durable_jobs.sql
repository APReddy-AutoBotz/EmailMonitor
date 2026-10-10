-- Offline ledger only. No worker credentials, live acquisition or account provisioning.
SET ROLE emailmonitor_owner;
ALTER TABLE emailmonitor.organizations ADD COLUMN deletion_generation bigint NOT NULL DEFAULT 1 CHECK(deletion_generation>0);
CREATE FUNCTION emailmonitor.guard_deletion_generation() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF NEW.deletion_generation<>OLD.deletion_generation THEN RAISE EXCEPTION 'DELETION_GENERATION_IMMUTABLE'; END IF;
 IF NEW.status<>OLD.status AND NEW.status IN ('offboarding','deleted') THEN
 NEW.deletion_generation=OLD.deletion_generation+1; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER deletion_generation_guard BEFORE UPDATE ON emailmonitor.organizations
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_deletion_generation();
REVOKE ALL ON FUNCTION emailmonitor.guard_deletion_generation() FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
CREATE TABLE emailmonitor.jobs (
 organization_id uuid NOT NULL REFERENCES emailmonitor.organizations(id), id uuid NOT NULL,
 created_by uuid NOT NULL, kind text NOT NULL CHECK(kind IN ('extraction','fixture_probe')),
 request jsonb NOT NULL, source_id text, policy_version bigint,
 state text NOT NULL CHECK(state IN ('draft','awaiting_approval','ready','queued','running','pausing','paused','cancelling','cancelled','completed','completed_partial','failed')),
 generation bigint NOT NULL DEFAULT 1 CHECK(generation>0), row_version bigint NOT NULL DEFAULT 1,
 discovery_complete boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(organization_id,id),
 FOREIGN KEY(organization_id,created_by) REFERENCES emailmonitor.memberships(organization_id,identity_id),
 FOREIGN KEY(organization_id,source_id,policy_version) REFERENCES emailmonitor.source_policies(organization_id,source_id,version),
 CHECK(kind<>'fixture_probe' OR (source_id='synthetic-publisher' AND policy_version IS NOT NULL)),
 CHECK(kind<>'extraction' OR state IN ('draft','cancelled'))
);
CREATE TABLE emailmonitor.job_items (
 organization_id uuid NOT NULL, job_id uuid NOT NULL, id uuid NOT NULL,
 input_digest text NOT NULL CHECK(input_digest ~ '^[0-9a-f]{64}$'),
 state text NOT NULL CHECK(state IN ('pending','running','retry_wait','succeeded','no_contact','needs_review','policy_blocked','access_blocked','unsupported','skipped','failed','cancelled')),
 lease_token uuid, lease_until timestamptz, lease_generation bigint, lease_deletion_generation bigint,
 completed_lease_token uuid,
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
 result jsonb, effect_key text, PRIMARY KEY(organization_id,job_id,id),
 FOREIGN KEY(organization_id,job_id) REFERENCES emailmonitor.jobs,
 CHECK((state='running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL AND lease_generation IS NOT NULL AND lease_deletion_generation IS NOT NULL) OR
 (state<>'running' AND lease_token IS NULL AND lease_until IS NULL AND lease_generation IS NULL AND lease_deletion_generation IS NULL)),
 CHECK(state<>'succeeded' OR (result IS NOT NULL AND effect_key IS NOT NULL AND completed_lease_token IS NOT NULL))
);
CREATE TABLE emailmonitor.job_idempotency (
 organization_id uuid NOT NULL, actor_id uuid NOT NULL, route text NOT NULL,
 key_hash text NOT NULL, payload_hash text NOT NULL, job_id uuid NOT NULL,
 expires_at timestamptz NOT NULL DEFAULT now()+interval '24 hours',
 PRIMARY KEY(organization_id,actor_id,route,key_hash),
 FOREIGN KEY(organization_id,actor_id) REFERENCES emailmonitor.memberships(organization_id,identity_id),
 FOREIGN KEY(organization_id,job_id) REFERENCES emailmonitor.jobs
);
CREATE TABLE emailmonitor.job_outbox (
 organization_id uuid NOT NULL, event_id uuid NOT NULL, job_id uuid NOT NULL, item_id uuid NOT NULL,
 generation bigint NOT NULL, aggregate_version bigint NOT NULL CHECK(aggregate_version>0), event_type text NOT NULL CHECK(event_type IN ('job.queued','job.item_terminal')), published_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(organization_id,event_id),
 FOREIGN KEY(organization_id,job_id,item_id) REFERENCES emailmonitor.job_items
);
CREATE TABLE emailmonitor.fixture_quota (
 organization_id uuid PRIMARY KEY REFERENCES emailmonitor.organizations(id),
 maximum integer NOT NULL DEFAULT 500 CHECK(maximum BETWEEN 1 AND 500),
 reserved integer NOT NULL DEFAULT 0 CHECK(reserved>=0), used integer NOT NULL DEFAULT 0 CHECK(used>=0),
 CHECK(reserved+used<=maximum)
);
CREATE TABLE emailmonitor.usage_reservations (
 organization_id uuid NOT NULL, job_id uuid NOT NULL, item_id uuid NOT NULL,
 state text NOT NULL CHECK(state IN ('reserved','consumed','released')),
 PRIMARY KEY(organization_id,job_id,item_id),
 FOREIGN KEY(organization_id,job_id,item_id) REFERENCES emailmonitor.job_items
);
CREATE TABLE emailmonitor.usage_events (
 organization_id uuid NOT NULL, effect_key text NOT NULL, job_id uuid NOT NULL, item_id uuid NOT NULL,
 units integer NOT NULL CHECK(units=1), PRIMARY KEY(organization_id,effect_key),
 UNIQUE(organization_id,job_id,item_id),
 FOREIGN KEY(organization_id,job_id,item_id) REFERENCES emailmonitor.job_items
);
CREATE FUNCTION emailmonitor.job_actor() RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
 SELECT identity_id FROM emailmonitor.resolve_session(current_setting('emailmonitor.session_hash',true))
$$;
CREATE FUNCTION emailmonitor.job_creator_allowed(p_org uuid,p_actor uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.tenant_allowed(p_org) AND emailmonitor.session_role(p_org)
 IN ('owner','admin','data_steward','operator') AND p_actor=emailmonitor.job_actor()
$$;
CREATE FUNCTION emailmonitor.job_write_allowed(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.tenant_allowed(p_org) AND EXISTS(SELECT 1 FROM emailmonitor.jobs j
 WHERE j.organization_id=p_org AND j.id=p_job AND
 (emailmonitor.session_role(p_org) IN ('owner','admin','data_steward') OR
  (emailmonitor.session_role(p_org)='operator' AND j.created_by=emailmonitor.job_actor())))
$$;
CREATE FUNCTION emailmonitor.job_permission_fence(p_org uuid,p_job uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE actor uuid; source text;
BEGIN
 IF NOT COALESCE(emailmonitor.job_write_allowed(p_org,p_job),false) THEN
 RAISE EXCEPTION 'JOB_UNAVAILABLE'; END IF;
 actor=emailmonitor.job_actor();
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE;
 PERFORM 1 FROM emailmonitor.memberships WHERE organization_id=p_org AND identity_id=actor FOR SHARE;
 PERFORM 1 FROM emailmonitor.identities WHERE id=actor FOR SHARE;
 PERFORM 1 FROM emailmonitor.sessions WHERE token_hash=current_setting('emailmonitor.session_hash',true) FOR SHARE;
 SELECT source_id INTO source FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 IF source IS NOT NULL THEN
 PERFORM 1 FROM emailmonitor.source_catalog WHERE source_id=source FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policy_heads WHERE organization_id=p_org AND source_id=source FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policies p JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
 WHERE p.organization_id=p_org AND p.source_id=source AND p.version=h.current_version FOR SHARE OF p;
 END IF;
 IF NOT COALESCE(emailmonitor.job_write_allowed(p_org,p_job),false) OR NOT EXISTS(
 SELECT 1 FROM emailmonitor.sessions WHERE token_hash=current_setting('emailmonitor.session_hash',true)
 AND revoked_at IS NULL AND expires_at>clock_timestamp()) THEN RAISE EXCEPTION 'JOB_UNAVAILABLE'; END IF;
END $$;
CREATE FUNCTION emailmonitor.fixture_reserve(p_org uuid,p_job uuid,p_item uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF NOT COALESCE(emailmonitor.job_write_allowed(p_org,p_job),false) OR NOT EXISTS(
 SELECT 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job AND kind='fixture_probe')
 THEN RAISE EXCEPTION 'JOB_UNAVAILABLE'; END IF;
 INSERT INTO emailmonitor.fixture_quota(organization_id) VALUES(p_org) ON CONFLICT DO NOTHING;
 PERFORM 1 FROM emailmonitor.fixture_quota WHERE organization_id=p_org FOR UPDATE;
 IF EXISTS(SELECT 1 FROM emailmonitor.usage_reservations WHERE
 organization_id=p_org AND job_id=p_job AND item_id=p_item) THEN RETURN; END IF;
 IF EXISTS(SELECT 1 FROM emailmonitor.fixture_quota WHERE organization_id=p_org AND reserved+used>=maximum) THEN RAISE EXCEPTION 'QUOTA_EXHAUSTED'; END IF;
 UPDATE emailmonitor.fixture_quota SET reserved=reserved+1 WHERE organization_id=p_org;
 INSERT INTO emailmonitor.usage_reservations VALUES(p_org,p_job,p_item,'reserved');
END $$;
CREATE FUNCTION emailmonitor.fixture_settle(p_org uuid,p_job uuid,p_item uuid,p_effect text)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE reservation text;
BEGIN
 IF NOT COALESCE(emailmonitor.job_write_allowed(p_org,p_job),false) THEN
 RAISE EXCEPTION 'JOB_UNAVAILABLE'; END IF;
 PERFORM 1 FROM emailmonitor.fixture_quota WHERE organization_id=p_org FOR UPDATE;
 SELECT state INTO reservation FROM emailmonitor.usage_reservations WHERE
 organization_id=p_org AND job_id=p_job AND item_id=p_item FOR UPDATE;
 IF reservation<>'reserved' OR reservation IS NULL THEN
 IF p_effect IS NOT NULL AND reservation='consumed' AND EXISTS(SELECT 1 FROM emailmonitor.usage_events
 WHERE organization_id=p_org AND effect_key=p_effect AND job_id=p_job AND item_id=p_item)
 THEN RETURN; END IF;
 IF p_effect IS NULL AND reservation='released' THEN RETURN; END IF;
 RAISE EXCEPTION 'RESERVATION_REQUIRED'; END IF;
 IF p_effect IS NOT NULL THEN
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.job_items WHERE organization_id=p_org AND job_id=p_job
 AND id=p_item AND state='succeeded' AND effect_key=p_effect) THEN
 RAISE EXCEPTION 'COMMITTED_RESULT_REQUIRED'; END IF;
 INSERT INTO emailmonitor.usage_events VALUES(p_org,p_effect,p_job,p_item,1);
 END IF;
 UPDATE emailmonitor.usage_reservations SET state=CASE WHEN p_effect IS NULL THEN 'released' ELSE 'consumed' END
 WHERE organization_id=p_org AND job_id=p_job AND item_id=p_item;
 UPDATE emailmonitor.fixture_quota SET reserved=reserved-1,used=used+CASE WHEN p_effect IS NULL THEN 0 ELSE 1 END
 WHERE organization_id=p_org;
END $$;
CREATE FUNCTION emailmonitor.guard_job() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF TG_OP='UPDATE' THEN
 IF (NEW.organization_id,NEW.id,NEW.created_by,NEW.kind,NEW.request,NEW.source_id,NEW.policy_version,NEW.created_at)
 IS DISTINCT FROM (OLD.organization_id,OLD.id,OLD.created_by,OLD.kind,OLD.request,OLD.source_id,OLD.policy_version,OLD.created_at)
 THEN RAISE EXCEPTION 'JOB_INPUT_IMMUTABLE'; END IF;
 IF OLD.state IN ('cancelled','completed','completed_partial','failed') THEN RAISE EXCEPTION 'TERMINAL_JOB'; END IF;
 IF NEW.state<>OLD.state AND NOT (
 (OLD.state='draft' AND NEW.state IN ('awaiting_approval','cancelled')) OR
 (OLD.state='awaiting_approval' AND NEW.state IN ('ready','cancelled')) OR
 (OLD.state='ready' AND NEW.state IN ('queued','cancelled')) OR
 (OLD.state='queued' AND NEW.state IN ('running','pausing','cancelling')) OR
 (OLD.state='running' AND NEW.state IN ('pausing','cancelling','completed','completed_partial','failed')) OR
 (OLD.state='pausing' AND NEW.state IN ('paused','cancelling')) OR
 (OLD.state='paused' AND NEW.state IN ('queued','cancelling')) OR
 (OLD.state='cancelling' AND NEW.state='cancelled')) THEN RAISE EXCEPTION 'INVALID_JOB_TRANSITION'; END IF;
 IF NEW.generation<>OLD.generation+(CASE WHEN (NEW.state IN ('pausing','cancelling') OR (NEW.state='cancelled' AND OLD.state='draft')) AND NEW.state<>OLD.state THEN 1 ELSE 0 END)
 THEN RAISE EXCEPTION 'GENERATION_REQUIRED'; END IF;
 NEW.row_version=OLD.row_version+1;
 ELSE
 IF NEW.generation<>1 OR NEW.row_version<>1 OR NEW.state NOT IN ('draft','queued')
 OR (NEW.kind='extraction' AND NEW.state<>'draft') THEN RAISE EXCEPTION 'INITIAL_JOB_REQUIRED'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER job_guard BEFORE INSERT OR UPDATE ON emailmonitor.jobs
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_job();
CREATE FUNCTION emailmonitor.guard_job_item() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE parent emailmonitor.jobs;
BEGIN
 SELECT * INTO parent FROM emailmonitor.jobs WHERE organization_id=NEW.organization_id AND id=NEW.job_id FOR SHARE;
 IF parent.kind<>'fixture_probe' THEN RAISE EXCEPTION 'PLANNING_UNAVAILABLE'; END IF;
 IF TG_OP='INSERT' THEN
 IF NEW.state<>'pending' OR NEW.attempts<>0 OR NEW.result IS NOT NULL OR NEW.effect_key IS NOT NULL
 THEN RAISE EXCEPTION 'INITIAL_ITEM_REQUIRED'; END IF;
 ELSE
 IF (NEW.organization_id,NEW.job_id,NEW.id,NEW.input_digest) IS DISTINCT FROM
 (OLD.organization_id,OLD.job_id,OLD.id,OLD.input_digest) THEN RAISE EXCEPTION 'ITEM_INPUT_IMMUTABLE'; END IF;
 IF OLD.state IN ('succeeded','failed','cancelled') THEN RAISE EXCEPTION 'TERMINAL_ITEM'; END IF;
 IF NEW.attempts<>OLD.attempts+(CASE WHEN NEW.state='running' AND OLD.state IN ('pending','retry_wait')
 THEN 1 ELSE 0 END) THEN RAISE EXCEPTION 'ATTEMPT_FENCE'; END IF;
 END IF;
 IF NEW.state='running' AND (parent.state NOT IN ('queued','running') OR
 NEW.lease_generation<>parent.generation OR NEW.lease_deletion_generation<>(SELECT deletion_generation FROM emailmonitor.organizations WHERE id=NEW.organization_id) OR NEW.lease_until<=clock_timestamp() OR
 NEW.lease_until>clock_timestamp()+interval '301 seconds') THEN RAISE EXCEPTION 'LEASE_FENCE'; END IF;
 IF NEW.state='succeeded' THEN
 PERFORM emailmonitor.job_permission_fence(NEW.organization_id,NEW.job_id);
 IF COALESCE(OLD.state<>'running' OR parent.state<>'running' OR
 OLD.lease_until<=clock_timestamp() OR OLD.lease_generation<>parent.generation OR
 OLD.lease_deletion_generation<>(SELECT deletion_generation FROM emailmonitor.organizations WHERE id=NEW.organization_id) OR
 NEW.completed_lease_token IS DISTINCT FROM OLD.lease_token OR NOT EXISTS(
 SELECT 1 FROM emailmonitor.source_policies p JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
 JOIN emailmonitor.source_catalog s USING(source_id) WHERE p.organization_id=NEW.organization_id
 AND p.source_id=parent.source_id AND p.version=parent.policy_version AND p.version=h.current_version
 AND p.state='approved' AND p.valid_until>clock_timestamp() AND s.enabled
 AND p.policy->'allowed_operations' ? 'fetch_html'),true) THEN RAISE EXCEPTION 'TERMINAL_LEASE_FENCE'; END IF;
 END IF;
 IF NEW.state='succeeded' AND (NEW.result<>'{"diagnostic":"persistence-only"}'::jsonb OR
 NEW.effect_key !~ '^[0-9a-f]{64}$') THEN RAISE EXCEPTION 'FIXTURE_RESULT_REQUIRED'; END IF;
 IF NEW.state<>'succeeded' AND (NEW.result IS NOT NULL OR NEW.effect_key IS NOT NULL OR NEW.completed_lease_token IS NOT NULL)
 THEN RAISE EXCEPTION 'COMMIT_REQUIRED'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER item_guard BEFORE INSERT OR UPDATE ON emailmonitor.job_items
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_job_item();
CREATE FUNCTION emailmonitor.guard_job_outbox() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF TG_OP='UPDATE' AND (NEW.organization_id,NEW.event_id,NEW.job_id,NEW.item_id,NEW.generation,NEW.aggregate_version,NEW.event_type,NEW.created_at)
 IS DISTINCT FROM (OLD.organization_id,OLD.event_id,OLD.job_id,OLD.item_id,OLD.generation,OLD.aggregate_version,OLD.event_type,OLD.created_at)
 THEN RAISE EXCEPTION 'OUTBOX_EVENT_IMMUTABLE'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER outbox_guard BEFORE UPDATE ON emailmonitor.job_outbox
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_job_outbox();
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['jobs','job_items','job_idempotency','job_outbox','fixture_quota','usage_reservations','usage_events'] LOOP
 EXECUTE format('ALTER TABLE emailmonitor.%I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('ALTER TABLE emailmonitor.%I FORCE ROW LEVEL SECURITY',t);
 EXECUTE format('CREATE POLICY owner_all ON emailmonitor.%I TO emailmonitor_owner USING(true) WITH CHECK(true)',t);
 EXECUTE format('CREATE POLICY tenant_read ON emailmonitor.%I FOR SELECT TO emailmonitor_runtime USING(emailmonitor.tenant_allowed(organization_id))',t);
 EXECUTE format('REVOKE ALL ON emailmonitor.%I FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime',t);
 EXECUTE format('GRANT SELECT ON emailmonitor.%I TO emailmonitor_runtime',t);
 END LOOP;
 FOREACH t IN ARRAY ARRAY['job_items','job_outbox'] LOOP
 EXECUTE format('CREATE POLICY job_insert ON emailmonitor.%I FOR INSERT TO emailmonitor_runtime WITH CHECK(emailmonitor.job_write_allowed(organization_id,job_id))',t);
 EXECUTE format('CREATE POLICY job_update ON emailmonitor.%I FOR UPDATE TO emailmonitor_runtime USING(emailmonitor.job_write_allowed(organization_id,job_id)) WITH CHECK(emailmonitor.job_write_allowed(organization_id,job_id))',t);
 EXECUTE format('GRANT INSERT,UPDATE ON emailmonitor.%I TO emailmonitor_runtime',t);
 END LOOP;
END $$;
CREATE POLICY job_insert ON emailmonitor.jobs FOR INSERT TO emailmonitor_runtime
 WITH CHECK(emailmonitor.job_creator_allowed(organization_id,created_by));
CREATE POLICY job_update ON emailmonitor.jobs FOR UPDATE TO emailmonitor_runtime
 USING(emailmonitor.job_write_allowed(organization_id,id)) WITH CHECK(emailmonitor.job_write_allowed(organization_id,id));
CREATE POLICY idem_insert ON emailmonitor.job_idempotency FOR INSERT TO emailmonitor_runtime
 WITH CHECK(emailmonitor.job_creator_allowed(organization_id,actor_id) AND emailmonitor.job_write_allowed(organization_id,job_id));
CREATE POLICY idem_delete ON emailmonitor.job_idempotency FOR DELETE TO emailmonitor_runtime
 USING(emailmonitor.job_creator_allowed(organization_id,actor_id));
GRANT INSERT,UPDATE ON emailmonitor.jobs TO emailmonitor_runtime;
GRANT INSERT,DELETE ON emailmonitor.job_idempotency TO emailmonitor_runtime;
REVOKE ALL ON FUNCTION emailmonitor.job_actor(),emailmonitor.job_creator_allowed(uuid,uuid),
 emailmonitor.job_write_allowed(uuid,uuid),emailmonitor.job_permission_fence(uuid,uuid),emailmonitor.fixture_reserve(uuid,uuid,uuid),
 emailmonitor.fixture_settle(uuid,uuid,uuid,text),emailmonitor.guard_job(),emailmonitor.guard_job_item(),emailmonitor.guard_job_outbox()
 FROM PUBLIC,emailmonitor_authenticator;
GRANT EXECUTE ON FUNCTION emailmonitor.job_actor(),emailmonitor.job_creator_allowed(uuid,uuid),
 emailmonitor.job_write_allowed(uuid,uuid),emailmonitor.job_permission_fence(uuid,uuid),emailmonitor.fixture_reserve(uuid,uuid,uuid),
 emailmonitor.fixture_settle(uuid,uuid,uuid,text) TO emailmonitor_runtime;
RESET ROLE;
