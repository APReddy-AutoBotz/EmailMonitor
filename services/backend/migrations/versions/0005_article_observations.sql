-- Synthetic observations only: no accepted author/email association or export.
SET ROLE emailmonitor_owner;
CREATE TABLE emailmonitor.article_observations (
 organization_id uuid NOT NULL, job_id uuid NOT NULL,
 article_url text NOT NULL CHECK(article_url IN (
 'https://synthetic.publisher.example/article-a.html',
 'https://synthetic.publisher.example/article-b.html',
 'https://synthetic.publisher.example/tooltip.html',
 'https://synthetic.publisher.example/no-contact.html')),
 generation bigint NOT NULL CHECK(generation>0),
 deletion_generation bigint NOT NULL CHECK(deletion_generation>0),
 source_id text NOT NULL DEFAULT 'synthetic-publisher' CHECK(source_id='synthetic-publisher'),
 policy_version bigint NOT NULL CHECK(policy_version>0),
 discovery_revision bigint NOT NULL CHECK(discovery_revision>0),
 source_digest text NOT NULL CHECK(source_digest ~ '^[0-9a-f]{64}$'),
 observation jsonb NOT NULL CHECK(jsonb_typeof(observation)='object'
 AND octet_length(observation::text)<=131072),
 revision bigint NOT NULL DEFAULT 1 CHECK(revision>0),
 observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 expires_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(organization_id,job_id,article_url),
 FOREIGN KEY(organization_id,job_id) REFERENCES emailmonitor.discovery,
 FOREIGN KEY(organization_id,source_id,policy_version) REFERENCES emailmonitor.source_policies
);
CREATE FUNCTION emailmonitor.guard_article_observation() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE d emailmonitor.discovery; j emailmonitor.jobs; source_hash text; p jsonb; days integer;
BEGIN
 PERFORM emailmonitor.discovery_source_fence(NEW.organization_id,NEW.job_id,NEW.policy_version);
 SELECT * INTO d FROM emailmonitor.discovery WHERE organization_id=NEW.organization_id
 AND job_id=NEW.job_id FOR SHARE;
 SELECT * INTO j FROM emailmonitor.jobs WHERE organization_id=NEW.organization_id
 AND id=NEW.job_id FOR SHARE;
 IF NEW.generation<>d.generation OR NEW.deletion_generation<>d.deletion_generation
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
CREATE TRIGGER article_observation_guard BEFORE INSERT OR UPDATE ON emailmonitor.article_observations
 FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_article_observation();
ALTER TABLE emailmonitor.article_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.article_observations FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.article_observations TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_read ON emailmonitor.article_observations FOR SELECT TO emailmonitor_runtime
 USING(emailmonitor.tenant_allowed(organization_id) AND expires_at>clock_timestamp()
 AND EXISTS(SELECT 1 FROM emailmonitor.source_policies p
 JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
 JOIN emailmonitor.source_catalog s USING(source_id)
 WHERE p.organization_id=article_observations.organization_id
 AND p.source_id=article_observations.source_id
 AND p.version=article_observations.policy_version AND p.version=h.current_version
 AND p.state='approved' AND p.valid_until>clock_timestamp() AND s.enabled
 AND p.policy->'allowed_operations' ? 'extract_contacts'));
CREATE POLICY job_insert ON emailmonitor.article_observations FOR INSERT TO emailmonitor_runtime
 WITH CHECK(emailmonitor.job_write_allowed(organization_id,job_id));
CREATE POLICY job_update ON emailmonitor.article_observations FOR UPDATE TO emailmonitor_runtime
 USING(emailmonitor.job_write_allowed(organization_id,job_id) AND expires_at>clock_timestamp())
 WITH CHECK(emailmonitor.job_write_allowed(organization_id,job_id));
REVOKE ALL ON emailmonitor.article_observations FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
GRANT SELECT,INSERT,UPDATE ON emailmonitor.article_observations TO emailmonitor_runtime;
REVOKE ALL ON FUNCTION emailmonitor.guard_article_observation() FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator;
UPDATE emailmonitor.source_catalog SET support=jsonb_set(
 support || '{"offline_html_observations_implemented":true}'::jsonb,
 '{known_limits}', '["Synthetic fixture source only","No live connector or accepted-contact workflow"]'::jsonb)
 WHERE source_id='synthetic-publisher';
RESET ROLE;
