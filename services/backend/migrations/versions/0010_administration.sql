-- Synthetic metadata/admission only. Original tenant/source/lease fences remain.
SET ROLE emailmonitor_owner;
CREATE FUNCTION emailmonitor.administration_default() RETURNS jsonb
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,emailmonitor AS $$
 SELECT '{"entitlements":{"max_running_jobs":2,"max_parallel_parse":2,"max_parallel_export":1,"max_parallel_browser":1,"max_articles_per_job":500,"monthly_resolution_units":5000,"max_export_bytes":8388608,"browser_enabled":true,"exports_enabled":true},"branding":{"accent_color":"#155e63","label":null,"logo_reference":null}}'::jsonb
$$;
CREATE FUNCTION emailmonitor.administration_validate(p_config jsonb) RETURNS void
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,emailmonitor AS $$
DECLARE e jsonb; b jsonb; k text; ceiling integer;
BEGIN
 IF p_config IS NULL OR jsonb_typeof(p_config) IS DISTINCT FROM 'object'
 OR p_config-'entitlements'-'branding'<>'{}'::jsonb
 OR NOT p_config ?& ARRAY['entitlements','branding']
 THEN RAISE EXCEPTION 'ADMINISTRATION_CONFIG_INVALID'; END IF;
 e:=p_config->'entitlements'; b:=p_config->'branding';
 IF jsonb_typeof(e) IS DISTINCT FROM 'object'
 OR e-'max_running_jobs'-'max_parallel_parse'-'max_parallel_export'-'max_parallel_browser'-'max_articles_per_job'-'monthly_resolution_units'-'max_export_bytes'-'browser_enabled'-'exports_enabled'<>'{}'::jsonb
 OR NOT e ?& ARRAY['max_running_jobs','max_parallel_parse','max_parallel_export','max_parallel_browser','max_articles_per_job','monthly_resolution_units','max_export_bytes','browser_enabled','exports_enabled']
 OR jsonb_typeof(e->'browser_enabled') IS DISTINCT FROM 'boolean'
 OR jsonb_typeof(e->'exports_enabled') IS DISTINCT FROM 'boolean'
 OR jsonb_typeof(b) IS DISTINCT FROM 'object' OR b-'accent_color'-'label'-'logo_reference'<>'{}'::jsonb
 OR NOT b ?& ARRAY['accent_color','label','logo_reference']
 OR jsonb_typeof(b->'accent_color') IS DISTINCT FROM 'string'
 OR b->>'accent_color' !~ '^#[0-9a-f]{6}$'
 OR b->'logo_reference' IS DISTINCT FROM 'null'::jsonb
 OR (b->'label'<>'null'::jsonb AND (jsonb_typeof(b->'label') IS DISTINCT FROM 'string'
 OR length(b->>'label') NOT BETWEEN 1 AND 80 OR btrim(b->>'label',U&'\0020\00a0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200a\202f\205f\3000')=''
 OR b->>'label' ~ U&'[\0001-\001f\007f-\009f\00ad\0600-\0605\061c\06dd\070f\0890-\0891\08e2\180e\200b-\200f\2028-\202e\2060-\2064\2066-\206f\feff\fff9-\fffb\+0110bd\+0110cd\+013430-\+01343f\+01bca0-\+01bca3\+01d173-\+01d17a\+0e0001\+0e0020-\+0e007f]'))
 THEN RAISE EXCEPTION 'ADMINISTRATION_CONFIG_INVALID'; END IF;
 FOREACH k IN ARRAY ARRAY['max_running_jobs','max_parallel_parse','max_parallel_export','max_parallel_browser','max_articles_per_job','monthly_resolution_units','max_export_bytes'] LOOP
 ceiling:=CASE k WHEN 'max_running_jobs' THEN 2 WHEN 'max_parallel_parse' THEN 2
 WHEN 'max_parallel_export' THEN 1 WHEN 'max_parallel_browser' THEN 1
 WHEN 'max_articles_per_job' THEN 500 WHEN 'monthly_resolution_units' THEN 5000 ELSE 8388608 END;
 IF jsonb_typeof(e->k) IS DISTINCT FROM 'number' OR e->>k !~ '^[0-9]{1,8}$'
 OR (e->>k)::bigint NOT BETWEEN 0 AND ceiling THEN RAISE EXCEPTION 'ADMINISTRATION_CONFIG_INVALID'; END IF;
 END LOOP;
END $$;
CREATE TABLE emailmonitor.tenant_configuration (
 organization_id uuid PRIMARY KEY REFERENCES emailmonitor.organizations,
 revision bigint NOT NULL DEFAULT 1 CHECK(revision>=1),
 configuration jsonb NOT NULL DEFAULT emailmonitor.administration_default(),
 support_reference uuid NOT NULL UNIQUE,
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE emailmonitor.configuration_events (
 organization_id uuid NOT NULL REFERENCES emailmonitor.organizations,id uuid NOT NULL,
 actor_id uuid NOT NULL REFERENCES emailmonitor.identities,
 old_revision bigint NOT NULL,new_revision bigint NOT NULL CHECK(new_revision=old_revision+1),
 old_limits jsonb NOT NULL,new_limits jsonb NOT NULL,branding_changed boolean NOT NULL,
 occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),PRIMARY KEY(organization_id,id)
);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['tenant_configuration','configuration_events'] LOOP
 EXECUTE format('ALTER TABLE emailmonitor.%I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('ALTER TABLE emailmonitor.%I FORCE ROW LEVEL SECURITY',t);
 EXECUTE format('CREATE POLICY owner_all ON emailmonitor.%I TO emailmonitor_owner USING(true) WITH CHECK(true)',t);
 END LOOP;
END $$;
CREATE POLICY current_tenant ON emailmonitor.tenant_configuration FOR SELECT TO emailmonitor_runtime
 USING(emailmonitor.tenant_allowed(organization_id));
CREATE POLICY current_admin ON emailmonitor.configuration_events FOR SELECT TO emailmonitor_runtime
 USING(emailmonitor.tenant_allowed(organization_id) AND emailmonitor.session_role(organization_id) IN ('owner','admin'));
GRANT SELECT ON emailmonitor.tenant_configuration,emailmonitor.configuration_events TO emailmonitor_runtime;
CREATE FUNCTION emailmonitor.administration_initialize() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 INSERT INTO emailmonitor.tenant_configuration(organization_id,support_reference)
 VALUES(NEW.id,md5(NEW.id::text||':synthetic-support-reference')::uuid);
 RETURN NEW;
END $$;
CREATE TRIGGER administration_initialize AFTER INSERT ON emailmonitor.organizations
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.administration_initialize();
INSERT INTO emailmonitor.tenant_configuration(organization_id,support_reference)
 SELECT id,md5(id::text||':synthetic-support-reference')::uuid FROM emailmonitor.organizations;
CREATE FUNCTION emailmonitor.administration_read(p_org uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE c emailmonitor.tenant_configuration;
BEGIN
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) THEN
 RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 SELECT * INTO c FROM emailmonitor.tenant_configuration WHERE organization_id=p_org FOR SHARE;
 IF c.organization_id IS NULL THEN RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 RETURN c.configuration||jsonb_build_object('organization_id',p_org,'revision',c.revision,
 'support_reference',c.support_reference,'deployment_mode','synthetic_offline',
 'billing_implemented',false,'exceptional_support_grants_available',false);
END $$;
CREATE FUNCTION emailmonitor.administration_update(p_org uuid,p_revision bigint,p_config jsonb,p_event uuid)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE old emailmonitor.tenant_configuration; actor uuid;
BEGIN
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false)
 OR emailmonitor.session_role(p_org) IS DISTINCT FROM 'owner'
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.organizations WHERE id=p_org AND status='active')
 THEN RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 PERFORM emailmonitor.administration_validate(p_config);
 SELECT * INTO old FROM emailmonitor.tenant_configuration WHERE organization_id=p_org FOR UPDATE;
 IF old.organization_id IS NULL OR old.revision IS DISTINCT FROM p_revision OR p_event IS NULL
 THEN RAISE EXCEPTION 'ADMINISTRATION_REVISION_CONFLICT'; END IF;
 actor:=emailmonitor.job_actor();
 UPDATE emailmonitor.tenant_configuration SET revision=revision+1,configuration=p_config,
 updated_at=clock_timestamp() WHERE organization_id=p_org;
 INSERT INTO emailmonitor.configuration_events(organization_id,id,actor_id,old_revision,new_revision,old_limits,new_limits,branding_changed)
 VALUES(p_org,p_event,actor,old.revision,old.revision+1,old.configuration->'entitlements',p_config->'entitlements',
 old.configuration->'branding' IS DISTINCT FROM p_config->'branding');
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,p_event,actor,'organization.configuration_updated',p_org);
 RETURN emailmonitor.administration_read(p_org);
END $$;
REVOKE ALL ON FUNCTION emailmonitor.administration_default(),emailmonitor.administration_validate(jsonb),
 emailmonitor.administration_initialize(),emailmonitor.administration_read(uuid),
 emailmonitor.administration_update(uuid,bigint,jsonb,uuid)
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
GRANT EXECUTE ON FUNCTION emailmonitor.administration_read(uuid),
 emailmonitor.administration_update(uuid,bigint,jsonb,uuid) TO emailmonitor_runtime;
RESET ROLE;

-- Shared metadata contains identifiers/counters only, never contact payloads.
SET ROLE emailmonitor_owner;
CREATE TABLE emailmonitor.admission_mutex (
 id boolean PRIMARY KEY DEFAULT true CHECK(id), acquired bigint NOT NULL DEFAULT 0 CHECK(acquired>=0)
);
INSERT INTO emailmonitor.admission_mutex(id) VALUES(true);
CREATE TABLE emailmonitor.admission_pools (
 pool text PRIMARY KEY CHECK(pool IN ('fixture_io','parse','export','browser','http')),
 maximum integer NOT NULL CHECK(maximum BETWEEN 1 AND 4),last_organization uuid
);
INSERT INTO emailmonitor.admission_pools(pool,maximum) VALUES
 ('fixture_io',4),('parse',4),('export',2),('browser',2),('http',4);
CREATE TABLE emailmonitor.admission_requests (
 organization_id uuid NOT NULL REFERENCES emailmonitor.organizations,
 id uuid NOT NULL,pool text NOT NULL REFERENCES emailmonitor.admission_pools,
 actor_id uuid NOT NULL REFERENCES emailmonitor.identities,session_hash text NOT NULL,
 job_id uuid,reference_id uuid NOT NULL,generation bigint NOT NULL CHECK(generation>=1),
 ordinal bigserial NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 heartbeat_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 expires_at timestamptz NOT NULL,state text NOT NULL CHECK(state IN ('waiting','active')),
 nonce uuid,lease_until timestamptz,
 PRIMARY KEY(organization_id,id),UNIQUE(organization_id,pool,reference_id,generation),
 FOREIGN KEY(organization_id,job_id) REFERENCES emailmonitor.jobs,
 CHECK((state='active')=(nonce IS NOT NULL AND lease_until IS NOT NULL)),
 CHECK(expires_at>created_at)
);
CREATE INDEX admission_pool_order ON emailmonitor.admission_requests(pool,state,ordinal);
CREATE TABLE emailmonitor.resolution_accounts (
 organization_id uuid NOT NULL,root_job_id uuid NOT NULL,unit_id uuid NOT NULL,
 job_id uuid NOT NULL,item_id uuid,period date NOT NULL,
 state text NOT NULL CHECK(state IN ('reserved','settled','released')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),settled_at timestamptz,
 PRIMARY KEY(organization_id,root_job_id,unit_id),
 FOREIGN KEY(organization_id,root_job_id) REFERENCES emailmonitor.jobs,
 FOREIGN KEY(organization_id,job_id,item_id) REFERENCES emailmonitor.execution_items,
 FOREIGN KEY(organization_id,job_id) REFERENCES emailmonitor.jobs,
 CHECK((state='settled')=(settled_at IS NOT NULL))
);
CREATE INDEX resolution_period_usage ON emailmonitor.resolution_accounts(organization_id,period,state);
CREATE TABLE emailmonitor.source_resource_buckets (
 source_id text PRIMARY KEY REFERENCES emailmonitor.source_catalog,
 ready_at timestamptz NOT NULL DEFAULT '-infinity',retry_after_until timestamptz NOT NULL DEFAULT '-infinity',
 provider_blocked boolean NOT NULL DEFAULT false,
 attempts bigint NOT NULL DEFAULT 0 CHECK(attempts>=0),last_organization uuid
);
CREATE TABLE emailmonitor.tenant_source_buckets (
 organization_id uuid NOT NULL REFERENCES emailmonitor.organizations,
 source_id text NOT NULL REFERENCES emailmonitor.source_catalog,
 ready_at timestamptz NOT NULL DEFAULT '-infinity',attempts bigint NOT NULL DEFAULT 0 CHECK(attempts>=0),
 PRIMARY KEY(organization_id,source_id)
);
CREATE TABLE emailmonitor.source_resource_requests (
 organization_id uuid NOT NULL REFERENCES emailmonitor.organizations,id uuid NOT NULL,
 job_id uuid,actor_id uuid NOT NULL REFERENCES emailmonitor.identities,session_hash text NOT NULL,
 source_id text NOT NULL CHECK(source_id='synthetic-publisher'),
 generation bigint NOT NULL CHECK(generation>=1),deletion_generation bigint NOT NULL CHECK(deletion_generation>=1),
 policy_version bigint NOT NULL CHECK(policy_version>=1),operation text NOT NULL CHECK(operation IN ('fetch_html','browser')),
 ordinal bigserial NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 heartbeat_at timestamptz NOT NULL DEFAULT clock_timestamp(),path text NOT NULL,
 expires_at timestamptz NOT NULL,state text NOT NULL CHECK(state IN ('waiting','active','finished')),
 nonce uuid,lease_until timestamptz,outcome text CHECK(outcome IN ('response','network_failure','provider_backoff')),
 PRIMARY KEY(organization_id,id),FOREIGN KEY(organization_id,job_id) REFERENCES emailmonitor.jobs,
 FOREIGN KEY(organization_id,source_id,policy_version) REFERENCES emailmonitor.source_policies(organization_id,source_id,version),
 CHECK((state='active')=(nonce IS NOT NULL AND lease_until IS NOT NULL)),
 CHECK(expires_at>created_at)
);
CREATE INDEX source_resource_order ON emailmonitor.source_resource_requests(source_id,state,ordinal);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['admission_mutex','admission_pools','admission_requests','resolution_accounts',
 'source_resource_buckets','tenant_source_buckets','source_resource_requests'] LOOP
 EXECUTE format('ALTER TABLE emailmonitor.%I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('ALTER TABLE emailmonitor.%I FORCE ROW LEVEL SECURITY',t);
 EXECUTE format('CREATE POLICY owner_all ON emailmonitor.%I TO emailmonitor_owner USING(true) WITH CHECK(true)',t);
 EXECUTE format('REVOKE ALL ON emailmonitor.%I FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator',t);
 END LOOP;
END $$;
-- Only current-tenant operational state is readable. Shared infrastructure stays private.
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['admission_requests','resolution_accounts','tenant_source_buckets','source_resource_requests'] LOOP
 EXECUTE format('CREATE POLICY tenant_read ON emailmonitor.%I FOR SELECT TO emailmonitor_runtime USING(emailmonitor.tenant_allowed(organization_id))',t);
 IF t='admission_requests' THEN
 GRANT SELECT(organization_id,id,pool,job_id,reference_id,generation,created_at,heartbeat_at,expires_at,state,lease_until)
 ON emailmonitor.admission_requests TO emailmonitor_runtime;
 ELSIF t='source_resource_requests' THEN
 GRANT SELECT(organization_id,id,job_id,source_id,policy_version,operation,created_at,expires_at,state,lease_until,outcome)
 ON emailmonitor.source_resource_requests TO emailmonitor_runtime;
 ELSE EXECUTE format('GRANT SELECT ON emailmonitor.%I TO emailmonitor_runtime',t); END IF;
 END LOOP;
END $$;
CREATE FUNCTION emailmonitor.admission_cleanup() RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE stamp timestamptz:=clock_timestamp();
BEGIN
 -- Caller owns the short shared mutex. Expiry never authorizes a stale work commit.
 DELETE FROM emailmonitor.admission_requests a WHERE a.expires_at<=stamp
 OR (a.state='active' AND a.lease_until<=stamp)
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.memberships m JOIN emailmonitor.identities i ON i.id=m.identity_id
 JOIN emailmonitor.sessions ss ON ss.identity_id=i.id AND ss.token_hash=a.session_hash
 JOIN emailmonitor.organizations o ON o.id=m.organization_id AND o.status='active'
 WHERE m.organization_id=a.organization_id AND m.identity_id=a.actor_id AND m.status='active'
 AND m.role IN ('owner','admin','data_steward','operator') AND i.active AND ss.revoked_at IS NULL
 AND ss.expires_at>stamp AND ss.permission_revision=i.permission_revision)
 OR (a.job_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM emailmonitor.jobs j
 WHERE j.organization_id=a.organization_id AND j.id=a.job_id AND j.generation=a.generation
 AND j.state IN ('draft','queued','running')));
 UPDATE emailmonitor.source_resource_requests SET state='finished',nonce=NULL,lease_until=NULL,
 outcome='network_failure' WHERE state='active' AND lease_until<=stamp;
 DELETE FROM emailmonitor.source_resource_requests WHERE expires_at<=stamp AND state<>'active';
 UPDATE emailmonitor.resolution_accounts r SET state='released' WHERE r.state='reserved'
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.execution_items i JOIN emailmonitor.jobs j
 ON j.organization_id=i.organization_id AND j.id=i.job_id WHERE i.organization_id=r.organization_id
 AND i.job_id=r.job_id AND (i.id=r.item_id OR (r.item_id IS NULL
 AND md5(r.organization_id::text||':'||r.root_job_id::text||':article:'||i.input_url)::uuid=r.unit_id))
 AND j.state IN ('queued','running','paused')
 AND i.state IN ('pending','running','retry_wait'))
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.article_observations a JOIN emailmonitor.jobs j
 ON j.organization_id=a.organization_id AND j.id=a.job_id WHERE a.organization_id=r.organization_id
 AND a.job_id=r.job_id AND j.state='draft' AND a.expires_at>stamp
 AND md5(a.organization_id::text||':'||r.root_job_id::text||':article:'||a.article_url)::uuid=r.unit_id);
END $$;
CREATE FUNCTION emailmonitor.resolution_reserve(p_org uuid,p_job uuid,p_item uuid) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE i emailmonitor.execution_items; r emailmonitor.execution_runs; current emailmonitor.resolution_accounts;
 cap integer; units bigint; v_period date:=date_trunc('month',clock_timestamp() AT TIME ZONE 'UTC')::date; unit uuid;
BEGIN
 SELECT * INTO i FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=p_job AND id=p_item;
 IF i.id IS NULL THEN RAISE EXCEPTION 'RESOLUTION_SCOPE_REQUIRED'; END IF;
 IF i.work_kind<>'article' THEN RETURN true; END IF;
 SELECT * INTO r FROM emailmonitor.execution_runs WHERE organization_id=p_org AND job_id=p_job;
 unit:=md5(p_org::text||':'||r.root_job_id::text||':article:'||i.input_url)::uuid;
 SELECT * INTO current FROM emailmonitor.resolution_accounts WHERE organization_id=p_org
 AND root_job_id=r.root_job_id AND unit_id=unit;
 IF current.state='settled' THEN RETURN true; END IF;
 IF current.state='reserved' THEN v_period:=current.period; END IF;
 SELECT least((c.configuration->'entitlements'->>'monthly_resolution_units')::integer,
 (e.entitlements->>'monthly_resolution_units')::integer) INTO cap
 FROM emailmonitor.tenant_configuration c JOIN emailmonitor.job_entitlements e
 ON e.organization_id=c.organization_id AND e.job_id=p_job WHERE c.organization_id=p_org FOR SHARE OF c;
 SELECT count(*) INTO units FROM emailmonitor.resolution_accounts WHERE organization_id=p_org
 AND resolution_accounts.period=v_period AND state IN ('reserved','settled');
 IF cap IS NULL OR units>cap OR (current.state IS DISTINCT FROM 'reserved' AND units>=cap) THEN RETURN false; END IF;
 IF current.state='reserved' THEN RETURN true; END IF;
 INSERT INTO emailmonitor.resolution_accounts(organization_id,root_job_id,unit_id,job_id,item_id,period,state)
 VALUES(p_org,r.root_job_id,unit,p_job,p_item,v_period,'reserved')
 ON CONFLICT(organization_id,root_job_id,unit_id) DO UPDATE SET
 job_id=EXCLUDED.job_id,item_id=EXCLUDED.item_id,period=EXCLUDED.period,state='reserved';
 RETURN true;
END $$;
CREATE FUNCTION emailmonitor.admission_try(p_org uuid,p_job uuid,p_reference uuid,p_pool text,p_generation bigint,p_nonce uuid,p_seconds integer)
 RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE stamp timestamptz:=clock_timestamp(); conf jsonb; saved jsonb; slots integer; active integer;
 pool_state emailmonitor.admission_pools; mine emailmonitor.admission_requests; chosen uuid; ticket uuid;
BEGIN
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) OR p_nonce IS NULL OR p_reference IS NULL
 OR p_generation IS NULL OR p_generation<1 OR p_seconds IS NULL OR p_seconds NOT BETWEEN 1 AND 120
 OR p_pool NOT IN ('fixture_io','parse','export','browser','http') THEN
 RAISE EXCEPTION 'ADMISSION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 -- One mutex order serializes metadata admission, not the bounded work itself.
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 stamp:=clock_timestamp();
 PERFORM emailmonitor.admission_cleanup();
 SELECT configuration->'entitlements' INTO conf FROM emailmonitor.tenant_configuration
 WHERE organization_id=p_org FOR SHARE;
 SELECT entitlements INTO saved FROM emailmonitor.job_entitlements WHERE organization_id=p_org AND job_id=p_job;
 IF p_job IS NOT NULL AND saved IS NULL THEN RETURN false; END IF;
 saved:=COALESCE(saved,conf);
 slots:=CASE p_pool WHEN 'export' THEN least((conf->>'max_parallel_export')::integer,(saved->>'max_parallel_export')::integer)
 WHEN 'browser' THEN least((conf->>'max_parallel_browser')::integer,(saved->>'max_parallel_browser')::integer)
 ELSE least((conf->>'max_parallel_parse')::integer,(saved->>'max_parallel_parse')::integer) END;
 IF slots IS NULL OR slots=0 OR (p_pool='export' AND NOT ((conf->>'exports_enabled')::boolean AND (saved->>'exports_enabled')::boolean))
 OR (p_pool='browser' AND NOT ((conf->>'browser_enabled')::boolean AND (saved->>'browser_enabled')::boolean)) THEN RETURN false; END IF;
 SELECT * INTO pool_state FROM emailmonitor.admission_pools WHERE admission_pools.pool=p_pool FOR UPDATE;
 ticket:=md5(p_org::text||':'||p_pool||':'||p_reference::text||':'||p_generation::text)::uuid;
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.admission_requests WHERE organization_id=p_org AND id=ticket)
 AND ((SELECT count(*) FROM emailmonitor.admission_requests WHERE organization_id=p_org)>=500
 OR (SELECT count(*) FROM emailmonitor.admission_requests)>=10000) THEN RETURN false; END IF;
 INSERT INTO emailmonitor.admission_requests(organization_id,id,pool,actor_id,session_hash,job_id,reference_id,generation,expires_at,state)
 VALUES(p_org,ticket,p_pool,emailmonitor.job_actor(),current_setting('emailmonitor.session_hash',true),p_job,p_reference,p_generation,stamp+interval '120 seconds','waiting')
 ON CONFLICT(organization_id,pool,reference_id,generation) DO UPDATE SET heartbeat_at=stamp,actor_id=EXCLUDED.actor_id,session_hash=EXCLUDED.session_hash
 WHERE admission_requests.state='waiting';
 SELECT * INTO mine FROM emailmonitor.admission_requests WHERE organization_id=p_org AND id=ticket;
 IF mine.state<>'waiting' THEN RETURN false; END IF;
 SELECT count(*) INTO active FROM emailmonitor.admission_requests WHERE admission_requests.pool=p_pool AND state='active';
 IF active>=pool_state.maximum OR (SELECT count(*) FROM emailmonitor.admission_requests
 WHERE organization_id=p_org AND admission_requests.pool=p_pool AND state='active')>=slots THEN RETURN false; END IF;
 SELECT a.id INTO chosen FROM emailmonitor.admission_requests a
 JOIN emailmonitor.organizations o ON o.id=a.organization_id AND o.status='active'
 JOIN emailmonitor.tenant_configuration c ON c.organization_id=a.organization_id
 LEFT JOIN emailmonitor.job_entitlements captured ON captured.organization_id=a.organization_id AND captured.job_id=a.job_id
 LEFT JOIN emailmonitor.export_entitlements exported ON p_pool='export' AND exported.organization_id=a.organization_id AND exported.export_id=a.reference_id
 WHERE a.pool=p_pool AND a.state='waiting' AND a.expires_at>stamp
 AND EXISTS(SELECT 1 FROM emailmonitor.memberships m JOIN emailmonitor.identities i ON i.id=m.identity_id
 JOIN emailmonitor.sessions ss ON ss.identity_id=i.id AND ss.token_hash=a.session_hash
 WHERE m.organization_id=a.organization_id AND m.identity_id=a.actor_id AND m.status='active' AND i.active
 AND ss.revoked_at IS NULL AND ss.expires_at>stamp AND ss.permission_revision=i.permission_revision
 AND m.role IN ('owner','admin','data_steward','operator') AND (p_pool<>'export' OR m.role<>'operator'))
 AND a.heartbeat_at>=stamp-interval '5 seconds'
 AND (a.job_id IS NULL OR captured.job_id IS NOT NULL)
 AND (p_pool<>'export' OR ((c.configuration->'entitlements'->>'exports_enabled')::boolean
 AND (COALESCE(exported.entitlements,captured.entitlements,c.configuration->'entitlements')->>'exports_enabled')::boolean))
 AND (p_pool<>'browser' OR ((c.configuration->'entitlements'->>'browser_enabled')::boolean
 AND (COALESCE(captured.entitlements,c.configuration->'entitlements')->>'browser_enabled')::boolean))
 AND (a.job_id IS NULL OR EXISTS(SELECT 1 FROM emailmonitor.jobs j
 JOIN emailmonitor.discovery d ON d.organization_id=j.organization_id AND d.job_id=j.id
 LEFT JOIN emailmonitor.execution_runs r ON r.organization_id=j.organization_id AND r.job_id=j.id
 JOIN emailmonitor.source_policy_heads h ON h.organization_id=d.organization_id AND h.source_id=d.source_id
 JOIN emailmonitor.source_policies policy ON policy.organization_id=h.organization_id AND policy.source_id=h.source_id AND policy.version=h.current_version
 JOIN emailmonitor.memberships membership ON membership.organization_id=j.organization_id AND membership.identity_id=a.actor_id
 JOIN emailmonitor.identities actor ON actor.id=membership.identity_id
 JOIN emailmonitor.sessions sess ON sess.token_hash=a.session_hash AND sess.identity_id=actor.id
 JOIN emailmonitor.source_catalog catalog ON catalog.source_id=d.source_id
 WHERE j.organization_id=a.organization_id AND j.id=a.job_id AND j.generation=a.generation
 AND j.state IN ('draft','queued','running') AND membership.status='active' AND actor.active
 AND sess.revoked_at IS NULL AND sess.expires_at>stamp AND sess.permission_revision=actor.permission_revision
 AND catalog.enabled AND policy.policy->'allowed_operations' ? 'fetch_html'
 AND policy.policy->'allowed_operations' ? 'extract_contacts'
 AND j.request->>'purpose'=policy.policy->>'purpose'
 AND membership.role IN ('owner','admin','data_steward','operator')
 AND policy.state='approved' AND policy.valid_until>stamp AND policy.version=d.policy_version
 AND (r.job_id IS NULL OR r.policy_version=d.policy_version)))
 AND (SELECT count(*) FROM emailmonitor.admission_requests live WHERE live.organization_id=a.organization_id
 AND live.pool=p_pool AND live.state='active')<CASE p_pool WHEN 'export' THEN least((c.configuration->'entitlements'->>'max_parallel_export')::integer,
 (COALESCE(exported.entitlements,captured.entitlements,c.configuration->'entitlements')->>'max_parallel_export')::integer)
 WHEN 'browser' THEN least((c.configuration->'entitlements'->>'max_parallel_browser')::integer,
 (COALESCE(captured.entitlements,c.configuration->'entitlements')->>'max_parallel_browser')::integer)
 ELSE least((c.configuration->'entitlements'->>'max_parallel_parse')::integer,
 (COALESCE(captured.entitlements,c.configuration->'entitlements')->>'max_parallel_parse')::integer) END
 ORDER BY (a.organization_id IS NOT DISTINCT FROM pool_state.last_organization),a.ordinal LIMIT 1;
 IF chosen IS DISTINCT FROM ticket THEN RETURN false; END IF;
 stamp:=clock_timestamp();
 UPDATE emailmonitor.admission_requests SET state='active',nonce=p_nonce,
 lease_until=stamp+make_interval(secs=>p_seconds) WHERE organization_id=p_org AND id=ticket;
 UPDATE emailmonitor.admission_pools SET last_organization=p_org WHERE admission_pools.pool=p_pool;
 UPDATE emailmonitor.admission_mutex SET acquired=acquired+1 WHERE id;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION emailmonitor.admission_cleanup(),emailmonitor.resolution_reserve(uuid,uuid,uuid),
 emailmonitor.admission_try(uuid,uuid,uuid,text,bigint,uuid,integer)
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
RESET ROLE;

SET ROLE emailmonitor_owner;
CREATE TABLE emailmonitor.job_entitlements (
 organization_id uuid NOT NULL,job_id uuid NOT NULL,configuration_revision bigint NOT NULL CHECK(configuration_revision>=1),
 entitlements jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(organization_id,job_id),FOREIGN KEY(organization_id,job_id) REFERENCES emailmonitor.jobs
);
ALTER TABLE emailmonitor.job_entitlements ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.job_entitlements FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.job_entitlements TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY current_job ON emailmonitor.job_entitlements FOR SELECT TO emailmonitor_runtime
 USING(emailmonitor.tenant_allowed(organization_id) AND emailmonitor.execution_read_allowed(organization_id,job_id));
REVOKE ALL ON emailmonitor.job_entitlements FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
GRANT SELECT ON emailmonitor.job_entitlements TO emailmonitor_runtime;
INSERT INTO emailmonitor.job_entitlements(organization_id,job_id,configuration_revision,entitlements)
 SELECT d.organization_id,d.job_id,c.revision,c.configuration->'entitlements'
 FROM emailmonitor.discovery d JOIN emailmonitor.tenant_configuration c ON c.organization_id=d.organization_id;
CREATE FUNCTION emailmonitor.administration_plan(p_org uuid,p_job uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs; conf emailmonitor.tenant_configuration; saved emailmonitor.job_entitlements;
BEGIN
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false)
 OR emailmonitor.session_role(p_org) NOT IN ('owner','admin','data_steward','operator')
 THEN RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR UPDATE;
 IF j.id IS NULL OR j.kind<>'extraction' OR j.state<>'draft'
 THEN RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 SELECT * INTO conf FROM emailmonitor.tenant_configuration WHERE organization_id=p_org FOR SHARE;
 INSERT INTO emailmonitor.job_entitlements(organization_id,job_id,configuration_revision,entitlements)
 VALUES(p_org,p_job,conf.revision,conf.configuration->'entitlements') ON CONFLICT DO NOTHING;
 SELECT * INTO saved FROM emailmonitor.job_entitlements WHERE organization_id=p_org AND job_id=p_job;
 RETURN jsonb_build_object('revision',saved.configuration_revision,'entitlements',saved.entitlements);
END $$;
REVOKE ALL ON FUNCTION emailmonitor.administration_plan(uuid,uuid)
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
GRANT EXECUTE ON FUNCTION emailmonitor.administration_plan(uuid,uuid) TO emailmonitor_runtime;
RESET ROLE;

SET ROLE emailmonitor_owner;
CREATE FUNCTION emailmonitor.resolution_observation_reserve() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs; root uuid; unit uuid; account emailmonitor.resolution_accounts;
 conf jsonb; saved jsonb; cap integer; article_cap integer; position bigint; units bigint;
 v_period date:=date_trunc('month',clock_timestamp() AT TIME ZONE 'UTC')::date; item uuid;
BEGIN
 IF NOT COALESCE(emailmonitor.tenant_allowed(NEW.organization_id),false)
 OR emailmonitor.session_role(NEW.organization_id) NOT IN ('owner','admin','data_steward','operator')
 THEN RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 PERFORM emailmonitor.discovery_source_fence(NEW.organization_id,NEW.job_id,NEW.policy_version);
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=NEW.organization_id AND id=NEW.job_id FOR UPDATE;
 IF j.id IS NULL OR j.kind<>'extraction' OR j.state NOT IN ('draft','running') THEN RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 SELECT root_job_id INTO root FROM emailmonitor.execution_runs WHERE organization_id=NEW.organization_id AND job_id=NEW.job_id;
 root:=COALESCE(root,NEW.job_id);
 unit:=md5(NEW.organization_id::text||':'||root::text||':article:'||NEW.article_url)::uuid;
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 SELECT configuration->'entitlements' INTO conf FROM emailmonitor.tenant_configuration
 WHERE organization_id=NEW.organization_id FOR SHARE;
 SELECT entitlements INTO saved FROM emailmonitor.job_entitlements
 WHERE organization_id=NEW.organization_id AND job_id=NEW.job_id;
 IF saved IS NULL OR conf IS NULL THEN RAISE EXCEPTION 'EFFECTIVE_ENTITLEMENT_REQUIRED'; END IF;
 IF NEW.observation->>'route'='browser_dom' AND
 (NOT (conf->>'browser_enabled')::boolean OR NOT (saved->>'browser_enabled')::boolean)
 THEN RAISE EXCEPTION 'ENTITLEMENT_BUDGET_EXHAUSTED' USING ERRCODE='EM013'; END IF;
 article_cap:=least((conf->>'max_articles_per_job')::integer,(saved->>'max_articles_per_job')::integer);
 SELECT entry.ordinality INTO position FROM emailmonitor.discovery d,
 LATERAL jsonb_array_elements_text(d.checkpoint->'articles') WITH ORDINALITY entry(url,ordinality)
 WHERE d.organization_id=NEW.organization_id AND d.job_id=NEW.job_id AND entry.url=NEW.article_url;
 IF position IS NULL OR position>article_cap THEN RAISE EXCEPTION 'ENTITLEMENT_BUDGET_EXHAUSTED' USING ERRCODE='EM013'; END IF;
 SELECT * INTO account FROM emailmonitor.resolution_accounts WHERE organization_id=NEW.organization_id
 AND root_job_id=root AND unit_id=unit;
 IF account.state='settled' THEN RETURN NEW; END IF;
 IF account.state='reserved' THEN v_period:=account.period; END IF;
 cap:=least((conf->>'monthly_resolution_units')::integer,(saved->>'monthly_resolution_units')::integer);
 SELECT count(*) INTO units FROM emailmonitor.resolution_accounts WHERE organization_id=NEW.organization_id
 AND period=v_period AND state IN ('reserved','settled');
 IF units>cap OR (account.state IS DISTINCT FROM 'reserved' AND units>=cap)
 THEN RAISE EXCEPTION 'ENTITLEMENT_BUDGET_EXHAUSTED' USING ERRCODE='EM013'; END IF;
 item:=nullif(current_setting('emailmonitor.execution_item',true),'')::uuid;
 INSERT INTO emailmonitor.resolution_accounts(organization_id,root_job_id,unit_id,job_id,item_id,period,state)
 VALUES(NEW.organization_id,root,unit,NEW.job_id,item,v_period,'reserved')
 ON CONFLICT(organization_id,root_job_id,unit_id) DO UPDATE SET job_id=EXCLUDED.job_id,item_id=EXCLUDED.item_id,
 period=EXCLUDED.period,state='reserved';
 RETURN NEW;
END $$;
CREATE TRIGGER resolution_observation_reserve BEFORE INSERT OR UPDATE ON emailmonitor.article_observations
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.resolution_observation_reserve();
CREATE FUNCTION emailmonitor.resolution_effect_settle() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE conf jsonb; saved jsonb; account emailmonitor.resolution_accounts; cap integer; units bigint;
BEGIN
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 SELECT configuration->'entitlements' INTO conf FROM emailmonitor.tenant_configuration
 WHERE organization_id=NEW.organization_id FOR SHARE;
 SELECT entitlements INTO saved FROM emailmonitor.job_entitlements WHERE organization_id=NEW.organization_id AND job_id=NEW.job_id;
 SELECT * INTO account FROM emailmonitor.resolution_accounts WHERE organization_id=NEW.organization_id
 AND root_job_id=NEW.root_job_id AND unit_id=NEW.effect_id;
 cap:=least((conf->>'monthly_resolution_units')::integer,(saved->>'monthly_resolution_units')::integer);
 SELECT count(*) INTO units FROM emailmonitor.resolution_accounts WHERE organization_id=NEW.organization_id
 AND period=account.period AND state IN ('reserved','settled');
 IF conf IS NULL OR saved IS NULL OR account.state IS DISTINCT FROM 'reserved' OR units>cap OR cap=0
 THEN RAISE EXCEPTION 'ENTITLEMENT_BUDGET_EXHAUSTED' USING ERRCODE='EM013'; END IF;
 UPDATE emailmonitor.resolution_accounts SET state='settled',settled_at=clock_timestamp(),
 job_id=NEW.job_id,item_id=NEW.item_id WHERE organization_id=NEW.organization_id
 AND root_job_id=NEW.root_job_id AND unit_id=NEW.effect_id AND state='reserved';
 IF NOT FOUND AND NOT EXISTS(SELECT 1 FROM emailmonitor.resolution_accounts
 WHERE organization_id=NEW.organization_id AND root_job_id=NEW.root_job_id
 AND unit_id=NEW.effect_id AND state='settled') THEN RAISE EXCEPTION 'RESOLUTION_RESERVATION_REQUIRED'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER resolution_effect_settle AFTER INSERT ON emailmonitor.execution_effects
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.resolution_effect_settle();
CREATE FUNCTION emailmonitor.resolution_terminal_release() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE root uuid;
BEGIN
 IF NEW.state IN ('failed','cancelled','policy_blocked','access_blocked','skipped') THEN
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 SELECT root_job_id INTO root FROM emailmonitor.execution_runs WHERE organization_id=NEW.organization_id AND job_id=NEW.job_id;
 UPDATE emailmonitor.resolution_accounts SET state='released' WHERE organization_id=NEW.organization_id
 AND job_id=NEW.job_id AND (item_id=NEW.id OR unit_id=md5(NEW.organization_id::text||':'||COALESCE(root,NEW.job_id)::text||':article:'||NEW.input_url)::uuid) AND state='reserved';
 END IF;
 IF NEW.state<>'running' THEN
 DELETE FROM emailmonitor.admission_requests WHERE organization_id=NEW.organization_id
 AND job_id=NEW.job_id AND reference_id=NEW.id;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER resolution_terminal_release AFTER UPDATE ON emailmonitor.execution_items
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.resolution_terminal_release();
REVOKE ALL ON FUNCTION emailmonitor.resolution_observation_reserve(),
 emailmonitor.resolution_effect_settle(),emailmonitor.resolution_terminal_release()
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
RESET ROLE;

SET ROLE emailmonitor_owner;
DO $$ DECLARE constraint_name text; matches integer; BEGIN
 SELECT count(*),min(conname::text) INTO matches,constraint_name FROM pg_constraint
 WHERE conrelid='emailmonitor.execution_items'::regclass AND contype='c'
 AND pg_get_constraintdef(oid) LIKE '%scheduled%' AND pg_get_constraintdef(oid) LIKE '%pagination_committed%';
 IF matches<>1 THEN RAISE EXCEPTION 'EXACT_ITEM_REASON_CONSTRAINT_REQUIRED'; END IF;
 EXECUTE format('ALTER TABLE emailmonitor.execution_items DROP CONSTRAINT %I',constraint_name);
END $$;
ALTER TABLE emailmonitor.execution_items ADD CONSTRAINT execution_items_reason_check CHECK(reason IN (
 'scheduled','leased','observed','no_contact','requires_review','browser_not_completed','source_policy_changed',
 'worker_failure','lease_exhausted','user_cancelled','pagination_committed','quota_exhausted'));
CREATE FUNCTION emailmonitor.execution_quota_stop(p_org uuid,p_job uuid,p_event uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs;
BEGIN
 PERFORM emailmonitor.execution_control_fence(p_org,p_job);
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 IF j.state NOT IN ('queued','running') THEN RETURN; END IF;
 PERFORM emailmonitor.execution_sync(p_org,p_job);
 UPDATE emailmonitor.execution_items SET state='skipped',reason='quota_exhausted',lease_token=NULL,
 lease_until=NULL,lease_generation=NULL,lease_deletion_generation=NULL,completed_at=clock_timestamp()
 WHERE organization_id=p_org AND job_id=p_job AND state IN ('pending','running','retry_wait');
 DELETE FROM emailmonitor.admission_requests WHERE organization_id=p_org AND job_id=p_job;
 UPDATE emailmonitor.resolution_accounts SET state='released' WHERE organization_id=p_org AND job_id=p_job AND state='reserved';
 PERFORM emailmonitor.execution_emit(p_org,p_job,p_event,'job.item_terminal');
 PERFORM emailmonitor.execution_settle(p_org,p_job,md5(p_event::text||':quota-finished')::uuid);
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,p_event,emailmonitor.job_actor(),'job.quota_exhausted',p_job);
END $$;
CREATE FUNCTION emailmonitor.execution_budget_exhausted(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE conf jsonb; saved jsonb; units bigint; cap integer; reserved_units bigint; job emailmonitor.jobs;
 v_period date:=date_trunc('month',clock_timestamp() AT TIME ZONE 'UTC')::date;
BEGIN
 SELECT configuration->'entitlements' INTO conf FROM emailmonitor.tenant_configuration
 WHERE organization_id=p_org;
 SELECT entitlements INTO saved FROM emailmonitor.job_entitlements WHERE organization_id=p_org AND job_id=p_job;
 IF conf IS NULL OR saved IS NULL THEN RETURN true; END IF;
 IF least((conf->>'max_running_jobs')::integer,(saved->>'max_running_jobs')::integer)=0
 OR least((conf->>'max_parallel_parse')::integer,(saved->>'max_parallel_parse')::integer)=0
 OR least((conf->>'max_articles_per_job')::integer,(saved->>'max_articles_per_job')::integer)=0 THEN RETURN true; END IF;
 SELECT * INTO job FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 IF job.state='running' AND (SELECT count(*) FROM emailmonitor.jobs active WHERE active.organization_id=p_org
 AND active.kind='extraction' AND active.state='running' AND (active.created_at,active.id)<=(job.created_at,job.id))
 >least((conf->>'max_running_jobs')::integer,(saved->>'max_running_jobs')::integer) THEN RETURN true; END IF;
 cap:=least((conf->>'monthly_resolution_units')::integer,(saved->>'monthly_resolution_units')::integer);
 SELECT count(*) INTO units FROM emailmonitor.resolution_accounts WHERE organization_id=p_org
 AND period=v_period AND state IN ('reserved','settled');
 SELECT count(*) INTO reserved_units FROM emailmonitor.resolution_accounts WHERE organization_id=p_org
 AND period=v_period AND state='reserved';
 RETURN cap=0 OR units>cap OR (units>=cap AND reserved_units=0) OR EXISTS(
 SELECT 1 FROM emailmonitor.resolution_accounts pending WHERE pending.organization_id=p_org
 AND pending.job_id=p_job AND pending.state='reserved' AND pending.period<>v_period
 AND (SELECT count(*) FROM emailmonitor.resolution_accounts oldperiod WHERE oldperiod.organization_id=p_org
 AND oldperiod.period=pending.period AND oldperiod.state IN ('reserved','settled'))>cap);
END $$;
ALTER FUNCTION emailmonitor.execution_claim(uuid,uuid,uuid,uuid,uuid,integer,bigint) RENAME TO execution_claim_pre_admission;
REVOKE ALL ON FUNCTION emailmonitor.execution_claim_pre_admission(uuid,uuid,uuid,uuid,uuid,integer,bigint)
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
CREATE FUNCTION emailmonitor.execution_claim(p_org uuid,p_job uuid,p_item uuid,p_event uuid,p_token uuid,p_seconds integer,p_generation bigint DEFAULT NULL)
 RETURNS TABLE(item_id uuid,work_kind text,input_url text,discovery_revision bigint,generation bigint,deletion_generation bigint)
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs; i emailmonitor.execution_items; conf jsonb; saved jsonb; slots integer; chosen_pool text; position bigint;
BEGIN
 PERFORM emailmonitor.execution_control_fence(p_org,p_job);
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 SELECT * INTO i FROM emailmonitor.execution_items WHERE organization_id=p_org AND job_id=p_job AND id=p_item FOR UPDATE;
 -- Delegate invalid/duplicate/terminal deliveries to the original receipt/fence path.
 IF i.id IS NULL OR j.state NOT IN ('queued','running') OR i.state NOT IN ('pending','retry_wait')
 OR i.attempts>=3 OR p_token IS NULL OR p_seconds IS NULL OR p_seconds NOT BETWEEN 1 AND 120
 OR (p_generation IS NOT NULL AND p_generation<>j.generation)
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.execution_outbox e WHERE e.organization_id=p_org
 AND e.job_id=p_job AND e.item_id=p_item AND e.event_id=p_event AND e.generation=j.generation) THEN
 RETURN QUERY SELECT * FROM emailmonitor.execution_claim_pre_admission(p_org,p_job,p_item,p_event,p_token,p_seconds,p_generation);
 RETURN; END IF;
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 PERFORM emailmonitor.admission_cleanup();
 IF emailmonitor.execution_budget_exhausted(p_org,p_job) THEN
 PERFORM emailmonitor.execution_quota_stop(p_org,p_job,p_event);RETURN; END IF;
 SELECT configuration->'entitlements' INTO conf FROM emailmonitor.tenant_configuration WHERE organization_id=p_org;
 SELECT entitlements INTO saved FROM emailmonitor.job_entitlements WHERE organization_id=p_org AND job_id=p_job;
 slots:=least((conf->>'max_running_jobs')::integer,(saved->>'max_running_jobs')::integer);
 IF j.state='queued' AND (SELECT count(*) FROM emailmonitor.jobs active WHERE active.organization_id=p_org
 AND active.kind='extraction' AND active.state='running')>=slots THEN RETURN; END IF;
 IF i.work_kind='article' THEN
 SELECT entry.ordinality INTO position FROM emailmonitor.discovery d,
 LATERAL jsonb_array_elements_text(d.checkpoint->'articles') WITH ORDINALITY entry(url,ordinality)
 WHERE d.organization_id=p_org AND d.job_id=p_job AND entry.url=i.input_url;
 IF position IS NULL OR position>least((conf->>'max_articles_per_job')::integer,(saved->>'max_articles_per_job')::integer)
 THEN PERFORM emailmonitor.execution_quota_stop(p_org,p_job,p_event);RETURN; END IF;
 IF NOT emailmonitor.resolution_reserve(p_org,p_job,p_item) THEN
 -- A live reservation can fill the budget temporarily; do not cancel its worker.
 IF emailmonitor.execution_budget_exhausted(p_org,p_job) THEN
 PERFORM emailmonitor.execution_quota_stop(p_org,p_job,p_event); END IF;
 RETURN; END IF;
 END IF;
 chosen_pool:=CASE i.work_kind WHEN 'article' THEN 'parse' ELSE 'fixture_io' END;
 IF NOT emailmonitor.admission_try(p_org,p_job,p_item,chosen_pool,j.generation,p_token,p_seconds) THEN RETURN; END IF;
 RETURN QUERY SELECT * FROM emailmonitor.execution_claim_pre_admission(p_org,p_job,p_item,p_event,p_token,p_seconds,p_generation);
END $$;
ALTER FUNCTION emailmonitor.execution_reconcile(uuid,uuid,uuid) RENAME TO execution_reconcile_pre_admission;
REVOKE ALL ON FUNCTION emailmonitor.execution_reconcile_pre_admission(uuid,uuid,uuid)
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
CREATE FUNCTION emailmonitor.execution_reconcile(p_org uuid,p_job uuid,p_event uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs;
BEGIN
 PERFORM emailmonitor.execution_control_fence(p_org,p_job,false);
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 -- Immutable terminal jobs are checked before any resource/usage synchronization.
 IF j.state IN ('cancelled','completed','completed_partial','failed') THEN RETURN; END IF;
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 PERFORM emailmonitor.admission_cleanup();
 IF j.state IN ('queued','running') AND COALESCE(emailmonitor.execution_read_allowed(p_org,p_job),false)
 AND emailmonitor.execution_budget_exhausted(p_org,p_job) THEN
 PERFORM emailmonitor.execution_quota_stop(p_org,p_job,p_event);RETURN; END IF;
 PERFORM emailmonitor.execution_reconcile_pre_admission(p_org,p_job,p_event);
END $$;
REVOKE ALL ON FUNCTION emailmonitor.execution_quota_stop(uuid,uuid,uuid),
 emailmonitor.execution_budget_exhausted(uuid,uuid),emailmonitor.execution_claim(uuid,uuid,uuid,uuid,uuid,integer,bigint),
 emailmonitor.execution_reconcile(uuid,uuid,uuid) FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
GRANT EXECUTE ON FUNCTION emailmonitor.execution_claim(uuid,uuid,uuid,uuid,uuid,integer,bigint),
 emailmonitor.execution_reconcile(uuid,uuid,uuid) TO emailmonitor_runtime;
RESET ROLE;

SET ROLE emailmonitor_owner;
ALTER FUNCTION emailmonitor.execution_write_allowed(uuid,uuid) RENAME TO execution_write_allowed_pre_admission;
REVOKE ALL ON FUNCTION emailmonitor.execution_write_allowed_pre_admission(uuid,uuid)
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
CREATE FUNCTION emailmonitor.execution_write_allowed(p_org uuid,p_job uuid) RETURNS boolean
 LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs;
BEGIN
 IF NOT COALESCE(emailmonitor.execution_write_allowed_pre_admission(p_org,p_job),false) THEN RETURN false; END IF;
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 -- Initial planning checks source permission before it atomically captures limits.
 -- Observation/admission guards separately require that captured configuration.
 IF j.state='draft' AND NOT EXISTS(SELECT 1 FROM emailmonitor.job_entitlements
 WHERE organization_id=p_org AND job_id=p_job) THEN RETURN true; END IF;
 IF emailmonitor.execution_budget_exhausted(p_org,p_job) THEN RETURN false; END IF;
 IF j.state='draft' THEN RETURN true; END IF;
 RETURN EXISTS(SELECT 1 FROM emailmonitor.admission_requests a WHERE a.organization_id=p_org
 AND a.job_id=p_job AND a.reference_id::text=current_setting('emailmonitor.execution_item',true)
 AND a.generation=j.generation AND a.state='active' AND a.lease_until>clock_timestamp()
 AND a.nonce::text=current_setting('emailmonitor.execution_token',true)
 AND a.session_hash=current_setting('emailmonitor.session_hash',true) AND a.actor_id=emailmonitor.job_actor());
END $$;
CREATE FUNCTION emailmonitor.resolution_job_release() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF NEW.state IN ('cancelled','completed','completed_partial','failed') THEN
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 DELETE FROM emailmonitor.admission_requests WHERE organization_id=NEW.organization_id AND job_id=NEW.id;
 UPDATE emailmonitor.resolution_accounts SET state='released' WHERE organization_id=NEW.organization_id
 AND job_id=NEW.id AND state='reserved';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER resolution_job_release AFTER UPDATE ON emailmonitor.jobs
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.resolution_job_release();
REVOKE ALL ON FUNCTION emailmonitor.execution_write_allowed(uuid,uuid),emailmonitor.resolution_job_release()
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
GRANT EXECUTE ON FUNCTION emailmonitor.execution_write_allowed(uuid,uuid) TO emailmonitor_runtime;
RESET ROLE;

SET ROLE emailmonitor_owner;
CREATE FUNCTION emailmonitor.administration_usage(p_org uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE v_period date:=date_trunc('month',clock_timestamp() AT TIME ZONE 'UTC')::date;
 used bigint; held bigint; waiting jsonb; active jsonb; source_attempts bigint; conf jsonb;
BEGIN
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) THEN
 RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 SELECT count(*) FILTER(WHERE state='settled'),count(*) FILTER(WHERE state='reserved') INTO used,held
 FROM emailmonitor.resolution_accounts WHERE organization_id=p_org AND period=v_period;
 SELECT COALESCE(jsonb_object_agg(pool,total),'{}'::jsonb) INTO waiting FROM (
 SELECT pool,count(*) total FROM (
 SELECT pool FROM emailmonitor.admission_requests WHERE organization_id=p_org
 AND state='waiting' AND expires_at>clock_timestamp()
 UNION ALL SELECT CASE r.operation WHEN 'browser' THEN 'browser' ELSE 'http' END
 FROM emailmonitor.source_resource_requests r WHERE r.organization_id=p_org AND r.state='waiting'
 AND r.expires_at>clock_timestamp() AND NOT EXISTS(SELECT 1 FROM emailmonitor.admission_requests a
 WHERE a.organization_id=r.organization_id AND a.reference_id=r.id
 AND a.pool=CASE r.operation WHEN 'browser' THEN 'browser' ELSE 'http' END)
 ) tickets GROUP BY pool) counters;
 SELECT COALESCE(jsonb_object_agg(pool,total),'{}'::jsonb) INTO active FROM (
 SELECT pool,count(*) total FROM emailmonitor.admission_requests WHERE organization_id=p_org
 AND state='active' AND lease_until>clock_timestamp() GROUP BY pool) counters;
 SELECT COALESCE(sum(attempts),0) INTO source_attempts FROM emailmonitor.tenant_source_buckets WHERE organization_id=p_org;
 SELECT configuration->'entitlements' INTO conf FROM emailmonitor.tenant_configuration WHERE organization_id=p_org;
 RETURN jsonb_build_object('organization_id',p_org,'period_start',v_period,'settled_resolution_units',used,
 'reserved_resolution_units',held,'monthly_unit_limit',(conf->>'monthly_resolution_units')::integer,
 'waiting_units',waiting,'active_units',active,'source_resource_attempts',source_attempts,
 'billing_implemented',false,'synthetic_only',true);
END $$;
REVOKE ALL ON FUNCTION emailmonitor.administration_usage(uuid) FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
GRANT EXECUTE ON FUNCTION emailmonitor.administration_usage(uuid) TO emailmonitor_runtime;
RESET ROLE;

SET ROLE emailmonitor_owner;
CREATE FUNCTION emailmonitor.fixture_admission_claim(p_org uuid,p_job uuid,p_url text,p_nonce uuid,p_seconds integer)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs; d emailmonitor.discovery; pool text; reference uuid; inherited boolean;
BEGIN
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false)
 OR emailmonitor.session_role(p_org) NOT IN ('owner','admin','data_steward','operator')
 OR p_url NOT IN ('https://synthetic.publisher.example/search-page-1.html','https://synthetic.publisher.example/search-page-2.html',
 'https://synthetic.publisher.example/article-a.html','https://synthetic.publisher.example/article-b.html',
 'https://synthetic.publisher.example/tooltip.html','https://synthetic.publisher.example/no-contact.html') THEN
 RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR UPDATE;
 SELECT * INTO d FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job;
 IF j.id IS NULL OR d.job_id IS NULL OR j.state NOT IN ('draft','running') THEN
 RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 PERFORM emailmonitor.discovery_source_fence(p_org,p_job,d.policy_version);
 IF NOT (d.checkpoint->'articles' ? p_url) AND NOT (d.checkpoint->'pages' ? p_url)
 AND d.checkpoint->>'next_url' IS DISTINCT FROM p_url THEN
 RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 pool:=CASE WHEN d.checkpoint->'articles' ? p_url THEN 'parse' ELSE 'fixture_io' END;
 IF j.state='running' THEN
 inherited:=COALESCE(emailmonitor.execution_write_allowed(p_org,p_job),false) AND EXISTS(
 SELECT 1 FROM emailmonitor.execution_items i WHERE i.organization_id=p_org AND i.job_id=p_job
 AND i.id::text=current_setting('emailmonitor.execution_item',true) AND i.input_url=p_url);
 IF NOT inherited THEN RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 RETURN jsonb_build_object('admitted',true,'inherited',true,'reference',null);
 END IF;
 IF emailmonitor.execution_budget_exhausted(p_org,p_job) THEN
 RETURN jsonb_build_object('admitted',false,'inherited',false,'reference',null); END IF;
 reference:=md5(p_org::text||':'||p_job::text||':fixture:'||p_url)::uuid;
 inherited:=emailmonitor.admission_try(p_org,p_job,reference,pool,j.generation,p_nonce,p_seconds);
 RETURN jsonb_build_object('admitted',inherited,'inherited',false,'reference',reference);
END $$;
CREATE FUNCTION emailmonitor.fixture_admission_release(p_org uuid,p_job uuid,p_reference uuid,p_nonce uuid,p_success boolean)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) THEN
 RAISE EXCEPTION 'ADMINISTRATION_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 PERFORM 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR UPDATE;
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 IF p_success IS NULL OR (p_success AND NOT COALESCE(emailmonitor.fixture_commit_allowed(p_org,p_job,
 current_setting('emailmonitor.fixture_url',true)),false)) OR (p_success AND NOT EXISTS(SELECT 1 FROM emailmonitor.admission_requests
 WHERE organization_id=p_org AND job_id=p_job AND reference_id=p_reference AND nonce=p_nonce
 AND actor_id=emailmonitor.job_actor() AND session_hash=current_setting('emailmonitor.session_hash',true)
 AND state='active' AND lease_until>clock_timestamp()) ) THEN
 RAISE EXCEPTION 'FIXTURE_ADMISSION_FENCE' USING ERRCODE='EM013'; END IF;
 DELETE FROM emailmonitor.admission_requests WHERE organization_id=p_org AND job_id=p_job
 AND reference_id=p_reference AND nonce=p_nonce AND session_hash=current_setting('emailmonitor.session_hash',true);
END $$;
REVOKE ALL ON FUNCTION emailmonitor.fixture_admission_claim(uuid,uuid,text,uuid,integer),
 emailmonitor.fixture_admission_release(uuid,uuid,uuid,uuid,boolean) FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
GRANT EXECUTE ON FUNCTION emailmonitor.fixture_admission_claim(uuid,uuid,text,uuid,integer),
 emailmonitor.fixture_admission_release(uuid,uuid,uuid,uuid,boolean) TO emailmonitor_runtime;
RESET ROLE;

-- Fixed-source actual network admission; identifiers and metadata only.
SET ROLE emailmonitor_owner;
CREATE FUNCTION emailmonitor.source_resource_current(p_org uuid,p_id uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT EXISTS(SELECT 1 FROM emailmonitor.source_resource_requests r
 JOIN emailmonitor.organizations o ON o.id=r.organization_id AND o.status='active'
 JOIN emailmonitor.memberships m ON m.organization_id=r.organization_id AND m.identity_id=r.actor_id
 JOIN emailmonitor.identities i ON i.id=m.identity_id AND i.active
 JOIN emailmonitor.sessions ss ON ss.token_hash=r.session_hash AND ss.identity_id=i.id
 JOIN emailmonitor.source_policy_heads h ON h.organization_id=r.organization_id AND h.source_id=r.source_id
 JOIN emailmonitor.source_policies p ON p.organization_id=h.organization_id AND p.source_id=h.source_id AND p.version=h.current_version
 JOIN emailmonitor.source_catalog c ON c.source_id=r.source_id AND c.enabled AND c.execution_mode='fixture'
 JOIN emailmonitor.tenant_configuration cfg ON cfg.organization_id=r.organization_id
 WHERE r.organization_id=p_org AND r.id=p_id AND p.version=r.policy_version
 AND r.deletion_generation=o.deletion_generation
 AND m.status='active' AND m.role IN ('owner','admin','data_steward','operator')
 AND ss.revoked_at IS NULL AND ss.expires_at>statement_timestamp() AND ss.permission_revision=i.permission_revision
 AND p.state='approved' AND p.valid_until>statement_timestamp() AND p.policy->>'execution_mode'='fixture'
 AND p.policy->'allowed_operations' ? r.operation AND r.operation=ANY(c.allowed_operations)
 AND p.policy->'allowed_hosts' ? 'synthetic.publisher.example' AND 'synthetic.publisher.example'=ANY(c.allowed_hosts)
 AND c.support->'routes_by_operation'->r.operation ? r.path
 AND (cfg.configuration->'entitlements'->>'max_parallel_parse')::integer>0
 AND (r.operation<>'browser' OR ((cfg.configuration->'entitlements'->>'browser_enabled')::boolean
 AND (cfg.configuration->'entitlements'->>'max_parallel_browser')::integer>0))
 AND (r.job_id IS NULL OR EXISTS(SELECT 1 FROM emailmonitor.jobs j JOIN emailmonitor.discovery d
 ON d.organization_id=j.organization_id AND d.job_id=j.id JOIN emailmonitor.job_entitlements e
 ON e.organization_id=j.organization_id AND e.job_id=j.id
 WHERE j.organization_id=r.organization_id AND j.id=r.job_id AND j.state IN ('draft','running')
 AND j.generation=r.generation AND d.generation=j.generation
 AND d.deletion_generation=o.deletion_generation
 AND d.policy_version=r.policy_version AND j.request->>'purpose'=p.policy->>'purpose'
 AND (r.operation<>'browser' OR (e.entitlements->>'browser_enabled')::boolean))))
$$;
CREATE FUNCTION emailmonitor.source_resource_claim(p_org uuid,p_id uuid,p_job uuid,p_version bigint,
 p_operation text,p_path text,p_nonce uuid,p_seconds integer) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE stamp timestamptz:=clock_timestamp(); mine emailmonitor.source_resource_requests;
 bucket emailmonitor.source_resource_buckets; tenant emailmonitor.tenant_source_buckets;
 spacing double precision; chosen uuid; until_time timestamptz; pool text; gen bigint:=1; epoch bigint;
BEGIN
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) OR emailmonitor.session_role(p_org) NOT IN ('owner','admin','data_steward','operator')
 OR p_id IS NULL OR p_nonce IS NULL OR p_version IS NULL OR p_version<1 OR p_operation IS NULL
 OR p_operation NOT IN ('fetch_html','browser') OR p_path IS NULL OR length(p_path)>512
 OR p_seconds IS NULL OR p_seconds NOT BETWEEN 1 AND 60
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 IF p_job IS NOT NULL THEN
 PERFORM 1 FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 SELECT generation INTO gen FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job;
 IF NOT COALESCE(emailmonitor.execution_write_allowed(p_org,p_job),false)
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 END IF;
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 stamp:=clock_timestamp();
 PERFORM emailmonitor.admission_cleanup();
 PERFORM 1 FROM emailmonitor.source_catalog WHERE source_id='synthetic-publisher' FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policy_heads WHERE organization_id=p_org AND source_id='synthetic-publisher' FOR SHARE;
 PERFORM 1 FROM emailmonitor.source_policies WHERE organization_id=p_org AND source_id='synthetic-publisher' AND version=p_version FOR SHARE;
 PERFORM 1 FROM emailmonitor.tenant_configuration WHERE organization_id=p_org FOR SHARE;
 SELECT deletion_generation INTO epoch FROM emailmonitor.organizations WHERE id=p_org;
 SELECT * INTO mine FROM emailmonitor.source_resource_requests WHERE organization_id=p_org AND id=p_id;
 IF mine.id IS NOT NULL AND (mine.job_id IS DISTINCT FROM p_job OR mine.policy_version<>p_version
 OR mine.operation<>p_operation OR mine.path<>p_path OR mine.generation<>gen OR mine.deletion_generation<>epoch OR mine.actor_id<>emailmonitor.job_actor()
 OR mine.session_hash<>current_setting('emailmonitor.session_hash',true) OR mine.state='finished')
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 IF mine.id IS NULL AND ((SELECT count(*) FROM emailmonitor.source_resource_requests WHERE organization_id=p_org)>=500
 OR (SELECT count(*) FROM emailmonitor.source_resource_requests)>=10000) THEN
 RETURN jsonb_build_object('admitted',false,'wait_seconds',1.0); END IF;
 INSERT INTO emailmonitor.source_resource_requests(organization_id,id,job_id,actor_id,session_hash,source_id,generation,deletion_generation,policy_version,operation,path,expires_at,state)
 VALUES(p_org,p_id,p_job,emailmonitor.job_actor(),current_setting('emailmonitor.session_hash',true),
 'synthetic-publisher',gen,epoch,p_version,p_operation,p_path,stamp+interval '120 seconds','waiting')
 ON CONFLICT(organization_id,id) DO UPDATE SET heartbeat_at=stamp WHERE source_resource_requests.state='waiting';
 IF NOT COALESCE(emailmonitor.source_resource_current(p_org,p_id),false)
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 IF mine.state='active' THEN
 IF mine.nonce IS DISTINCT FROM p_nonce OR mine.lease_until<=stamp
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 RETURN jsonb_build_object('admitted',true,'wait_seconds',0.0); END IF;
 INSERT INTO emailmonitor.source_resource_buckets(source_id) VALUES('synthetic-publisher') ON CONFLICT DO NOTHING;
 INSERT INTO emailmonitor.tenant_source_buckets(organization_id,source_id) VALUES(p_org,'synthetic-publisher') ON CONFLICT DO NOTHING;
 SELECT * INTO bucket FROM emailmonitor.source_resource_buckets WHERE source_id='synthetic-publisher' FOR UPDATE;
 IF bucket.provider_blocked THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 SELECT * INTO tenant FROM emailmonitor.tenant_source_buckets WHERE organization_id=p_org AND source_id='synthetic-publisher' FOR UPDATE;
 until_time:=greatest(bucket.ready_at,bucket.retry_after_until,tenant.ready_at);
 IF until_time>stamp OR EXISTS(SELECT 1 FROM emailmonitor.source_resource_requests
 WHERE source_id='synthetic-publisher' AND state='active' AND lease_until>stamp) THEN
 RETURN jsonb_build_object('admitted',false,'wait_seconds',greatest(0.05,least(1.0,extract(epoch FROM until_time-stamp)))); END IF;
 SELECT r.id INTO chosen FROM emailmonitor.source_resource_requests r
 WHERE r.source_id='synthetic-publisher' AND r.state='waiting' AND r.expires_at>stamp
 AND r.heartbeat_at>=stamp-interval '5 seconds' AND emailmonitor.source_resource_current(r.organization_id,r.id)
 AND NOT EXISTS(SELECT 1 FROM emailmonitor.tenant_source_buckets t WHERE t.organization_id=r.organization_id
 AND t.source_id=r.source_id AND t.ready_at>stamp)
 ORDER BY (r.organization_id IS NOT DISTINCT FROM bucket.last_organization),r.ordinal LIMIT 1;
 IF chosen IS DISTINCT FROM p_id THEN RETURN jsonb_build_object('admitted',false,'wait_seconds',0.05); END IF;
 pool:=CASE p_operation WHEN 'browser' THEN 'browser' ELSE 'http' END;
 -- HTTP uses the same bounded pool metadata; its per-tenant ceiling is parse's2.
 IF NOT emailmonitor.admission_try(p_org,p_job,p_id,pool,gen,p_nonce,p_seconds)
 THEN RETURN jsonb_build_object('admitted',false,'wait_seconds',0.05); END IF;
 SELECT greatest(5.0,(policy->'limits'->>'min_request_interval_seconds')::double precision) INTO spacing
 FROM emailmonitor.source_policies WHERE organization_id=p_org AND source_id='synthetic-publisher' AND version=p_version;
 IF spacing IS NULL OR spacing>86400 OR spacing<5 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 IF NOT COALESCE(emailmonitor.source_resource_current(p_org,p_id),false)
 OR NOT COALESCE(emailmonitor.network_entitlement_allowed(p_org,p_operation,p_job),false) THEN
 RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 stamp:=clock_timestamp();
 UPDATE emailmonitor.source_resource_requests SET state='active',nonce=p_nonce,lease_until=stamp+make_interval(secs=>p_seconds)
 WHERE organization_id=p_org AND id=p_id;
 UPDATE emailmonitor.source_resource_buckets SET ready_at=stamp+interval '5 seconds',attempts=attempts+1,last_organization=p_org
 WHERE source_id='synthetic-publisher';
 UPDATE emailmonitor.tenant_source_buckets SET ready_at=stamp+make_interval(secs=>spacing),attempts=attempts+1
 WHERE organization_id=p_org AND source_id='synthetic-publisher';
 RETURN jsonb_build_object('admitted',true,'wait_seconds',0.0);
END $$;
CREATE FUNCTION emailmonitor.source_resource_finish(p_org uuid,p_id uuid,p_nonce uuid,p_outcome text,p_retry_seconds integer) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE mine emailmonitor.source_resource_requests; stamp timestamptz:=clock_timestamp();
BEGIN
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) OR p_outcome IS NULL
 OR p_outcome NOT IN ('response','network_failure','provider_backoff') OR p_retry_seconds IS NULL
 OR p_retry_seconds NOT BETWEEN -1 AND 86400 OR (p_outcome<>'provider_backoff' AND p_retry_seconds<>0)
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 stamp:=clock_timestamp();
 SELECT * INTO mine FROM emailmonitor.source_resource_requests WHERE organization_id=p_org AND id=p_id;
 IF mine.id IS NULL OR mine.session_hash IS DISTINCT FROM current_setting('emailmonitor.session_hash',true)
 OR mine.actor_id IS DISTINCT FROM emailmonitor.job_actor() OR (mine.state='active' AND mine.nonce IS DISTINCT FROM p_nonce)
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 IF p_outcome<>'network_failure' AND (mine.state IS DISTINCT FROM 'active'
 OR mine.nonce IS DISTINCT FROM p_nonce OR mine.lease_until IS NULL OR mine.lease_until<=stamp
 OR NOT emailmonitor.source_resource_current(p_org,p_id)
 OR NOT emailmonitor.network_entitlement_allowed(p_org,mine.operation,mine.job_id))
 THEN RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 stamp:=clock_timestamp();
 IF p_outcome<>'network_failure' AND mine.lease_until<=stamp THEN
 RAISE EXCEPTION 'SOURCE_RESOURCE_SCOPE_DENIED' USING ERRCODE='EM013'; END IF;
 IF mine.state='active' AND mine.lease_until>stamp AND p_outcome='provider_backoff' THEN
 UPDATE emailmonitor.source_resource_buckets SET provider_blocked=provider_blocked OR p_retry_seconds=-1,
 retry_after_until=greatest(retry_after_until,stamp+make_interval(secs=>greatest(5,p_retry_seconds)))
 WHERE source_id=mine.source_id;
 END IF;
 DELETE FROM emailmonitor.admission_requests WHERE organization_id=p_org AND reference_id=p_id AND nonce=p_nonce
 AND pool=CASE mine.operation WHEN 'browser' THEN 'browser' ELSE 'http' END;
 UPDATE emailmonitor.source_resource_requests SET state='finished',outcome=p_outcome,nonce=NULL,lease_until=NULL
 WHERE organization_id=p_org AND id=p_id AND state IN ('waiting','active');
END $$;
REVOKE ALL ON FUNCTION emailmonitor.source_resource_current(uuid,uuid),
 emailmonitor.source_resource_claim(uuid,uuid,uuid,bigint,text,text,uuid,integer),
 emailmonitor.source_resource_finish(uuid,uuid,uuid,text,integer) FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
GRANT EXECUTE ON FUNCTION emailmonitor.source_resource_claim(uuid,uuid,uuid,bigint,text,text,uuid,integer),
 emailmonitor.source_resource_finish(uuid,uuid,uuid,text,integer) TO emailmonitor_runtime;
RESET ROLE;

SET ROLE emailmonitor_owner;
ALTER FUNCTION emailmonitor.execution_retry(uuid,uuid,bigint,uuid,uuid) RENAME TO execution_retry_pre_entitlement;
REVOKE ALL ON FUNCTION emailmonitor.execution_retry_pre_entitlement(uuid,uuid,bigint,uuid,uuid)
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
CREATE FUNCTION emailmonitor.execution_retry(p_org uuid,p_job uuid,p_revision bigint,p_new uuid,p_event uuid)
 RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE child uuid;
BEGIN
 child:=emailmonitor.execution_retry_pre_entitlement(p_org,p_job,p_revision,p_new,p_event);
 -- A continuation cannot acquire a larger captured plan through a tenant upgrade.
 INSERT INTO emailmonitor.job_entitlements(organization_id,job_id,configuration_revision,entitlements)
 SELECT organization_id,child,configuration_revision,entitlements FROM emailmonitor.job_entitlements
 WHERE organization_id=p_org AND job_id=p_job ON CONFLICT DO NOTHING;
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.job_entitlements WHERE organization_id=p_org AND job_id=child)
 THEN RAISE EXCEPTION 'ENTITLEMENT_SNAPSHOT_REQUIRED' USING ERRCODE='EM013'; END IF;
 RETURN child;
END $$;
REVOKE ALL ON FUNCTION emailmonitor.execution_retry(uuid,uuid,bigint,uuid,uuid) FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
GRANT EXECUTE ON FUNCTION emailmonitor.execution_retry(uuid,uuid,bigint,uuid,uuid) TO emailmonitor_runtime;
CREATE TABLE emailmonitor.export_entitlements (
 organization_id uuid NOT NULL,export_id uuid NOT NULL,configuration_revision bigint NOT NULL CHECK(configuration_revision>=1),
 entitlements jsonb NOT NULL,PRIMARY KEY(organization_id,export_id),
 FOREIGN KEY(organization_id,export_id) REFERENCES emailmonitor.exports
);
ALTER TABLE emailmonitor.export_entitlements ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.export_entitlements FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.export_entitlements TO emailmonitor_owner USING(true) WITH CHECK(true);
REVOKE ALL ON emailmonitor.export_entitlements FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
INSERT INTO emailmonitor.export_entitlements SELECT e.organization_id,e.id,c.revision,c.configuration->'entitlements'
 FROM emailmonitor.exports e JOIN emailmonitor.tenant_configuration c ON c.organization_id=e.organization_id;
CREATE FUNCTION emailmonitor.export_entitlement_fence(p_org uuid,p_export uuid DEFAULT NULL) RETURNS integer
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE conf jsonb; saved jsonb;
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true);
 SELECT configuration->'entitlements' INTO conf FROM emailmonitor.tenant_configuration WHERE organization_id=p_org FOR SHARE;
 IF p_export IS NOT NULL THEN
 SELECT entitlements INTO saved FROM emailmonitor.export_entitlements WHERE organization_id=p_org AND export_id=p_export;
 IF saved IS NULL THEN RAISE EXCEPTION 'EXPORT_ENTITLEMENT_DENIED' USING ERRCODE='EM013'; END IF;
 ELSE saved:=conf; END IF;
 IF conf IS NULL OR NOT (conf->>'exports_enabled')::boolean OR NOT (saved->>'exports_enabled')::boolean
 OR least((conf->>'max_parallel_export')::integer,(saved->>'max_parallel_export')::integer)=0
 OR least((conf->>'max_export_bytes')::integer,(saved->>'max_export_bytes')::integer)=0
 THEN RAISE EXCEPTION 'EXPORT_ENTITLEMENT_DENIED' USING ERRCODE='EM013'; END IF;
 RETURN least((conf->>'max_export_bytes')::integer,(saved->>'max_export_bytes')::integer);
END $$;
ALTER FUNCTION emailmonitor.exports_create(uuid,uuid,text,jsonb,uuid) RENAME TO exports_create_pre_entitlement;
ALTER FUNCTION emailmonitor.exports_preview(uuid,jsonb) RENAME TO exports_preview_pre_entitlement;
ALTER FUNCTION emailmonitor.exports_claim(uuid,uuid,uuid,bigint,uuid,integer) RENAME TO exports_claim_pre_admission;
ALTER FUNCTION emailmonitor.exports_finish(uuid,uuid,bigint,uuid,bytea,text,text) RENAME TO exports_finish_pre_entitlement;
ALTER FUNCTION emailmonitor.exports_download(uuid,uuid) RENAME TO exports_download_pre_entitlement;
REVOKE ALL ON FUNCTION emailmonitor.exports_create_pre_entitlement(uuid,uuid,text,jsonb,uuid),
 emailmonitor.exports_preview_pre_entitlement(uuid,jsonb),emailmonitor.exports_claim_pre_admission(uuid,uuid,uuid,bigint,uuid,integer),
 emailmonitor.exports_finish_pre_entitlement(uuid,uuid,bigint,uuid,bytea,text,text),
 emailmonitor.exports_download_pre_entitlement(uuid,uuid),emailmonitor.export_entitlement_fence(uuid,uuid)
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
CREATE FUNCTION emailmonitor.exports_create(p_org uuid,p_id uuid,p_key text,p_request jsonb,p_event uuid) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE selected uuid;
BEGIN
 PERFORM emailmonitor.export_entitlement_fence(p_org);
 selected:=emailmonitor.exports_create_pre_entitlement(p_org,p_id,p_key,p_request,p_event);
 INSERT INTO emailmonitor.export_entitlements SELECT p_org,selected,revision,configuration->'entitlements'
 FROM emailmonitor.tenant_configuration WHERE organization_id=p_org ON CONFLICT DO NOTHING;
 RETURN selected;
END $$;
CREATE FUNCTION emailmonitor.exports_preview(p_org uuid,p_request jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 PERFORM emailmonitor.export_entitlement_fence(p_org);
 RETURN emailmonitor.exports_preview_pre_entitlement(p_org,p_request);
END $$;
CREATE FUNCTION emailmonitor.exports_claim(p_org uuid,p_export uuid,p_event uuid,p_generation bigint,p_nonce uuid,p_seconds integer) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE e emailmonitor.exports;
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true);
 SELECT * INTO e FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export FOR UPDATE NOWAIT;
 -- Invalid/stale/duplicate delivery retains the original receipt and denial path.
 IF e.id IS NULL OR e.generation IS DISTINCT FROM p_generation OR e.state NOT IN ('queued','running')
 OR (e.state='running' AND e.lease_until>clock_timestamp()) OR e.attempts>=3
 OR p_seconds IS NULL OR p_seconds NOT BETWEEN 1 AND 120 OR p_nonce IS NULL
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.export_outbox WHERE organization_id=p_org
 AND export_id=p_export AND event_id=p_event AND generation=p_generation) THEN
 RETURN emailmonitor.exports_claim_pre_admission(p_org,p_export,p_event,p_generation,p_nonce,p_seconds); END IF;
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 PERFORM emailmonitor.export_entitlement_fence(p_org,p_export);
 PERFORM emailmonitor.export_lock(p_org,p_export);
 IF NOT emailmonitor.admission_try(p_org,NULL,p_export,'export',p_generation,p_nonce,p_seconds) THEN RETURN NULL; END IF;
 RETURN emailmonitor.exports_claim_pre_admission(p_org,p_export,p_event,p_generation,p_nonce,p_seconds);
END $$;
CREATE FUNCTION emailmonitor.exports_finish(p_org uuid,p_export uuid,p_generation bigint,p_nonce uuid,p_body bytea,p_mime text,p_extension text) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE cap integer;
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true);
 PERFORM 1 FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export FOR UPDATE NOWAIT;
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 cap:=emailmonitor.export_entitlement_fence(p_org,p_export);
 IF p_body IS NULL OR octet_length(p_body)>cap THEN RAISE EXCEPTION 'EXPORT_ENTITLEMENT_DENIED' USING ERRCODE='EM013'; END IF;
 IF NOT EXISTS(SELECT 1 FROM emailmonitor.admission_requests WHERE organization_id=p_org AND reference_id=p_export
 AND pool='export' AND state='active' AND generation=p_generation AND nonce=p_nonce AND lease_until>clock_timestamp()
 AND actor_id=emailmonitor.job_actor() AND session_hash=current_setting('emailmonitor.session_hash',true)) THEN RETURN false; END IF;
 RETURN emailmonitor.exports_finish_pre_entitlement(p_org,p_export,p_generation,p_nonce,p_body,p_mime,p_extension);
END $$;
CREATE FUNCTION emailmonitor.exports_download(p_org uuid,p_export uuid) RETURNS TABLE(body bytea,mime text,extension text,digest text)
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE cap integer;
BEGIN
 cap:=emailmonitor.export_entitlement_fence(p_org,p_export);
 RETURN QUERY SELECT a.body,a.mime,a.extension,a.digest FROM emailmonitor.exports_download_pre_entitlement(p_org,p_export) a
 WHERE octet_length(a.body)<=cap;
 IF NOT FOUND THEN RAISE EXCEPTION 'EXPORT_ENTITLEMENT_DENIED' USING ERRCODE='EM013'; END IF;
END $$;
CREATE FUNCTION emailmonitor.export_admission_release() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
 IF NEW.state<>'running' THEN
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 DELETE FROM emailmonitor.admission_requests WHERE organization_id=NEW.organization_id AND reference_id=NEW.id AND pool='export';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER export_admission_release AFTER UPDATE ON emailmonitor.exports FOR EACH ROW EXECUTE FUNCTION emailmonitor.export_admission_release();
REVOKE ALL ON FUNCTION emailmonitor.export_admission_release(),emailmonitor.exports_create(uuid,uuid,text,jsonb,uuid),
 emailmonitor.exports_preview(uuid,jsonb),emailmonitor.exports_claim(uuid,uuid,uuid,bigint,uuid,integer),
 emailmonitor.exports_finish(uuid,uuid,bigint,uuid,bytea,text,text),emailmonitor.exports_download(uuid,uuid)
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
GRANT EXECUTE ON FUNCTION emailmonitor.exports_create(uuid,uuid,text,jsonb,uuid),emailmonitor.exports_preview(uuid,jsonb),
 emailmonitor.exports_claim(uuid,uuid,uuid,bigint,uuid,integer),emailmonitor.exports_finish(uuid,uuid,bigint,uuid,bytea,text,text),
 emailmonitor.exports_download(uuid,uuid) TO emailmonitor_runtime;
RESET ROLE;

SET ROLE emailmonitor_owner;
CREATE FUNCTION emailmonitor.export_entitlement_allowed(p_org uuid,p_export uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT COALESCE(EXISTS(SELECT 1 FROM emailmonitor.exports e
 JOIN emailmonitor.tenant_configuration c ON c.organization_id=e.organization_id
 JOIN emailmonitor.export_entitlements saved ON saved.organization_id=e.organization_id AND saved.export_id=e.id
 LEFT JOIN emailmonitor.export_artifacts a ON a.organization_id=e.organization_id AND a.export_id=e.id
 WHERE e.organization_id=p_org AND e.id=p_export AND emailmonitor.tenant_allowed(p_org)
 AND (c.configuration->'entitlements'->>'exports_enabled')::boolean AND (saved.entitlements->>'exports_enabled')::boolean
 AND least((c.configuration->'entitlements'->>'max_parallel_export')::integer,(saved.entitlements->>'max_parallel_export')::integer)>0
 AND least((c.configuration->'entitlements'->>'max_export_bytes')::integer,(saved.entitlements->>'max_export_bytes')::integer)>0
 AND (e.state<>'ready' OR (a.body IS NOT NULL AND octet_length(a.body)<=least(
 (c.configuration->'entitlements'->>'max_export_bytes')::integer,(saved.entitlements->>'max_export_bytes')::integer)))),false)
$$;
ALTER FUNCTION emailmonitor.export_metadata(uuid,uuid) RENAME TO export_metadata_pre_entitlement;
ALTER FUNCTION emailmonitor.exports_reconcile(uuid,uuid) RENAME TO exports_reconcile_pre_entitlement;
REVOKE ALL ON FUNCTION emailmonitor.export_metadata_pre_entitlement(uuid,uuid),
 emailmonitor.exports_reconcile_pre_entitlement(uuid,uuid),emailmonitor.export_entitlement_allowed(uuid,uuid)
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
CREATE FUNCTION emailmonitor.export_metadata(p_org uuid,p_export uuid) RETURNS jsonb
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE doc jsonb;
BEGIN
 doc:=emailmonitor.export_metadata_pre_entitlement(p_org,p_export);
 IF doc IS NULL THEN RETURN NULL; END IF;
 RETURN jsonb_set(doc,'{download_available}',to_jsonb(COALESCE((doc->>'download_available')::boolean,false)
 AND emailmonitor.export_entitlement_allowed(p_org,p_export)));
END $$;
CREATE FUNCTION emailmonitor.exports_reconcile(p_org uuid,p_export uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE e emailmonitor.exports;
BEGIN
 PERFORM emailmonitor.results_fence(p_org,true,NULL,false);
 SELECT * INTO e FROM emailmonitor.exports WHERE organization_id=p_org AND id=p_export FOR UPDATE NOWAIT;
 IF e.id IS NULL THEN RAISE EXCEPTION 'RESULT_SCOPE_DENIED' USING ERRCODE='EM011'; END IF;
 IF e.state IN ('queued','running') AND NOT emailmonitor.export_entitlement_allowed(p_org,p_export) THEN
 UPDATE emailmonitor.exports SET state='failed',reason='snapshot_changed',generation=generation+1,
 revision=revision+1,lease_nonce=NULL,lease_until=NULL WHERE organization_id=p_org AND id=p_export;
 RETURN;
 END IF;
 PERFORM emailmonitor.exports_reconcile_pre_entitlement(p_org,p_export);
END $$;
REVOKE ALL ON FUNCTION emailmonitor.export_metadata(uuid,uuid),emailmonitor.exports_reconcile(uuid,uuid)
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
GRANT EXECUTE ON FUNCTION emailmonitor.export_metadata(uuid,uuid),emailmonitor.exports_reconcile(uuid,uuid) TO emailmonitor_runtime;
RESET ROLE;

SET ROLE emailmonitor_owner;
CREATE FUNCTION emailmonitor.network_entitlement_allowed(p_org uuid,p_operation text,p_job uuid DEFAULT NULL) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE conf jsonb; saved jsonb;
BEGIN
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false) OR emailmonitor.session_role(p_org) NOT IN ('owner','admin','data_steward','operator')
 OR p_operation IS NULL OR p_operation NOT IN ('fetch_html','browser') THEN RETURN false; END IF;
 SELECT configuration->'entitlements' INTO conf FROM emailmonitor.tenant_configuration WHERE organization_id=p_org FOR SHARE;
 IF p_job IS NOT NULL THEN
 SELECT entitlements INTO saved FROM emailmonitor.job_entitlements WHERE organization_id=p_org AND job_id=p_job;
 IF saved IS NULL OR NOT COALESCE(emailmonitor.execution_write_allowed(p_org,p_job),false) THEN RETURN false; END IF;
 ELSE saved:=conf; END IF;
 RETURN conf IS NOT NULL AND least((conf->>'max_parallel_parse')::integer,(saved->>'max_parallel_parse')::integer)>0
 AND (p_operation<>'browser' OR ((conf->>'browser_enabled')::boolean AND (saved->>'browser_enabled')::boolean
 AND least((conf->>'max_parallel_browser')::integer,(saved->>'max_parallel_browser')::integer)>0));
END $$;
REVOKE ALL ON FUNCTION emailmonitor.network_entitlement_allowed(uuid,text,uuid) FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
GRANT EXECUTE ON FUNCTION emailmonitor.network_entitlement_allowed(uuid,text,uuid) TO emailmonitor_runtime;
RESET ROLE;


SET ROLE emailmonitor_owner;
CREATE FUNCTION emailmonitor.fixture_commit_allowed(p_org uuid,p_job uuid,p_url text) RETURNS boolean
 LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE j emailmonitor.jobs; d emailmonitor.discovery; reference uuid; nonce text; pool text;
BEGIN
 IF NOT COALESCE(emailmonitor.tenant_allowed(p_org),false)
 OR emailmonitor.session_role(p_org) NOT IN ('owner','admin','data_steward','operator') THEN RETURN false; END IF;
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=p_org AND id=p_job FOR UPDATE;
 IF j.id IS NULL OR j.state<>'draft' OR current_setting('emailmonitor.fixture_job',true) IS DISTINCT FROM p_job::text
 OR current_setting('emailmonitor.fixture_url',true) IS DISTINCT FROM p_url THEN RETURN false; END IF;
 SELECT * INTO d FROM emailmonitor.discovery WHERE organization_id=p_org AND job_id=p_job;
 IF d.job_id IS NULL THEN RETURN false; END IF;
 reference:=md5(p_org::text||':'||p_job::text||':fixture:'||p_url)::uuid;
 nonce:=current_setting('emailmonitor.fixture_nonce',true);
 IF current_setting('emailmonitor.fixture_reference',true) IS DISTINCT FROM reference::text THEN RETURN false; END IF;
 pool:=CASE WHEN d.checkpoint->'articles' ? p_url THEN 'parse' ELSE 'fixture_io' END;
 PERFORM 1 FROM emailmonitor.admission_mutex WHERE id FOR UPDATE;
 PERFORM emailmonitor.discovery_source_fence(p_org,p_job,d.policy_version);
 IF emailmonitor.execution_budget_exhausted(p_org,p_job) THEN RETURN false; END IF;
 RETURN EXISTS(SELECT 1 FROM emailmonitor.admission_requests a WHERE a.organization_id=p_org
 AND a.job_id=p_job AND a.reference_id=reference AND a.pool=pool AND a.generation=j.generation
 AND a.actor_id=emailmonitor.job_actor() AND a.session_hash=current_setting('emailmonitor.session_hash',true)
 AND a.state='active' AND a.nonce::text=nonce AND a.lease_until>clock_timestamp());
END $$;
CREATE FUNCTION emailmonitor.fixture_draft_commit_guard() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE url text; job_state text;
BEGIN
 SELECT state INTO job_state FROM emailmonitor.jobs WHERE organization_id=NEW.organization_id AND id=NEW.job_id;
 IF job_state='draft' THEN
 IF TG_TABLE_NAME='discovery' THEN url:=OLD.checkpoint->>'next_url';
 ELSE url:=NEW.article_url; END IF;
 IF NOT COALESCE(emailmonitor.fixture_commit_allowed(NEW.organization_id,NEW.job_id,url),false) THEN
 RAISE EXCEPTION 'FIXTURE_ADMISSION_FENCE' USING ERRCODE='EM013'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER fixture_discovery_commit_guard BEFORE UPDATE ON emailmonitor.discovery
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.fixture_draft_commit_guard();
CREATE TRIGGER fixture_observation_commit_guard BEFORE INSERT OR UPDATE ON emailmonitor.article_observations
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.fixture_draft_commit_guard();
REVOKE ALL ON FUNCTION emailmonitor.fixture_commit_allowed(uuid,uuid,text),emailmonitor.fixture_draft_commit_guard()
 FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
GRANT EXECUTE ON FUNCTION emailmonitor.fixture_commit_allowed(uuid,uuid,text) TO emailmonitor_runtime;
RESET ROLE;
