-- Synthetic execution only. No source grants, new credentials or live enablement.
SET ROLE emailmonitor_owner;
CREATE TABLE emailmonitor.execution_runs (
 organization_id uuid NOT NULL, job_id uuid NOT NULL, root_job_id uuid NOT NULL,
 retry_from uuid, source_id text NOT NULL DEFAULT 'synthetic-publisher' CHECK(source_id='synthetic-publisher'),
 policy_version bigint NOT NULL, deletion_generation bigint NOT NULL,
 selected_urls jsonb CHECK(selected_urls IS NULL OR (jsonb_typeof(selected_urls)='array' AND jsonb_array_length(selected_urls) BETWEEN 1 AND 4)),
 last_sequence bigint NOT NULL DEFAULT 0 CHECK(last_sequence>=0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), expires_at timestamptz NOT NULL,
 PRIMARY KEY(organization_id,job_id), UNIQUE(organization_id,retry_from),
 FOREIGN KEY(organization_id,job_id) REFERENCES emailmonitor.jobs,
 FOREIGN KEY(organization_id,root_job_id) REFERENCES emailmonitor.jobs,
 FOREIGN KEY(organization_id,retry_from) REFERENCES emailmonitor.jobs,
 FOREIGN KEY(organization_id,source_id,policy_version) REFERENCES emailmonitor.source_policies(organization_id,source_id,version)
);
CREATE TABLE emailmonitor.execution_items (
 organization_id uuid NOT NULL, job_id uuid NOT NULL, id uuid NOT NULL,
 work_kind text NOT NULL CHECK(work_kind IN ('discover','article')),
 input_url text NOT NULL CHECK(input_url IN (
 'https://synthetic.publisher.example/search-page-1.html',
 'https://synthetic.publisher.example/search-page-2.html',
 'https://synthetic.publisher.example/article-a.html',
 'https://synthetic.publisher.example/article-b.html',
 'https://synthetic.publisher.example/tooltip.html',
 'https://synthetic.publisher.example/no-contact.html')),
 expected_discovery_revision bigint NOT NULL CHECK(expected_discovery_revision>0),
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','running','retry_wait','succeeded','no_contact','needs_review','policy_blocked','access_blocked','unsupported','skipped','failed','cancelled')),
 reason text NOT NULL DEFAULT 'scheduled' CHECK(reason IN ('scheduled','leased','observed','no_contact','requires_review','browser_not_completed','source_policy_changed','worker_failure','lease_exhausted','user_cancelled','pagination_committed')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
 lease_token uuid, lease_until timestamptz, lease_generation bigint, lease_deletion_generation bigint,
 batch_id uuid, effect_id uuid, completed_at timestamptz, inherited_job_id uuid, inherited_item_id uuid,
 PRIMARY KEY(organization_id,job_id,id), UNIQUE(organization_id,job_id,work_kind,input_url),
 FOREIGN KEY(organization_id,job_id) REFERENCES emailmonitor.execution_runs,
 FOREIGN KEY(organization_id,batch_id) REFERENCES emailmonitor.association_batches,
 FOREIGN KEY(organization_id,inherited_job_id,inherited_item_id) REFERENCES emailmonitor.execution_items,
 CHECK((inherited_job_id IS NULL)=(inherited_item_id IS NULL)),
 CHECK(inherited_job_id IS NULL OR state IN ('succeeded','no_contact','needs_review','unsupported','policy_blocked','access_blocked','skipped','cancelled')),
 CHECK((work_kind='discover' AND input_url LIKE 'https://synthetic.publisher.example/search-page-%.html') OR
 (work_kind='article' AND input_url NOT LIKE 'https://synthetic.publisher.example/search-page-%.html')),
 CHECK((state='running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL AND lease_generation IS NOT NULL AND lease_deletion_generation IS NOT NULL) OR
 (state<>'running' AND lease_token IS NULL AND lease_until IS NULL AND lease_generation IS NULL AND lease_deletion_generation IS NULL)),
 CHECK(effect_id IS NULL OR state IN ('succeeded','no_contact','needs_review','unsupported'))
);
CREATE TABLE emailmonitor.execution_outbox (
 organization_id uuid NOT NULL, job_id uuid NOT NULL, event_id uuid NOT NULL,
 item_id uuid NOT NULL, generation bigint NOT NULL, published_at timestamptz,
 deliveries integer NOT NULL DEFAULT 0 CHECK(deliveries>=0),
 PRIMARY KEY(organization_id,job_id,event_id),
 FOREIGN KEY(organization_id,job_id,item_id) REFERENCES emailmonitor.execution_items
);
CREATE TABLE emailmonitor.execution_events (
 organization_id uuid NOT NULL, job_id uuid NOT NULL, sequence bigint NOT NULL CHECK(sequence>0),
 event_id uuid NOT NULL, event_type text NOT NULL CHECK(event_type IN (
 'job.queued','job.discovery_progress','job.item_terminal','job.paused','job.cancelled','job.finished','association.reviewed')),
 aggregate_version bigint NOT NULL CHECK(aggregate_version>0),
 item_id uuid, batch_id uuid, association_id uuid, occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(organization_id,job_id,sequence), UNIQUE(organization_id,job_id,event_id),
 FOREIGN KEY(organization_id,job_id) REFERENCES emailmonitor.execution_runs,
 FOREIGN KEY(organization_id,job_id,item_id) REFERENCES emailmonitor.execution_items,
 FOREIGN KEY(organization_id,batch_id,association_id) REFERENCES emailmonitor.author_email_associations(organization_id,batch_id,id),
 CHECK((event_type='association.reviewed' AND batch_id IS NOT NULL AND association_id IS NOT NULL) OR
 (event_type<>'association.reviewed' AND batch_id IS NULL AND association_id IS NULL))
);
CREATE FUNCTION emailmonitor.execution_read_allowed(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(emailmonitor.tenant_allowed(p_org),false) AND EXISTS(
 SELECT 1 FROM emailmonitor.jobs j JOIN emailmonitor.discovery d
 ON d.organization_id=j.organization_id AND d.job_id=j.id
 JOIN emailmonitor.organizations o ON o.id=j.organization_id
 JOIN emailmonitor.source_policy_heads h ON h.organization_id=d.organization_id AND h.source_id=d.source_id
 JOIN emailmonitor.source_policies p ON p.organization_id=h.organization_id AND p.source_id=h.source_id AND p.version=h.current_version
 JOIN emailmonitor.source_catalog s ON s.source_id=p.source_id
 LEFT JOIN emailmonitor.execution_runs r ON r.organization_id=j.organization_id AND r.job_id=j.id
 WHERE j.organization_id=p_org AND j.id=p_job AND j.kind='extraction' AND o.status='active'
 AND d.deletion_generation=o.deletion_generation AND p.version=d.policy_version
 AND (r.job_id IS NULL OR (r.policy_version=p.version AND r.deletion_generation=o.deletion_generation AND r.expires_at>statement_timestamp()))
 AND p.state='approved' AND p.valid_until>statement_timestamp() AND s.enabled
 AND j.request->>'purpose'=p.policy->>'purpose'
 AND p.policy->'allowed_operations' ? 'fetch_html' AND p.policy->'allowed_operations' ? 'extract_contacts'
 AND 'fetch_html'=ANY(s.allowed_operations) AND 'extract_contacts'=ANY(s.allowed_operations)
 AND 'synthetic.publisher.example'=ANY(s.allowed_hosts) AND p.policy->'allowed_hosts' ? 'synthetic.publisher.example'
 AND (p.policy->'retention'->>'contact_days')::integer>0) AND EXISTS(
 SELECT 1 FROM emailmonitor.sessions ss JOIN emailmonitor.identities ii ON ii.id=ss.identity_id
 WHERE ss.token_hash=current_setting('emailmonitor.session_hash',true) AND ss.revoked_at IS NULL
 AND ss.expires_at>statement_timestamp() AND ii.active AND ss.permission_revision=ii.permission_revision)
$$;
CREATE FUNCTION emailmonitor.execution_write_allowed(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs;
BEGIN
 IF NOT COALESCE(emailmonitor.job_write_allowed(p_org,p_job),false) THEN RETURN false; END IF;
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 IF j.kind<>'extraction' OR j.id IS NULL THEN RETURN false; END IF;
 IF j.state='draft' THEN RETURN true; END IF;
 RETURN j.state='running' AND EXISTS(SELECT 1 FROM emailmonitor.execution_items i
 JOIN emailmonitor.execution_runs r ON r.organization_id=i.organization_id AND r.job_id=i.job_id
 JOIN emailmonitor.organizations o ON o.id=i.organization_id
 WHERE i.organization_id=p_org AND i.job_id=p_job AND i.state='running' AND i.lease_until>clock_timestamp()
 AND i.job_id::text=current_setting('emailmonitor.execution_job',true)
 AND i.id::text=current_setting('emailmonitor.execution_item',true)
 AND i.lease_token::text=current_setting('emailmonitor.execution_token',true)
 AND i.lease_generation::text=current_setting('emailmonitor.execution_generation',true)
 AND i.lease_deletion_generation::text=current_setting('emailmonitor.execution_deletion',true)
 AND i.lease_generation=j.generation AND i.lease_deletion_generation=o.deletion_generation
 AND r.deletion_generation=o.deletion_generation AND r.expires_at>clock_timestamp());
END $$;
CREATE FUNCTION emailmonitor.execution_emit(p_org uuid,p_job uuid,p_event uuid,p_type text,p_item uuid DEFAULT NULL,p_batch uuid DEFAULT NULL,p_association uuid DEFAULT NULL,p_version bigint DEFAULT NULL)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE seq bigint; ver bigint;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.execution_runs WHERE organization_id=p_org AND job_id=p_job)
 OR EXISTS(SELECT 1 FROM emailmonitor.execution_events WHERE organization_id=p_org AND job_id=p_job AND event_id=p_event)
 THEN RETURN; END IF;
 UPDATE emailmonitor.execution_runs SET last_sequence=last_sequence+1
 WHERE organization_id=p_org AND job_id=p_job RETURNING last_sequence INTO seq;
 SELECT COALESCE(p_version,row_version) INTO ver FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 INSERT INTO emailmonitor.execution_events(organization_id,job_id,sequence,event_id,event_type,aggregate_version,item_id,batch_id,association_id)
 VALUES(p_org,p_job,seq,p_event,p_type,ver,p_item,p_batch,p_association);
END $$;
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['execution_runs','execution_items','execution_outbox','execution_events'] LOOP
 EXECUTE format('ALTER TABLE emailmonitor.%I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('ALTER TABLE emailmonitor.%I FORCE ROW LEVEL SECURITY',t);
 EXECUTE format('CREATE POLICY owner_all ON emailmonitor.%I TO emailmonitor_owner USING(true) WITH CHECK(true)',t);
 EXECUTE format('CREATE POLICY tenant_read ON emailmonitor.%I FOR SELECT TO emailmonitor_runtime USING(emailmonitor.execution_read_allowed(organization_id,job_id))',t);
 EXECUTE format('REVOKE ALL ON emailmonitor.%I FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime',t);
 EXECUTE format('GRANT SELECT ON emailmonitor.%I TO emailmonitor_runtime',t);
 END LOOP;
END $$;
CREATE TABLE emailmonitor.execution_effects (
 organization_id uuid NOT NULL, root_job_id uuid NOT NULL, effect_id uuid NOT NULL,
 job_id uuid NOT NULL, item_id uuid NOT NULL, batch_id uuid NOT NULL,
 PRIMARY KEY(organization_id,root_job_id,effect_id),
 FOREIGN KEY(organization_id,root_job_id) REFERENCES emailmonitor.jobs,
 FOREIGN KEY(organization_id,job_id,item_id) REFERENCES emailmonitor.execution_items,
 FOREIGN KEY(organization_id,batch_id) REFERENCES emailmonitor.association_batches
);
ALTER TABLE emailmonitor.execution_effects ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.execution_effects FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.execution_effects TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_read ON emailmonitor.execution_effects FOR SELECT TO emailmonitor_runtime
 USING(emailmonitor.execution_read_allowed(organization_id,job_id));
REVOKE ALL ON emailmonitor.execution_effects FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT SELECT ON emailmonitor.execution_effects TO emailmonitor_runtime;
CREATE FUNCTION emailmonitor.execution_control_fence(p_org uuid,p_job uuid,p_policy boolean DEFAULT true)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs; d emailmonitor.discovery; epoch bigint;
BEGIN
 PERFORM emailmonitor.job_permission_fence(p_org,p_job);
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR UPDATE;
 SELECT * INTO d FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job FOR SHARE;
 SELECT deletion_generation INTO epoch FROM emailmonitor.organizations WHERE id=p_org;
 IF j.id IS NULL OR j.kind<>'extraction' OR d.job_id IS NULL OR d.deletion_generation<>epoch
 OR (p_policy AND NOT COALESCE(emailmonitor.execution_read_allowed(p_org,p_job),false))
 THEN RAISE EXCEPTION 'EXECUTION_SCOPE_DENIED' USING ERRCODE='EM010'; END IF;
END $$;
CREATE FUNCTION emailmonitor.execution_sync(p_org uuid,p_job uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE d emailmonitor.discovery; r emailmonitor.execution_runs; gen bigint; url text; unit uuid; event uuid;
BEGIN
 SELECT * INTO d FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job;
 SELECT * INTO r FROM emailmonitor.execution_runs WHERE organization_id=p_org AND job_id=p_job;
 SELECT generation INTO gen FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 IF r.job_id IS NULL OR d.job_id IS NULL THEN RAISE EXCEPTION 'EXECUTION_REQUIRED'; END IF;
 FOR url IN SELECT value FROM jsonb_array_elements_text(d.checkpoint->'articles') LOOP
 IF r.selected_urls IS NOT NULL AND NOT (r.selected_urls ? url) THEN CONTINUE; END IF;
 unit:=md5(p_org::text||':'||p_job::text||':article:'||url)::uuid;
 INSERT INTO emailmonitor.execution_items(organization_id,job_id,id,work_kind,input_url,expected_discovery_revision)
 VALUES(p_org,p_job,unit,'article',url,d.revision) ON CONFLICT DO NOTHING;
 END LOOP;
 IF r.selected_urls IS NULL AND d.checkpoint->>'status'='pending' THEN
 url:=d.checkpoint->>'next_url';
 IF url IS NULL THEN RAISE EXCEPTION 'DISCOVERY_CURSOR_REQUIRED'; END IF;
 unit:=md5(p_org::text||':'||p_job::text||':discover:'||url)::uuid;
 INSERT INTO emailmonitor.execution_items(organization_id,job_id,id,work_kind,input_url,expected_discovery_revision)
 VALUES(p_org,p_job,unit,'discover',url,d.revision) ON CONFLICT DO NOTHING;
 END IF;
 -- New work is reconstructed from durable checkpoints; no process-local queue is authority.
 FOR unit IN SELECT id FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=p_job
 AND state IN ('pending','retry_wait') AND attempts<3 LOOP
 event:=md5(p_org::text||':'||p_job::text||':'||unit::text||':'||gen::text)::uuid;
 INSERT INTO emailmonitor.execution_outbox(organization_id,job_id,event_id,item_id,generation)
 VALUES(p_org,p_job,event,unit,gen) ON CONFLICT DO NOTHING;
 END LOOP;
END $$;
CREATE FUNCTION emailmonitor.execution_start(p_org uuid,p_job uuid,p_revision bigint,p_event uuid)
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
 SELECT (policy->'retention'->>'contact_days')::integer INTO days FROM emailmonitor.source_policies
 WHERE organization_id=p_org AND source_id=d.source_id AND version=d.policy_version;
 INSERT INTO emailmonitor.execution_runs(organization_id,job_id,root_job_id,policy_version,deletion_generation,expires_at)
 VALUES(p_org,p_job,p_job,d.policy_version,d.deletion_generation,clock_timestamp()+make_interval(days=>days));
 UPDATE emailmonitor.jobs SET state='ready' WHERE organization_id=p_org AND id=p_job;
 UPDATE emailmonitor.jobs SET state='queued' WHERE organization_id=p_org AND id=p_job;
 PERFORM emailmonitor.execution_sync(p_org,p_job);
 PERFORM emailmonitor.execution_emit(p_org,p_job,p_event,'job.queued');
END $$;
CREATE FUNCTION emailmonitor.execution_claim(p_org uuid,p_job uuid,p_item uuid,p_event uuid,p_token uuid,p_seconds integer,p_generation bigint DEFAULT NULL)
 RETURNS TABLE(item_id uuid,work_kind text,input_url text,discovery_revision bigint,generation bigint,deletion_generation bigint)
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs; i emailmonitor.execution_items; epoch bigint;
BEGIN
 PERFORM emailmonitor.execution_control_fence(p_org,p_job);
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 IF p_generation IS NOT NULL AND p_generation<>j.generation THEN
 RAISE EXCEPTION 'EXECUTION_WORK_FENCE' USING ERRCODE='EM010'; END IF;
 SELECT * INTO i FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=p_job AND id=p_item FOR UPDATE;
 SELECT o.deletion_generation INTO epoch FROM emailmonitor.organizations o WHERE o.id=p_org;
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.execution_outbox e WHERE e.organization_id=p_org AND e.job_id=p_job
 AND e.item_id=p_item AND e.event_id=p_event AND e.generation=j.generation) THEN RAISE EXCEPTION 'EXECUTION_EVENT_DENIED'; END IF;
 UPDATE emailmonitor.execution_outbox SET deliveries=deliveries+1 WHERE organization_id=p_org AND job_id=p_job AND event_id=p_event;
 IF i.id IS NULL OR j.state NOT IN ('queued','running') OR i.state NOT IN ('pending','retry_wait') OR i.attempts>=3 THEN RETURN; END IF;
 IF p_token IS NULL OR p_seconds IS NULL OR p_seconds NOT BETWEEN 1 AND 120 THEN RAISE EXCEPTION 'BOUNDED_LEASE_REQUIRED'; END IF;
 IF j.state='queued' THEN UPDATE emailmonitor.jobs SET state='running' WHERE organization_id=p_org AND id=p_job; END IF;
 UPDATE emailmonitor.execution_items SET state='running',reason='leased',attempts=attempts+1,
 lease_token=p_token,lease_until=clock_timestamp()+make_interval(secs=>p_seconds),
 lease_generation=j.generation,lease_deletion_generation=epoch WHERE organization_id=p_org AND job_id=p_job AND id=p_item;
 RETURN QUERY SELECT i.id,i.work_kind,i.input_url,i.expected_discovery_revision,j.generation,epoch;
END $$;

-- Remove only the prototype draft/cancelled-only extraction constraint. All
-- enum, immutable-input, ownership and generation checks remain mandatory.
DO $$ DECLARE names text[]; BEGIN
 SELECT array_agg(conname) INTO names FROM pg_constraint WHERE conrelid='emailmonitor.jobs'::regclass
 AND contype='c' AND pg_get_constraintdef(oid) LIKE '%extraction%'
 AND pg_get_constraintdef(oid) LIKE '%state%' AND pg_get_constraintdef(oid) NOT LIKE '%fixture_probe%';
 IF cardinality(names) IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'EXACT_PROTOTYPE_CONSTRAINT_REQUIRED'; END IF;
 EXECUTE format('ALTER TABLE emailmonitor.jobs DROP CONSTRAINT %I',names[1]);
END $$;
CREATE OR REPLACE FUNCTION emailmonitor.guard_job() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF TG_OP='UPDATE' THEN
 IF (NEW.organization_id,NEW.id,NEW.created_by,NEW.kind,NEW.request,NEW.source_id,NEW.policy_version,NEW.created_at)
 IS DISTINCT FROM (OLD.organization_id,OLD.id,OLD.created_by,OLD.kind,OLD.request,OLD.source_id,OLD.policy_version,OLD.created_at)
 THEN RAISE EXCEPTION 'JOB_INPUT_IMMUTABLE'; END IF;
 IF NEW.kind='extraction' AND NEW.state IN ('ready','queued','running') AND (
 NOT EXISTS(SELECT 1 FROM emailmonitor.execution_runs WHERE organization_id=NEW.organization_id AND job_id=NEW.id)
 OR NOT COALESCE(emailmonitor.execution_read_allowed(NEW.organization_id,NEW.id),false))
 THEN RAISE EXCEPTION 'EXECUTION_REQUIRED'; END IF;
 IF NEW.kind='extraction' AND NEW.state IN ('completed','completed_partial','failed') THEN
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.execution_runs WHERE organization_id=NEW.organization_id AND job_id=NEW.id)
 OR EXISTS(SELECT 1 FROM emailmonitor.execution_items WHERE organization_id=NEW.organization_id
 AND job_id=NEW.id AND state IN ('pending','running','retry_wait'))
 THEN RAISE EXCEPTION 'TERMINAL_EXECUTION_REQUIRED'; END IF;
 IF NEW.state='completed' AND (NOT EXISTS(SELECT 1 FROM emailmonitor.discovery
 WHERE organization_id=NEW.organization_id AND job_id=NEW.id AND checkpoint->>'discovery_complete'='true')
 OR EXISTS(SELECT 1 FROM emailmonitor.execution_items WHERE organization_id=NEW.organization_id AND job_id=NEW.id
 AND state IN ('policy_blocked','access_blocked','unsupported','skipped','failed','cancelled')))
 THEN RAISE EXCEPTION 'COMPLETE_EXECUTION_REQUIRED'; END IF;
 END IF;
 IF NEW.kind='extraction' AND ((NEW.state='paused' AND EXISTS(SELECT 1 FROM emailmonitor.execution_items
 WHERE organization_id=NEW.organization_id AND job_id=NEW.id AND state='running')) OR
 (NEW.state='cancelled' AND OLD.state<>'draft' AND EXISTS(SELECT 1 FROM emailmonitor.execution_items
 WHERE organization_id=NEW.organization_id AND job_id=NEW.id AND state IN ('pending','running','retry_wait'))))
 THEN RAISE EXCEPTION 'CLEARED_LEASES_REQUIRED'; END IF;
 IF OLD.state IN ('cancelled','completed','completed_partial','failed') THEN RAISE EXCEPTION 'TERMINAL_JOB'; END IF;
 IF NEW.state<>OLD.state AND NOT (
 (OLD.state='draft' AND NEW.state IN ('awaiting_approval','ready','cancelled')) OR
 (OLD.state='awaiting_approval' AND NEW.state IN ('ready','cancelled')) OR
 (OLD.state='ready' AND (NEW.state IN ('queued','cancelled') OR (NEW.kind='extraction' AND NEW.state='cancelling'))) OR
 (OLD.state='queued' AND (NEW.state IN ('running','pausing','cancelling') OR
 (NEW.kind='extraction' AND NEW.state='completed_partial' AND EXISTS(SELECT 1 FROM emailmonitor.execution_runs WHERE organization_id=NEW.organization_id AND job_id=NEW.id)
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.execution_items WHERE organization_id=NEW.organization_id AND job_id=NEW.id AND state IN ('pending','running','retry_wait'))))) OR
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

CREATE OR REPLACE FUNCTION emailmonitor.discovery_source_fence(p_org uuid,p_job uuid,p_version bigint)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 PERFORM emailmonitor.job_permission_fence(p_org,p_job);
 IF p_version IS NULL OR NOT COALESCE(emailmonitor.execution_write_allowed(p_org,p_job),false)
 THEN RAISE EXCEPTION 'EXECUTION_WORK_FENCE' USING ERRCODE='EM010'; END IF;
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

CREATE OR REPLACE FUNCTION emailmonitor.guard_discovery() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
DECLARE parent emailmonitor.jobs;
BEGIN
 SELECT * INTO parent FROM emailmonitor.jobs WHERE organization_id=NEW.organization_id AND id=NEW.job_id FOR SHARE;
 IF TG_OP='UPDATE' AND NEW.generation<>OLD.generation THEN
 PERFORM emailmonitor.execution_control_fence(NEW.organization_id,NEW.job_id);
 IF parent.state<>'paused' OR NEW.generation<>parent.generation OR NEW.revision<>OLD.revision+1
 OR (to_jsonb(NEW)-'generation'-'revision') IS DISTINCT FROM (to_jsonb(OLD)-'generation'-'revision')
 THEN RAISE EXCEPTION 'DISCOVERY_REBASE_DENIED'; END IF;
 RETURN NEW;
 END IF;
 PERFORM emailmonitor.discovery_source_fence(NEW.organization_id,NEW.job_id,NEW.policy_version);
 SELECT * INTO parent FROM emailmonitor.jobs WHERE organization_id=NEW.organization_id AND id=NEW.job_id FOR SHARE;
 IF parent.state='running' AND NOT EXISTS(SELECT 1 FROM emailmonitor.execution_items i
 WHERE i.organization_id=NEW.organization_id AND i.job_id=NEW.job_id AND i.work_kind='discover'
 AND i.id::text=current_setting('emailmonitor.execution_item',true)
 AND i.input_url=OLD.checkpoint->>'next_url') THEN
 RAISE EXCEPTION 'EXECUTION_WORK_FENCE' USING ERRCODE='EM010'; END IF;
 IF parent.kind<>'extraction' OR NOT COALESCE(emailmonitor.execution_write_allowed(NEW.organization_id,NEW.job_id),false) OR NEW.generation<>parent.generation
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

CREATE OR REPLACE FUNCTION emailmonitor.association_parent_fence(p_org uuid,p_job uuid,p_url text,p_revision bigint,p_write boolean DEFAULT false)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE o emailmonitor.organizations; j emailmonitor.jobs; a emailmonitor.article_observations;
 p emailmonitor.source_policies; h emailmonitor.source_policy_heads; s emailmonitor.source_catalog;
 session_row emailmonitor.sessions; identity_row emailmonitor.identities;
BEGIN
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) THEN RAISE EXCEPTION 'ASSOCIATION_DENIED' USING ERRCODE='EM009'; END IF;
 SELECT * INTO o FROM emailmonitor.organizations WHERE id=p_org FOR SHARE;
 SELECT * INTO session_row FROM emailmonitor.sessions WHERE token_hash=current_setting('emailmonitor.session_hash',true) FOR SHARE;
 SELECT * INTO identity_row FROM emailmonitor.identities WHERE id=session_row.identity_id FOR SHARE;
 IF session_row.token_hash IS NULL OR session_row.revoked_at IS NOT NULL OR session_row.expires_at<=clock_timestamp()
 OR NOT COALESCE(identity_row.active,false) OR session_row.permission_revision<>identity_row.permission_revision
 OR NOT COALESCE(emailmonitor.tenant_allowed(p_org),false)
 THEN RAISE EXCEPTION 'ASSOCIATION_DENIED' USING ERRCODE='EM009'; END IF;
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR SHARE;
 SELECT * INTO s FROM emailmonitor.source_catalog WHERE source_id='synthetic-publisher' FOR SHARE;
 SELECT * INTO h FROM emailmonitor.source_policy_heads WHERE organization_id=p_org AND source_id='synthetic-publisher' FOR SHARE;
 SELECT * INTO p FROM emailmonitor.source_policies WHERE organization_id=p_org AND source_id='synthetic-publisher' AND version=h.current_version FOR SHARE;
 SELECT * INTO a FROM emailmonitor.article_observations WHERE organization_id=p_org AND job_id=p_job AND article_url=p_url FOR SHARE;
 IF o.status IS DISTINCT FROM 'active' OR j.id IS NULL OR a.article_url IS NULL
 OR j.kind<>'extraction'
 OR (p_write AND (NOT COALESCE(emailmonitor.execution_write_allowed(p_org,p_job),false)
 OR (j.state='draft' AND j.generation<>a.generation)
 OR (j.state='running' AND NOT EXISTS(SELECT 1 FROM emailmonitor.execution_items i
 WHERE i.organization_id=p_org AND i.job_id=p_job AND i.work_kind='article' AND i.input_url=p_url
 AND i.id::text=current_setting('emailmonitor.execution_item',true)))))
 OR a.deletion_generation<>o.deletion_generation
 OR a.revision<>p_revision OR a.expires_at<=clock_timestamp()
 OR NOT COALESCE(s.enabled,false) OR p.state IS DISTINCT FROM 'approved'
 OR p.valid_until<=clock_timestamp() OR p.version<>a.policy_version
 OR j.request->>'purpose' IS DISTINCT FROM p.policy->>'purpose'
 OR NOT COALESCE(p.policy->'allowed_operations' ? 'extract_contacts',false)
 OR NOT COALESCE('extract_contacts'=ANY(s.allowed_operations),false)
 OR NOT COALESCE('synthetic.publisher.example'=ANY(s.allowed_hosts),false)
 OR NOT COALESCE(p.policy->'allowed_hosts' ? 'synthetic.publisher.example',false)
 OR COALESCE((p.policy->'retention'->>'contact_days')::integer,0)<=0
 OR NOT COALESCE(s.support->'routes_by_operation'->'extract_contacts' ? replace(p_url,'https://synthetic.publisher.example',''),false)
 OR (a.observation->>'route'='browser_dom' AND (NOT COALESCE(p.policy->'allowed_operations' ? 'browser',false) OR NOT COALESCE('browser'=ANY(s.allowed_operations),false)))
 OR (jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")') AND (
 NOT COALESCE(p.policy->'allowed_operations' ? 'retain_excerpt',false) OR NOT COALESCE('retain_excerpt'=ANY(s.allowed_operations),false) OR COALESCE((p.policy->'retention'->>'excerpt_days')::integer,0)<=0))
 THEN RAISE EXCEPTION 'ASSOCIATION_DENIED' USING ERRCODE='EM009'; END IF;
END $$;

CREATE OR REPLACE FUNCTION emailmonitor.association_visible(p_org uuid,p_batch uuid) RETURNS boolean
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE b emailmonitor.association_batches;
BEGIN
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) THEN RETURN false; END IF;
 SELECT * INTO b FROM emailmonitor.association_batches WHERE organization_id=p_org AND id=p_batch;
 RETURN b.id IS NOT NULL AND b.sealed AND b.expires_at>statement_timestamp() AND EXISTS(
 SELECT 1 FROM emailmonitor.sessions ss JOIN emailmonitor.identities ii ON ii.id=ss.identity_id
 WHERE ss.token_hash=current_setting('emailmonitor.session_hash',true) AND ss.revoked_at IS NULL
 AND ss.expires_at>statement_timestamp() AND ii.active AND ss.permission_revision=ii.permission_revision) AND EXISTS(
 SELECT 1 FROM emailmonitor.article_observations a JOIN emailmonitor.jobs j ON j.organization_id=a.organization_id AND j.id=a.job_id
 JOIN emailmonitor.organizations o ON o.id=a.organization_id
 JOIN emailmonitor.source_policy_heads h ON h.organization_id=a.organization_id AND h.source_id=a.source_id
 JOIN emailmonitor.source_policies p ON p.organization_id=h.organization_id AND p.source_id=h.source_id AND p.version=h.current_version
 JOIN emailmonitor.source_catalog s ON s.source_id=p.source_id
 WHERE a.organization_id=p_org AND a.job_id=b.job_id AND a.article_url=b.article_url
 AND a.revision=b.source_revision AND a.policy_version=b.policy_version
 AND a.generation=b.generation AND j.kind='extraction' AND j.kind='extraction'
 AND a.deletion_generation=b.deletion_generation AND o.deletion_generation=b.deletion_generation AND o.status='active'
 AND a.expires_at>statement_timestamp() AND s.enabled AND p.state='approved' AND p.valid_until>statement_timestamp()
 AND p.version=b.policy_version AND a.policy_version=b.policy_version
 AND j.request->>'purpose'=p.policy->>'purpose' AND p.policy->'allowed_operations' ? 'extract_contacts'
 AND 'extract_contacts'=ANY(s.allowed_operations) AND 'synthetic.publisher.example'=ANY(s.allowed_hosts)
 AND p.policy->'allowed_hosts' ? 'synthetic.publisher.example'
 AND s.support->'routes_by_operation'->'extract_contacts' ? replace(b.article_url,'https://synthetic.publisher.example','')
 AND (p.policy->'retention'->>'contact_days')::integer>0
 AND (a.observation->>'route'<>'browser_dom' OR (p.policy->'allowed_operations' ? 'browser' AND 'browser'=ANY(s.allowed_operations)))
 AND (NOT jsonb_path_exists(a.observation,'$.**.excerpt ? (@ != "")') OR (
 p.policy->'allowed_operations' ? 'retain_excerpt' AND 'retain_excerpt'=ANY(s.allowed_operations) AND (p.policy->'retention'->>'excerpt_days')::integer>0)));
END $$;
CREATE OR REPLACE FUNCTION emailmonitor.guard_article_observation() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE d emailmonitor.discovery; j emailmonitor.jobs; source_hash text; p jsonb; days integer;
BEGIN
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
 OR NEW.observation->>'parser_version' IS DISTINCT FROM 'synthetic-html-v1'
 OR NEW.observation->>'identity_association_implemented' IS DISTINCT FROM 'false'
 OR COALESCE(NEW.observation->>'route','') NOT IN ('html','browser_dom')
 OR COALESCE(NEW.observation->>'status','') NOT IN ('observed','no_contact','requires_browser')
 OR COALESCE(jsonb_typeof(NEW.observation->'authors'),'')<>'array'
 OR COALESCE(jsonb_typeof(NEW.observation->'candidates'),'')<>'array'
 OR jsonb_array_length(NEW.observation->'authors') NOT BETWEEN 1 AND 100
 OR jsonb_array_length(NEW.observation->'candidates')>100
 OR COALESCE(NEW.observation->>'content_digest','') !~ '^[0-9a-f]{64}$'
 THEN RAISE EXCEPTION 'ARTICLE_OBSERVATION_FENCE'; END IF;
 SELECT policy INTO p FROM emailmonitor.source_policies WHERE organization_id=NEW.organization_id
 AND source_id='synthetic-publisher' AND version=NEW.policy_version;
 IF j.request->>'purpose' IS DISTINCT FROM p->>'purpose'
 OR NOT (p->'allowed_operations' ? 'extract_contacts')
 OR (p->'retention'->>'contact_days')::integer<=0
 OR NOT (p->'allowed_operations' ? 'fetch_html')
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
 WHEN 'https://synthetic.publisher.example/article-a.html' THEN '33c3bddb62834da34acb300b7c0bd7bb4c8728fb57e5ece43b8fc4e81920c3f0'
 WHEN 'https://synthetic.publisher.example/article-b.html' THEN '87cd02138f7cc3dfa921ccdf9b2a1613e21529c1c89c3f36fcf36fd0ba8530b1'
 WHEN 'https://synthetic.publisher.example/tooltip.html' THEN 'f5ef425b50becc43b78b5a94c120c698d2c11d3d394325112d02355a0c27a893'
 WHEN 'https://synthetic.publisher.example/no-contact.html' THEN 'e743113b240ab1e931df471a9a3d8bd0137fc89157d69803a9238de3c8985b01' END;
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
 OR (NEW.observation->>'status'<>'observed' AND jsonb_array_length(NEW.observation->'candidates')<>0)
 THEN RAISE EXCEPTION 'ARTICLE_OBSERVATION_PROVENANCE'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.observation->'candidates') candidate
 WHERE COALESCE(candidate->>'association_status','') NOT IN ('unmatched','needs_review')
 OR candidate->>'technical_status' IS DISTINCT FROM 'not_checked'
 OR candidate->>'delivery_status' IS DISTINCT FROM 'unverified'
 OR candidate->>'outreach_eligibility' IS DISTINCT FROM 'not_assessed')
 THEN RAISE EXCEPTION 'ARTICLE_OBSERVATION_NOT_ASSOCIATION'; END IF;
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
END $$;
CREATE FUNCTION emailmonitor.execution_settle(p_org uuid,p_job uuid,p_event uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs; d emailmonitor.discovery; target text;
BEGIN
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 SELECT * INTO d FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job;
 IF j.state NOT IN ('queued','running') OR EXISTS(SELECT 1 FROM emailmonitor.execution_items
 WHERE organization_id=p_org AND job_id=p_job AND state IN ('pending','running','retry_wait')) THEN RETURN; END IF;
 target:=CASE WHEN NOT COALESCE((d.checkpoint->>'discovery_complete')::boolean,false)
 OR EXISTS(SELECT 1 FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=p_job
 AND state IN ('policy_blocked','access_blocked','unsupported','skipped','failed','cancelled'))
 THEN 'completed_partial' ELSE 'completed' END;
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=p_job AND work_kind='article')
 AND EXISTS(SELECT 1 FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=p_job AND work_kind='discover' AND state='failed')
 THEN target:='failed'; END IF;
 IF j.state='queued' AND COALESCE(emailmonitor.execution_read_allowed(p_org,p_job),false) THEN
 UPDATE emailmonitor.jobs SET state='running' WHERE organization_id=p_org AND id=p_job;
 END IF;
 UPDATE emailmonitor.jobs SET state=target WHERE organization_id=p_org AND id=p_job;
 PERFORM emailmonitor.execution_emit(p_org,p_job,p_event,'job.finished');
END $$;
CREATE FUNCTION emailmonitor.execution_finish(p_org uuid,p_job uuid,p_item uuid,p_token uuid,
 p_batch uuid,p_failure text,p_event uuid) RETURNS text
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE i emailmonitor.execution_items; r emailmonitor.execution_runs; a emailmonitor.article_observations;
 b emailmonitor.association_batches; d emailmonitor.discovery; target text; why text; effect uuid;
BEGIN
 PERFORM emailmonitor.execution_control_fence(p_org,p_job,false);
 SELECT * INTO i FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=p_job AND id=p_item FOR UPDATE;
 SELECT * INTO r FROM emailmonitor.execution_runs WHERE organization_id=p_org AND job_id=p_job;
 IF i.id IS NULL OR i.state<>'running' OR i.lease_token IS DISTINCT FROM p_token
 OR p_item::text IS DISTINCT FROM current_setting('emailmonitor.execution_item',true)
 OR p_token::text IS DISTINCT FROM current_setting('emailmonitor.execution_token',true)
 OR NOT COALESCE(emailmonitor.execution_write_allowed(p_org,p_job),false)
 THEN RAISE EXCEPTION 'EXECUTION_WORK_FENCE' USING ERRCODE='EM010'; END IF;
 IF p_failure IS NOT NULL THEN
 IF p_batch IS NOT NULL OR p_failure NOT IN ('worker_failure','source_policy_changed')
 THEN RAISE EXCEPTION 'EXECUTION_FAILURE_INPUT'; END IF;
 IF p_failure='source_policy_changed' THEN
 IF COALESCE(emailmonitor.execution_read_allowed(p_org,p_job),false) THEN RAISE EXCEPTION 'POLICY_DENIAL_REQUIRED'; END IF;
 target:='policy_blocked'; why:='source_policy_changed';
 ELSE
 target:=CASE WHEN i.attempts<3 THEN 'retry_wait' ELSE 'failed' END;
 why:=CASE WHEN i.attempts<3 THEN 'worker_failure' ELSE 'lease_exhausted' END;
 END IF;
 ELSE
 IF NOT COALESCE(emailmonitor.execution_read_allowed(p_org,p_job),false) THEN RAISE EXCEPTION 'EXECUTION_SCOPE_DENIED' USING ERRCODE='EM010'; END IF;
 IF i.work_kind='discover' THEN
 SELECT * INTO d FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job;
 IF p_batch IS NOT NULL OR NOT (d.checkpoint->'pages' ? i.input_url) OR d.revision<=i.expected_discovery_revision
 THEN RAISE EXCEPTION 'COMMITTED_PAGE_REQUIRED'; END IF;
 target:='succeeded'; why:='pagination_committed';
 ELSE
 SELECT * INTO a FROM emailmonitor.article_observations WHERE organization_id=p_org AND job_id=p_job AND article_url=i.input_url;
 SELECT * INTO b FROM emailmonitor.association_batches WHERE organization_id=p_org AND id=p_batch;
 IF a.article_url IS NULL OR b.id IS NULL OR b.job_id<>p_job OR b.article_url<>i.input_url
 OR b.source_revision<>a.revision OR NOT COALESCE(emailmonitor.association_visible(p_org,p_batch),false)
 THEN RAISE EXCEPTION 'COMMITTED_ASSOCIATION_REQUIRED'; END IF;
 IF a.observation->>'status'='requires_browser' THEN target:='unsupported'; why:='browser_not_completed';
 ELSIF a.observation->>'status'='no_contact' THEN target:='no_contact'; why:='no_contact';
 ELSIF EXISTS(SELECT 1 FROM emailmonitor.author_email_associations x WHERE x.organization_id=p_org AND x.batch_id=p_batch
 AND x.state IN ('unmatched','needs_review')) THEN target:='needs_review'; why:='requires_review';
 ELSE target:='succeeded'; why:='observed'; END IF;
 effect:=md5(p_org::text||':'||r.root_job_id::text||':article:'||i.input_url)::uuid;
 INSERT INTO emailmonitor.execution_effects VALUES(p_org,r.root_job_id,effect,p_job,p_item,p_batch) ON CONFLICT DO NOTHING;
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.execution_effects WHERE organization_id=p_org AND root_job_id=r.root_job_id
 AND effect_id=effect AND job_id=p_job AND item_id=p_item AND batch_id=p_batch)
 THEN RAISE EXCEPTION 'EFFECT_IDENTITY_CONFLICT'; END IF;
 END IF;
 END IF;
 UPDATE emailmonitor.execution_items SET state=target,reason=why,batch_id=p_batch,effect_id=effect,
 lease_token=NULL,lease_until=NULL,lease_generation=NULL,lease_deletion_generation=NULL,
 completed_at=CASE WHEN target='retry_wait' THEN NULL ELSE clock_timestamp() END
 WHERE organization_id=p_org AND job_id=p_job AND id=p_item;
 IF target='retry_wait' THEN
 UPDATE emailmonitor.execution_outbox SET published_at=NULL WHERE organization_id=p_org AND job_id=p_job
 AND item_id=p_item AND generation=i.lease_generation;
 END IF;
 PERFORM emailmonitor.execution_sync(p_org,p_job);
 IF p_failure='source_policy_changed' THEN
 UPDATE emailmonitor.execution_items SET state='policy_blocked',reason='source_policy_changed',
 lease_token=NULL,lease_until=NULL,lease_generation=NULL,lease_deletion_generation=NULL,
 completed_at=clock_timestamp() WHERE organization_id=p_org AND job_id=p_job
 AND state IN ('pending','running','retry_wait');
 END IF;
 PERFORM emailmonitor.execution_emit(p_org,p_job,p_event,CASE WHEN i.work_kind='discover' THEN 'job.discovery_progress' ELSE 'job.item_terminal' END,p_item);
 PERFORM emailmonitor.execution_settle(p_org,p_job,md5(p_event::text||':finished')::uuid);
 RETURN target;
END $$;
CREATE FUNCTION emailmonitor.execution_control(p_org uuid,p_job uuid,p_revision bigint,p_action text,p_event uuid)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs; d emailmonitor.discovery;
BEGIN
 PERFORM emailmonitor.execution_control_fence(p_org,p_job,p_action<>'cancel');
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 SELECT * INTO d FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job;
 IF p_revision IS NULL OR j.row_version<>p_revision THEN RAISE EXCEPTION 'EXECUTION_REVISION' USING ERRCODE='EM409'; END IF;
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.execution_runs WHERE organization_id=p_org AND job_id=p_job)
 THEN RAISE EXCEPTION 'EXECUTION_REQUIRED'; END IF;
 IF p_action='pause' AND j.state IN ('queued','running') THEN
 UPDATE emailmonitor.jobs SET state='pausing',generation=generation+1 WHERE organization_id=p_org AND id=p_job;
 UPDATE emailmonitor.execution_items SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,
 reason=CASE WHEN attempts>=3 THEN 'lease_exhausted' ELSE 'scheduled' END,
 lease_token=NULL,lease_until=NULL,lease_generation=NULL,lease_deletion_generation=NULL
 WHERE organization_id=p_org AND job_id=p_job AND state='running';
 UPDATE emailmonitor.jobs SET state='paused' WHERE organization_id=p_org AND id=p_job;
 PERFORM emailmonitor.execution_emit(p_org,p_job,p_event,'job.paused');
 ELSIF p_action='resume' AND j.state='paused' THEN
 IF d.generation<>j.generation THEN
 UPDATE emailmonitor.discovery SET generation=j.generation,revision=revision+1
 WHERE organization_id=p_org AND job_id=p_job;
 END IF;
 UPDATE emailmonitor.execution_items SET expected_discovery_revision=(SELECT revision FROM emailmonitor.discovery
 WHERE organization_id=p_org AND job_id=p_job) WHERE organization_id=p_org AND job_id=p_job AND state IN ('pending','retry_wait')
 AND (work_kind='article' OR NOT ((SELECT checkpoint->'pages' FROM emailmonitor.discovery
 WHERE organization_id=p_org AND job_id=p_job) ? input_url));
 UPDATE emailmonitor.jobs SET state='queued' WHERE organization_id=p_org AND id=p_job;
 PERFORM emailmonitor.execution_sync(p_org,p_job);
 PERFORM emailmonitor.execution_emit(p_org,p_job,p_event,'job.queued');
 PERFORM emailmonitor.execution_settle(p_org,p_job,md5(p_event::text||':finished')::uuid);
 ELSIF p_action='cancel' AND j.state IN ('ready','queued','running','pausing','paused') THEN
 -- Capture every durable checkpoint unit before terminalizing the job.
 PERFORM emailmonitor.execution_sync(p_org,p_job);
 UPDATE emailmonitor.jobs SET state='cancelling',generation=generation+1 WHERE organization_id=p_org AND id=p_job;
 UPDATE emailmonitor.execution_items SET state='cancelled',reason='user_cancelled',lease_token=NULL,lease_until=NULL,
 lease_generation=NULL,lease_deletion_generation=NULL,completed_at=clock_timestamp()
 WHERE organization_id=p_org AND job_id=p_job AND state IN ('pending','running','retry_wait');
 UPDATE emailmonitor.jobs SET state='cancelled' WHERE organization_id=p_org AND id=p_job;
 PERFORM emailmonitor.execution_emit(p_org,p_job,p_event,'job.cancelled');
 ELSE RAISE EXCEPTION 'EXECUTION_CONTROL_STATE' USING ERRCODE='EM409'; END IF;
END $$;
CREATE FUNCTION emailmonitor.execution_reconcile(p_org uuid,p_job uuid,p_event uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 PERFORM emailmonitor.execution_control_fence(p_org,p_job,false);
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.execution_runs WHERE organization_id=p_org AND job_id=p_job)
 THEN RAISE EXCEPTION 'EXECUTION_REQUIRED'; END IF;
 IF EXISTS(SELECT 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job
 AND state IN ('cancelled','completed','completed_partial','failed')) THEN RETURN; END IF;
 IF NOT COALESCE(emailmonitor.execution_read_allowed(p_org,p_job),false) THEN
 PERFORM emailmonitor.execution_sync(p_org,p_job);
 UPDATE emailmonitor.execution_items SET state='policy_blocked',reason='source_policy_changed',lease_token=NULL,
 lease_until=NULL,lease_generation=NULL,lease_deletion_generation=NULL,completed_at=clock_timestamp()
 WHERE organization_id=p_org AND job_id=p_job AND state IN ('pending','running','retry_wait');
 ELSE
 UPDATE emailmonitor.execution_items SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'retry_wait' END,
 reason=CASE WHEN attempts>=3 THEN 'lease_exhausted' ELSE 'worker_failure' END,lease_token=NULL,
 lease_until=NULL,lease_generation=NULL,lease_deletion_generation=NULL
 WHERE organization_id=p_org AND job_id=p_job AND state='running' AND lease_until<=clock_timestamp();
 UPDATE emailmonitor.execution_outbox o SET published_at=NULL WHERE o.organization_id=p_org AND o.job_id=p_job
 AND EXISTS(SELECT 1 FROM emailmonitor.execution_items i WHERE i.organization_id=o.organization_id AND i.job_id=o.job_id
 AND i.id=o.item_id AND i.state IN ('pending','retry_wait') AND i.attempts<3
 AND o.generation=(SELECT generation FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job));
 IF EXISTS(SELECT 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job AND state IN ('queued','running'))
 THEN PERFORM emailmonitor.execution_sync(p_org,p_job); END IF;
 END IF;
 PERFORM emailmonitor.execution_settle(p_org,p_job,p_event);
END $$;
CREATE FUNCTION emailmonitor.execution_confirmed(p_org uuid,p_job uuid,p_event uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 PERFORM emailmonitor.execution_control_fence(p_org,p_job,false);
 UPDATE emailmonitor.execution_outbox o SET published_at=COALESCE(published_at,clock_timestamp())
 WHERE o.organization_id=p_org AND o.job_id=p_job AND o.event_id=p_event
 AND EXISTS(SELECT 1 FROM emailmonitor.jobs j WHERE j.organization_id=p_org AND j.id=p_job AND j.generation=o.generation);
END $$;
CREATE FUNCTION emailmonitor.execution_review_journal() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE job uuid;
BEGIN
 -- An inherited retained batch can contribute quality facts to several same-tenant
 -- lineage views. Invalidate every currently readable view in the review transaction.
 FOR job IN SELECT target FROM (
 SELECT b.job_id AS target FROM emailmonitor.association_batches b
 WHERE b.organization_id=NEW.organization_id AND b.id=NEW.batch_id
 UNION SELECT i.job_id AS target FROM emailmonitor.execution_items i
 WHERE i.organization_id=NEW.organization_id AND i.batch_id=NEW.batch_id) recipients
 WHERE COALESCE(emailmonitor.execution_read_allowed(NEW.organization_id,target),false)
 ORDER BY target LOOP
 PERFORM emailmonitor.execution_emit(NEW.organization_id,job,NEW.event_id,'association.reviewed',NULL,NEW.batch_id,NEW.association_id,NEW.revision);
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER association_progress_event AFTER INSERT ON emailmonitor.association_outbox
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.execution_review_journal();
CREATE FUNCTION emailmonitor.execution_read_fence(p_org uuid,p_job uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE actor uuid;
BEGIN
 IF NOT COALESCE(emailmonitor.execution_read_allowed(p_org,p_job),false) THEN
 RAISE EXCEPTION 'EXECUTION_SCOPE_DENIED' USING ERRCODE='EM010'; END IF;
 actor:=emailmonitor.job_actor();
 PERFORM 1 FROM emailmonitor.organizations WHERE id=p_org FOR SHARE;
 PERFORM 1 FROM emailmonitor.identities WHERE id=actor FOR SHARE;
 PERFORM 1 FROM emailmonitor.sessions WHERE token_hash=current_setting('emailmonitor.session_hash',true) FOR SHARE;
 PERFORM 1 FROM emailmonitor.memberships WHERE organization_id=p_org AND identity_id=actor FOR SHARE;
 PERFORM 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR SHARE;
 PERFORM 1 FROM emailmonitor.execution_runs WHERE organization_id=p_org AND job_id=p_job FOR SHARE;
 PERFORM 1 FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_catalog WHERE source_id='synthetic-publisher' FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policy_heads WHERE organization_id=p_org AND source_id='synthetic-publisher' FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policies p JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
 WHERE p.organization_id=p_org AND p.source_id='synthetic-publisher' AND p.version=h.current_version FOR SHARE OF p;
 IF NOT COALESCE(emailmonitor.execution_read_allowed(p_org,p_job),false) OR NOT EXISTS(
 SELECT 1 FROM emailmonitor.sessions WHERE token_hash=current_setting('emailmonitor.session_hash',true)
 AND revoked_at IS NULL AND expires_at>clock_timestamp()) THEN
 RAISE EXCEPTION 'EXECUTION_SCOPE_DENIED' USING ERRCODE='EM010'; END IF;
END $$;
CREATE FUNCTION emailmonitor.execution_retry(p_org uuid,p_job uuid,p_revision bigint,p_new uuid,p_event uuid)
 RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs; d emailmonitor.discovery; r emailmonitor.execution_runs; chosen jsonb; actor uuid; prior uuid; retry_page boolean;
BEGIN
 PERFORM emailmonitor.execution_control_fence(p_org,p_job);
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 SELECT * INTO d FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job;
 SELECT * INTO r FROM emailmonitor.execution_runs WHERE organization_id=p_org AND job_id=p_job;
 IF p_revision IS NULL OR j.row_version<>p_revision THEN RAISE EXCEPTION 'EXECUTION_REVISION' USING ERRCODE='EM409'; END IF;
 IF j.state NOT IN ('completed_partial','failed','cancelled') OR r.job_id IS NULL
 OR r.expires_at<=clock_timestamp() OR p_new IS NULL OR p_event IS NULL
 THEN RAISE EXCEPTION 'EXECUTION_RETRY_DENIED' USING ERRCODE='EM010'; END IF;
 SELECT job_id INTO prior FROM emailmonitor.execution_runs WHERE organization_id=p_org AND retry_from=p_job;
 IF prior IS NOT NULL THEN RETURN prior; END IF;
 -- Only exhausted transient failures are eligible. Existing committed article
 -- receipts are inherited by reference when resuming failed pagination, never rerun.
 SELECT EXISTS(SELECT 1 FROM emailmonitor.execution_items WHERE organization_id=p_org
 AND job_id=p_job AND work_kind='discover' AND state='failed' AND reason='lease_exhausted'
 AND input_url=d.checkpoint->>'next_url') INTO retry_page;
 SELECT jsonb_agg(i.input_url ORDER BY i.input_url) INTO chosen
 FROM emailmonitor.execution_items i WHERE i.organization_id=p_org AND i.job_id=p_job
 AND i.work_kind='article' AND i.state='failed' AND i.reason='lease_exhausted'
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.execution_effects e WHERE e.organization_id=p_org
 AND e.root_job_id=r.root_job_id AND e.effect_id=md5(p_org::text||':'||r.root_job_id::text||':article:'||i.input_url)::uuid);
 IF NOT retry_page AND (chosen IS NULL OR jsonb_array_length(chosen) NOT BETWEEN 1 AND 4) THEN
 RAISE EXCEPTION 'EXECUTION_RETRY_DENIED' USING ERRCODE='EM010'; END IF;
 actor:=emailmonitor.job_actor();
 INSERT INTO emailmonitor.jobs(organization_id,id,created_by,kind,request,state,discovery_complete)
 VALUES(p_org,p_new,actor,'extraction',j.request,'draft',j.discovery_complete);
 INSERT INTO emailmonitor.discovery(organization_id,job_id,generation,deletion_generation,source_id,policy_version,
 plan,checkpoint,max_pages,max_articles,revision)
 VALUES(p_org,p_new,1,d.deletion_generation,d.source_id,d.policy_version,d.plan,d.checkpoint,d.max_pages,d.max_articles,1);
 INSERT INTO emailmonitor.execution_runs(organization_id,job_id,root_job_id,retry_from,policy_version,
 deletion_generation,selected_urls,expires_at)
 VALUES(p_org,p_new,r.root_job_id,p_job,r.policy_version,r.deletion_generation,CASE WHEN retry_page THEN NULL ELSE chosen END,r.expires_at);
 UPDATE emailmonitor.jobs SET state='ready' WHERE organization_id=p_org AND id=p_new;
 UPDATE emailmonitor.jobs SET state='queued' WHERE organization_id=p_org AND id=p_new;
 PERFORM emailmonitor.execution_sync(p_org,p_new);
 IF retry_page THEN
 UPDATE emailmonitor.execution_items n SET state=old.state,reason=old.reason,attempts=0,
 batch_id=old.batch_id,effect_id=old.effect_id,completed_at=old.completed_at,
 inherited_job_id=old.job_id,inherited_item_id=old.id
 FROM emailmonitor.execution_items old WHERE n.organization_id=p_org AND n.job_id=p_new
 AND old.organization_id=p_org AND old.job_id=p_job AND n.work_kind='article'
 AND old.work_kind='article' AND old.input_url=n.input_url
 AND old.state IN ('succeeded','no_contact','needs_review','unsupported','policy_blocked','access_blocked','skipped','cancelled');
 DELETE FROM emailmonitor.execution_outbox o USING emailmonitor.execution_items n
 WHERE o.organization_id=p_org AND o.job_id=p_new AND n.organization_id=o.organization_id
 AND n.job_id=o.job_id AND n.id=o.item_id AND n.inherited_job_id IS NOT NULL;
 END IF;
 PERFORM emailmonitor.execution_emit(p_org,p_new,p_event,'job.queued');
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,p_event,actor,'job.retry_continuation_created',p_new);
 RETURN p_new;
END $$;
DO $$ DECLARE f record; BEGIN
 FOR f IN SELECT oid::regprocedure AS signature FROM pg_proc WHERE pronamespace='emailmonitor'::regnamespace
 AND proname IN ('execution_read_allowed','execution_read_fence','execution_write_allowed','execution_emit','execution_control_fence',
 'execution_sync','execution_start','execution_claim','execution_settle','execution_finish','execution_control',
 'execution_reconcile','execution_confirmed','execution_review_journal','execution_retry') LOOP
 EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator',f.signature);
 END LOOP;
END $$;
GRANT EXECUTE ON FUNCTION emailmonitor.execution_read_allowed(uuid,uuid),emailmonitor.execution_read_fence(uuid,uuid),
 emailmonitor.execution_write_allowed(uuid,uuid),emailmonitor.execution_start(uuid,uuid,bigint,uuid),
 emailmonitor.execution_claim(uuid,uuid,uuid,uuid,uuid,integer,bigint),
 emailmonitor.execution_finish(uuid,uuid,uuid,uuid,uuid,text,uuid),
 emailmonitor.execution_control(uuid,uuid,bigint,text,uuid),emailmonitor.execution_reconcile(uuid,uuid,uuid),
 emailmonitor.execution_confirmed(uuid,uuid,uuid),
 emailmonitor.execution_retry(uuid,uuid,bigint,uuid,uuid) TO emailmonitor_runtime;
RESET ROLE;
