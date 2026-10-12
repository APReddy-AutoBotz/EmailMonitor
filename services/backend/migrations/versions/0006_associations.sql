-- Synthetic retained observations only; no source/network permissions expanded.
SET ROLE emailmonitor_owner;
CREATE TABLE emailmonitor.association_batches (
 organization_id uuid NOT NULL, id uuid NOT NULL, job_id uuid NOT NULL, article_url text NOT NULL,
 source_revision bigint NOT NULL CHECK(source_revision>0), policy_version bigint NOT NULL,
 generation bigint NOT NULL, deletion_generation bigint NOT NULL,
 snapshot jsonb NOT NULL CHECK(jsonb_typeof(snapshot)='object' AND octet_length(snapshot::text)<=131072),
 input_digest text NOT NULL CHECK(input_digest ~ '^[0-9a-f]{64}$'),
 expires_at timestamptz NOT NULL, sealed boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(organization_id,id), UNIQUE(organization_id,job_id,article_url,source_revision),
 FOREIGN KEY(organization_id,job_id,article_url) REFERENCES emailmonitor.article_observations
);
CREATE FUNCTION emailmonitor.association_parent_fence(p_org uuid,p_job uuid,p_url text,p_revision bigint,p_write boolean DEFAULT false)
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
 OR j.kind<>'extraction' OR j.state NOT IN ('draft','cancelled')
 OR (p_write AND (j.state<>'draft' OR j.generation<>a.generation))
 OR a.deletion_generation<>o.deletion_generation OR j.deletion_generation<>o.deletion_generation
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
CREATE FUNCTION emailmonitor.association_visible(p_org uuid,p_batch uuid) RETURNS boolean
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
 AND a.generation=b.generation AND j.state IN ('draft','cancelled') AND j.kind='extraction'
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
CREATE FUNCTION emailmonitor.guard_association_batch() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
DECLARE a emailmonitor.article_observations;
BEGIN
 PERFORM emailmonitor.association_parent_fence(NEW.organization_id,NEW.job_id,NEW.article_url,NEW.source_revision,true);
 IF TG_OP='UPDATE' THEN
 IF (to_jsonb(NEW)-'sealed') IS DISTINCT FROM (to_jsonb(OLD)-'sealed') OR OLD.sealed OR NOT NEW.sealed
 THEN RAISE EXCEPTION 'ASSOCIATION_IMMUTABLE'; END IF;
 ELSE
 IF NEW.sealed OR NOT COALESCE(emailmonitor.job_write_allowed(NEW.organization_id,NEW.job_id),false)
 THEN RAISE EXCEPTION 'ASSOCIATION_DENIED' USING ERRCODE='EM009'; END IF;
 END IF;
 SELECT * INTO a FROM emailmonitor.article_observations WHERE organization_id=NEW.organization_id AND job_id=NEW.job_id AND article_url=NEW.article_url;
 IF NEW.snapshot->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
 OR NEW.snapshot->>'source_url' IS DISTINCT FROM NEW.article_url
 OR NEW.snapshot->>'content_digest' IS DISTINCT FROM a.observation->>'content_digest'
 OR NEW.snapshot->>'parser_version' IS DISTINCT FROM a.observation->>'parser_version'
 OR NEW.snapshot->>'observation_route' IS DISTINCT FROM a.observation->>'route'
 OR NEW.snapshot->>'observation_status' IS DISTINCT FROM a.observation->>'status'
 OR NEW.snapshot->'technical_network_checks' IS DISTINCT FROM 'false'::jsonb
 OR NEW.snapshot->'exports_available' IS DISTINCT FROM 'false'::jsonb
 OR NEW.snapshot->>'schema_version' IS DISTINCT FROM '1.0'
 OR COALESCE(jsonb_typeof(NEW.snapshot->'authors'),'')<>'array'
 OR COALESCE(jsonb_typeof(NEW.snapshot->'candidates'),'')<>'array'
 OR COALESCE(jsonb_typeof(NEW.snapshot->'evidence'),'')<>'array'
 OR COALESCE(jsonb_typeof(NEW.snapshot->'associations'),'')<>'array'
 OR jsonb_array_length(NEW.snapshot->'authors')>100 OR jsonb_array_length(NEW.snapshot->'candidates')>100
 OR jsonb_array_length(NEW.snapshot->'evidence')>2400 OR jsonb_array_length(NEW.snapshot->'associations')>10000
 THEN RAISE EXCEPTION 'ASSOCIATION_SNAPSHOT'; END IF;
 IF NEW.snapshot->'preferred_metadata' IS DISTINCT FROM a.observation->'preferred_metadata'
 OR jsonb_array_length(NEW.snapshot->'authors')<>jsonb_array_length(a.observation->'authors')
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.snapshot->'authors') x WHERE NOT EXISTS(
 SELECT 1 FROM jsonb_array_elements(a.observation->'authors') y
 WHERE x->'position'=y->'position' AND x->'display_name'=y->'display_name'
 AND x->'first'=y->'first' AND x->'corresponding'=y->'corresponding'
 AND x->'affiliations'=y->'affiliations' AND x->'orcid'=y->'orcid' AND x->'kind'=y->'author_kind'))
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.snapshot->'candidates') x,
 jsonb_array_elements_text(x->'raw_variants') raw(value) WHERE NOT EXISTS(
 SELECT 1 FROM jsonb_array_elements(a.observation->'candidates') y WHERE y->>'raw_address'=raw.value))
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.snapshot->'evidence') x WHERE NOT EXISTS(
 SELECT 1 FROM jsonb_path_query(a.observation,'$.** ? (@.locator != null && @.excerpt != null)') y
 WHERE x->'locator'=y->'locator' AND x->'excerpt'=y->'excerpt' AND x->'method'=y->'kind'
 AND x->'page'='null'::jsonb AND x->'anchor'='null'::jsonb AND x->'region'='null'::jsonb
 AND x->'coordinate_units'='null'::jsonb AND x->'coordinate_origin'='null'::jsonb AND x->'region_precision'='null'::jsonb))
 THEN RAISE EXCEPTION 'ASSOCIATION_SOURCE_PROVENANCE'; END IF;
 NEW.policy_version:=a.policy_version; NEW.generation:=a.generation; NEW.deletion_generation:=a.deletion_generation; NEW.expires_at:=a.expires_at;
 RETURN NEW;
END $$;
CREATE TRIGGER association_batch_guard BEFORE INSERT OR UPDATE ON emailmonitor.association_batches FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_association_batch();
-- Canonical record receipts are immutable inputs; stored generated columns and
-- composite foreign keys are the actual relational/indexed business shape.
CREATE TABLE emailmonitor.association_authors (
 organization_id uuid NOT NULL, batch_id uuid NOT NULL, record jsonb NOT NULL,
 id uuid GENERATED ALWAYS AS ((record->>'id')::uuid) STORED,
 position integer GENERATED ALWAYS AS ((record->>'position')::integer) STORED NOT NULL CHECK(position BETWEEN 1 AND 100),
 display_name text GENERATED ALWAYS AS (record->>'display_name') STORED NOT NULL CHECK(length(display_name) BETWEEN 1 AND 300),
 first_role boolean GENERATED ALWAYS AS ((record->>'first')::boolean) STORED NOT NULL,
 correspondence_role boolean GENERATED ALWAYS AS ((record->>'corresponding')::boolean) STORED,
 identity_state text GENERATED ALWAYS AS (record->>'identity_state') STORED NOT NULL CHECK(identity_state='article_local_unresolved'),
 PRIMARY KEY(organization_id,batch_id,id), UNIQUE(organization_id,batch_id,position),
 FOREIGN KEY(organization_id,batch_id) REFERENCES emailmonitor.association_batches
);
CREATE TABLE emailmonitor.association_candidates (
 organization_id uuid NOT NULL, batch_id uuid NOT NULL, record jsonb NOT NULL,
 id uuid GENERATED ALWAYS AS ((record->>'id')::uuid) STORED,
 raw_address text GENERATED ALWAYS AS (record->'address'->>'raw_address') STORED NOT NULL CHECK(length(raw_address) BETWEEN 1 AND 320),
 normalized_address text GENERATED ALWAYS AS (record->'address'->>'normalized_address') STORED,
 comparison_key text GENERATED ALWAYS AS (record->'address'->>'comparison_key') STORED NOT NULL,
 syntax_status text GENERATED ALWAYS AS (record->'address'->>'syntax_status') STORED NOT NULL CHECK(syntax_status IN ('valid','invalid','unsupported')),
 domain_status text GENERATED ALWAYS AS (record->'address'->>'domain_status') STORED NOT NULL CHECK(domain_status='not_checked'),
 delivery_status text GENERATED ALWAYS AS (record->'address'->>'delivery_status') STORED NOT NULL CHECK(delivery_status='unverified'),
 normalization_collision boolean GENERATED ALWAYS AS ((record->>'normalization_collision')::boolean) STORED NOT NULL,
 PRIMARY KEY(organization_id,batch_id,id), UNIQUE(organization_id,batch_id,comparison_key),
 FOREIGN KEY(organization_id,batch_id) REFERENCES emailmonitor.association_batches
);
CREATE INDEX association_candidate_lookup ON emailmonitor.association_candidates(organization_id,comparison_key);
CREATE TABLE emailmonitor.association_evidence (
 organization_id uuid NOT NULL, batch_id uuid NOT NULL, record jsonb NOT NULL,
 id uuid GENERATED ALWAYS AS ((record->>'id')::uuid) STORED,
 locator text GENERATED ALWAYS AS (record->>'locator') STORED NOT NULL CHECK(length(locator) BETWEEN 1 AND 512),
 excerpt text GENERATED ALWAYS AS (record->>'excerpt') STORED NOT NULL CHECK(length(excerpt)<=512),
 method text GENERATED ALWAYS AS (record->>'method') STORED NOT NULL,
 PRIMARY KEY(organization_id,batch_id,id),
 FOREIGN KEY(organization_id,batch_id) REFERENCES emailmonitor.association_batches
);
CREATE TABLE emailmonitor.author_email_associations (
 organization_id uuid NOT NULL, batch_id uuid NOT NULL, record jsonb NOT NULL,
 id uuid GENERATED ALWAYS AS ((record->>'id')::uuid) STORED,
 candidate_id uuid GENERATED ALWAYS AS ((record->>'candidate_id')::uuid) STORED NOT NULL,
 author_id uuid GENERATED ALWAYS AS ((record->>'author_id')::uuid) STORED,
 state text GENERATED ALWAYS AS (record->>'state') STORED NOT NULL CHECK(state IN ('unmatched','needs_review','accepted','rejected','suppressed')),
 evidence_strength text GENERATED ALWAYS AS (record->>'evidence_strength') STORED NOT NULL CHECK(evidence_strength IN ('explicit','supported','ambiguous','none')),
 revision bigint GENERATED ALWAYS AS ((record->>'revision')::bigint) STORED NOT NULL CHECK(revision>0),
 CHECK(record->'heuristic_score' IS NOT DISTINCT FROM 'null'::jsonb AND record->'calibrated_probability' IS NOT DISTINCT FROM 'null'::jsonb),
 CHECK(record->>'rule_version' IS NOT DISTINCT FROM 'synthetic-association-v1'),
 PRIMARY KEY(organization_id,batch_id,id),
 FOREIGN KEY(organization_id,batch_id) REFERENCES emailmonitor.association_batches,
 FOREIGN KEY(organization_id,batch_id,candidate_id) REFERENCES emailmonitor.association_candidates,
 FOREIGN KEY(organization_id,batch_id,author_id) REFERENCES emailmonitor.association_authors
);
CREATE INDEX association_state_lookup ON emailmonitor.author_email_associations(organization_id,state,batch_id);
CREATE TABLE emailmonitor.association_affiliations (
 organization_id uuid NOT NULL, batch_id uuid NOT NULL, author_id uuid NOT NULL,
 ordinal integer NOT NULL CHECK(ordinal BETWEEN 1 AND 20), institution_name text NOT NULL CHECK(length(institution_name)<=1000),
 observation_state text NOT NULL DEFAULT 'unknown' CHECK(observation_state='unknown'),
 PRIMARY KEY(organization_id,batch_id,author_id,ordinal),
 FOREIGN KEY(organization_id,batch_id,author_id) REFERENCES emailmonitor.association_authors
);
CREATE TABLE emailmonitor.association_raw_variants (
 organization_id uuid NOT NULL, batch_id uuid NOT NULL, candidate_id uuid NOT NULL,
 ordinal integer NOT NULL CHECK(ordinal BETWEEN 1 AND 100), raw_address text NOT NULL CHECK(length(raw_address) BETWEEN 1 AND 320),
 PRIMARY KEY(organization_id,batch_id,candidate_id,ordinal), UNIQUE(organization_id,batch_id,candidate_id,raw_address),
 FOREIGN KEY(organization_id,batch_id,candidate_id) REFERENCES emailmonitor.association_candidates
);
CREATE TABLE emailmonitor.association_author_evidence (
 organization_id uuid NOT NULL, batch_id uuid NOT NULL, author_id uuid NOT NULL, evidence_id uuid NOT NULL,
 PRIMARY KEY(organization_id,batch_id,author_id,evidence_id),
 FOREIGN KEY(organization_id,batch_id,author_id) REFERENCES emailmonitor.association_authors,
 FOREIGN KEY(organization_id,batch_id,evidence_id) REFERENCES emailmonitor.association_evidence
);
CREATE TABLE emailmonitor.association_candidate_evidence (
 organization_id uuid NOT NULL, batch_id uuid NOT NULL, candidate_id uuid NOT NULL, evidence_id uuid NOT NULL,
 PRIMARY KEY(organization_id,batch_id,candidate_id,evidence_id),
 FOREIGN KEY(organization_id,batch_id,candidate_id) REFERENCES emailmonitor.association_candidates,
 FOREIGN KEY(organization_id,batch_id,evidence_id) REFERENCES emailmonitor.association_evidence
);
CREATE TABLE emailmonitor.association_evidence_links (
 organization_id uuid NOT NULL, batch_id uuid NOT NULL, association_id uuid NOT NULL, evidence_id uuid NOT NULL,
 PRIMARY KEY(organization_id,batch_id,association_id,evidence_id),
 FOREIGN KEY(organization_id,batch_id,association_id) REFERENCES emailmonitor.author_email_associations,
 FOREIGN KEY(organization_id,batch_id,evidence_id) REFERENCES emailmonitor.association_evidence
);
CREATE TABLE emailmonitor.association_reviews (
 organization_id uuid NOT NULL, batch_id uuid NOT NULL, id uuid NOT NULL, association_id uuid NOT NULL,
 actor uuid NOT NULL, action text NOT NULL CHECK(action IN ('accept','reject','correct')),
 previous_record jsonb NOT NULL, new_record jsonb NOT NULL,
 expected_revision bigint NOT NULL, reason text NOT NULL CHECK(length(reason) BETWEEN 1 AND 300),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(organization_id,batch_id,id), UNIQUE(organization_id,batch_id,association_id,expected_revision),
 FOREIGN KEY(organization_id,batch_id,association_id) REFERENCES emailmonitor.author_email_associations,
 FOREIGN KEY(organization_id,actor) REFERENCES emailmonitor.memberships(organization_id,identity_id)
);
CREATE TABLE emailmonitor.association_review_evidence (
 organization_id uuid NOT NULL, batch_id uuid NOT NULL, review_id uuid NOT NULL, evidence_id uuid NOT NULL,
 PRIMARY KEY(organization_id,batch_id,review_id,evidence_id),
 FOREIGN KEY(organization_id,batch_id,review_id) REFERENCES emailmonitor.association_reviews,
 FOREIGN KEY(organization_id,batch_id,evidence_id) REFERENCES emailmonitor.association_evidence
);
CREATE TABLE emailmonitor.association_outbox (
 organization_id uuid NOT NULL, batch_id uuid NOT NULL, event_id uuid NOT NULL,
 association_id uuid NOT NULL, revision bigint NOT NULL, event_type text NOT NULL CHECK(event_type='association.reviewed'),
 published_at timestamptz, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(organization_id,event_id), UNIQUE(organization_id,batch_id,association_id,revision),
 FOREIGN KEY(organization_id,batch_id,association_id) REFERENCES emailmonitor.author_email_associations
);
CREATE FUNCTION emailmonitor.guard_association_record() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
DECLARE b emailmonitor.association_batches; old_revision bigint; author uuid; candidate uuid; cited uuid[];
BEGIN
 SELECT * INTO b FROM emailmonitor.association_batches WHERE organization_id=NEW.organization_id AND id=NEW.batch_id FOR SHARE;
 PERFORM emailmonitor.association_parent_fence(b.organization_id,b.job_id,b.article_url,b.source_revision,TG_OP='INSERT');
 IF TG_OP='INSERT' THEN
 IF b.id IS NULL OR b.sealed OR NOT COALESCE(emailmonitor.job_write_allowed(b.organization_id,b.job_id),false)
 OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(b.snapshot->TG_ARGV[0]) item WHERE item=NEW.record)
 THEN RAISE EXCEPTION 'ASSOCIATION_RECEIPT'; END IF;
 ELSE
 IF TG_TABLE_NAME<>'author_email_associations' OR NOT b.sealed
 OR emailmonitor.session_role(b.organization_id) NOT IN ('owner','admin','data_steward','reviewer')
 OR NEW.organization_id<>OLD.organization_id OR NEW.batch_id<>OLD.batch_id
 OR (NEW.record-ARRAY['author_id','state','evidence_strength','evidence_ids','reason','revision'])
 IS DISTINCT FROM (OLD.record-ARRAY['author_id','state','evidence_strength','evidence_ids','reason','revision'])
 OR (NEW.record->>'revision')::bigint<>(OLD.record->>'revision')::bigint+1
 OR OLD.record->>'state'='suppressed' OR NEW.record->>'state' NOT IN ('accepted','rejected')
 OR NEW.record->>'reason' IS DISTINCT FROM 'reviewed_evidence'
 THEN RAISE EXCEPTION 'ASSOCIATION_REVIEW_FENCE'; END IF;
 END IF;
 IF TG_TABLE_NAME='author_email_associations' AND NEW.record->>'state'='accepted' THEN
 author:=(NEW.record->>'author_id')::uuid; candidate:=(NEW.record->>'candidate_id')::uuid;
 SELECT array_agg(value::uuid) INTO cited FROM jsonb_array_elements_text(NEW.record->'evidence_ids');
 IF author IS NULL OR NEW.record->>'evidence_strength' NOT IN ('explicit','supported')
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.association_candidates c WHERE c.organization_id=NEW.organization_id
 AND c.batch_id=NEW.batch_id AND c.id=candidate AND c.syntax_status='valid' AND NOT c.normalization_collision)
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.association_authors a WHERE a.organization_id=NEW.organization_id AND a.batch_id=NEW.batch_id AND a.id=author)
 OR cited IS NULL OR cardinality(cited)>40
 OR EXISTS(SELECT 1 FROM unnest(cited) eid WHERE NOT EXISTS(SELECT 1 FROM emailmonitor.association_evidence e
 WHERE e.organization_id=NEW.organization_id AND e.batch_id=NEW.batch_id AND e.id=eid AND length(e.excerpt)>0))
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.association_candidates c WHERE c.organization_id=NEW.organization_id AND c.batch_id=NEW.batch_id AND c.id=candidate
 AND EXISTS(SELECT 1 FROM jsonb_array_elements_text(c.record->'evidence_ids') eid WHERE eid::uuid=ANY(cited)))
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.association_authors a WHERE a.organization_id=NEW.organization_id AND a.batch_id=NEW.batch_id AND a.id=author
 AND EXISTS(SELECT 1 FROM jsonb_array_elements_text(a.record->'evidence_ids') eid WHERE eid::uuid=ANY(cited)))
 THEN RAISE EXCEPTION 'ASSOCIATION_ACCEPTANCE_EVIDENCE'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER association_author_guard BEFORE INSERT ON emailmonitor.association_authors FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_association_record('authors');
CREATE TRIGGER association_candidate_guard BEFORE INSERT ON emailmonitor.association_candidates FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_association_record('candidates');
CREATE TRIGGER association_evidence_guard BEFORE INSERT ON emailmonitor.association_evidence FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_association_record('evidence');
CREATE TRIGGER author_email_association_guard BEFORE INSERT OR UPDATE ON emailmonitor.author_email_associations FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_association_record('associations');
CREATE FUNCTION emailmonitor.guard_association_relation() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$
DECLARE b emailmonitor.association_batches; source jsonb; entity uuid;
BEGIN
 SELECT * INTO b FROM emailmonitor.association_batches WHERE organization_id=NEW.organization_id AND id=NEW.batch_id FOR SHARE;
 PERFORM emailmonitor.association_parent_fence(b.organization_id,b.job_id,b.article_url,b.source_revision,NOT COALESCE(b.sealed,false));
 IF b.id IS NULL THEN RAISE EXCEPTION 'ASSOCIATION_RELATION'; END IF;
 IF b.sealed THEN
 IF TG_TABLE_NAME<>'association_evidence_links' OR emailmonitor.session_role(b.organization_id) NOT IN ('owner','admin','data_steward','reviewer')
 THEN RAISE EXCEPTION 'ASSOCIATION_IMMUTABLE'; END IF;
 RETURN NEW;
 END IF;
 IF NOT COALESCE(emailmonitor.job_write_allowed(b.organization_id,b.job_id),false) THEN RAISE EXCEPTION 'ASSOCIATION_DENIED' USING ERRCODE='EM009'; END IF;
 entity:=(to_jsonb(NEW)->>TG_ARGV[1])::uuid;
 SELECT item INTO source FROM jsonb_array_elements(b.snapshot->TG_ARGV[0]) item WHERE item->>'id'=entity::text;
 IF source IS NULL THEN RAISE EXCEPTION 'ASSOCIATION_RELATION'; END IF;
 IF TG_TABLE_NAME='association_affiliations' THEN
 IF source->'affiliations'->>(NEW.ordinal-1) IS DISTINCT FROM NEW.institution_name THEN RAISE EXCEPTION 'ASSOCIATION_AFFILIATION'; END IF;
 ELSIF TG_TABLE_NAME='association_raw_variants' THEN
 IF source->'raw_variants'->>(NEW.ordinal-1) IS DISTINCT FROM NEW.raw_address THEN RAISE EXCEPTION 'ASSOCIATION_RAW_VARIANT'; END IF;
 ELSIF NOT (source->'evidence_ids' ? NEW.evidence_id::text) THEN RAISE EXCEPTION 'ASSOCIATION_EVIDENCE_LINK'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER association_affiliation_guard BEFORE INSERT ON emailmonitor.association_affiliations FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_association_relation('authors','author_id');
CREATE TRIGGER association_variant_guard BEFORE INSERT ON emailmonitor.association_raw_variants FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_association_relation('candidates','candidate_id');
CREATE TRIGGER association_author_link_guard BEFORE INSERT ON emailmonitor.association_author_evidence FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_association_relation('authors','author_id');
CREATE TRIGGER association_candidate_link_guard BEFORE INSERT ON emailmonitor.association_candidate_evidence FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_association_relation('candidates','candidate_id');
CREATE TRIGGER association_link_guard BEFORE INSERT ON emailmonitor.association_evidence_links FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_association_relation('associations','association_id');
CREATE FUNCTION emailmonitor.seal_association_batch(p_org uuid,p_batch uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE b emailmonitor.association_batches; expected_count bigint; actual_count bigint;
BEGIN
 SELECT * INTO b FROM emailmonitor.association_batches WHERE organization_id=p_org AND id=p_batch FOR UPDATE;
 PERFORM emailmonitor.association_parent_fence(b.organization_id,b.job_id,b.article_url,b.source_revision,true);
 IF b.id IS NULL OR b.sealed OR NOT COALESCE(emailmonitor.job_write_allowed(p_org,b.job_id),false)
 THEN RAISE EXCEPTION 'ASSOCIATION_SEAL'; END IF;
 IF (SELECT count(*) FROM emailmonitor.association_authors WHERE organization_id=p_org AND batch_id=p_batch)<>jsonb_array_length(b.snapshot->'authors')
 OR (SELECT count(*) FROM emailmonitor.association_candidates WHERE organization_id=p_org AND batch_id=p_batch)<>jsonb_array_length(b.snapshot->'candidates')
 OR (SELECT count(*) FROM emailmonitor.association_evidence WHERE organization_id=p_org AND batch_id=p_batch)<>jsonb_array_length(b.snapshot->'evidence')
 OR (SELECT count(*) FROM emailmonitor.author_email_associations WHERE organization_id=p_org AND batch_id=p_batch)<>jsonb_array_length(b.snapshot->'associations')
 OR (SELECT count(*) FROM emailmonitor.association_author_evidence WHERE organization_id=p_org AND batch_id=p_batch)
 <>COALESCE((SELECT sum(jsonb_array_length(x->'evidence_ids')) FROM jsonb_array_elements(b.snapshot->'authors') x),0)
 OR (SELECT count(*) FROM emailmonitor.association_candidate_evidence WHERE organization_id=p_org AND batch_id=p_batch)
 <>COALESCE((SELECT sum(jsonb_array_length(x->'evidence_ids')) FROM jsonb_array_elements(b.snapshot->'candidates') x),0)
 OR (SELECT count(*) FROM emailmonitor.association_evidence_links WHERE organization_id=p_org AND batch_id=p_batch)
 <>COALESCE((SELECT sum(jsonb_array_length(x->'evidence_ids')) FROM jsonb_array_elements(b.snapshot->'associations') x),0)
 OR (SELECT count(*) FROM emailmonitor.association_affiliations WHERE organization_id=p_org AND batch_id=p_batch)
 <>COALESCE((SELECT sum(jsonb_array_length(x->'affiliations')) FROM jsonb_array_elements(b.snapshot->'authors') x),0)
 OR (SELECT count(*) FROM emailmonitor.association_raw_variants WHERE organization_id=p_org AND batch_id=p_batch)
 <>COALESCE((SELECT sum(jsonb_array_length(x->'raw_variants')) FROM jsonb_array_elements(b.snapshot->'candidates') x),0)
 THEN RAISE EXCEPTION 'ASSOCIATION_INCOMPLETE_RELATIONS'; END IF;
 UPDATE emailmonitor.association_batches SET sealed=true WHERE organization_id=p_org AND id=p_batch;
END $$;
CREATE FUNCTION emailmonitor.review_association(p_org uuid,p_batch uuid,p_association uuid,p_revision bigint,
 p_action text,p_author uuid,p_evidence uuid[],p_reason text,p_review uuid,p_event uuid) RETURNS bigint
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE b emailmonitor.association_batches; a emailmonitor.author_email_associations;
 updated jsonb; target uuid; cited uuid; actor uuid;
BEGIN
 SELECT * INTO b FROM emailmonitor.association_batches WHERE organization_id=p_org AND id=p_batch FOR SHARE;
 PERFORM emailmonitor.association_parent_fence(b.organization_id,b.job_id,b.article_url,b.source_revision);
 IF b.id IS NULL OR NOT b.sealed OR b.expires_at<=clock_timestamp()
 OR emailmonitor.session_role(p_org) NOT IN ('owner','admin','data_steward','reviewer')
 THEN RAISE EXCEPTION 'ASSOCIATION_DENIED' USING ERRCODE='EM009'; END IF;
 SELECT * INTO a FROM emailmonitor.author_email_associations WHERE organization_id=p_org AND batch_id=p_batch AND id=p_association FOR UPDATE;
 IF a.id IS NULL THEN RAISE EXCEPTION 'ASSOCIATION_DENIED' USING ERRCODE='EM009'; END IF;
 IF a.revision<>p_revision THEN RAISE EXCEPTION 'ASSOCIATION_REVISION' USING ERRCODE='EM409'; END IF;
 IF p_action IS NULL OR p_action NOT IN ('accept','reject','correct') OR a.state='suppressed'
 OR p_evidence IS NULL OR cardinality(p_evidence) NOT BETWEEN 1 AND 40
 OR cardinality(p_evidence)<>(SELECT count(DISTINCT e) FROM unnest(p_evidence) e)
 OR p_reason IS NULL OR length(p_reason) NOT BETWEEN 1 AND 300 OR p_review IS NULL OR p_event IS NULL
 OR (p_action='correct' AND p_author IS NULL) OR (p_action='reject' AND p_author IS NOT NULL)
 OR EXISTS(SELECT 1 FROM unnest(p_evidence) e WHERE NOT EXISTS(SELECT 1 FROM emailmonitor.association_evidence x
 WHERE x.organization_id=p_org AND x.batch_id=p_batch AND x.id=e))
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.association_candidate_evidence x WHERE x.organization_id=p_org AND x.batch_id=p_batch
 AND x.candidate_id=a.candidate_id AND x.evidence_id=ANY(p_evidence))
 THEN RAISE EXCEPTION 'ASSOCIATION_REVIEW_INPUT'; END IF;
 target:=COALESCE(p_author,a.author_id);
 IF p_action<>'reject' AND (target IS NULL
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.association_author_evidence x WHERE x.organization_id=p_org AND x.batch_id=p_batch AND x.author_id=target AND x.evidence_id=ANY(p_evidence))
 OR EXISTS(SELECT 1 FROM emailmonitor.association_evidence x WHERE x.organization_id=p_org AND x.batch_id=p_batch AND x.id=ANY(p_evidence) AND length(x.excerpt)=0))
 THEN RAISE EXCEPTION 'ASSOCIATION_ACCEPTANCE_EVIDENCE'; END IF;
 updated:=a.record||jsonb_build_object('state',CASE WHEN p_action='reject' THEN 'rejected' ELSE 'accepted' END,
 'reason','reviewed_evidence','revision',a.revision+1,'evidence_ids',to_jsonb(p_evidence));
 IF p_action<>'reject' THEN updated:=updated||jsonb_build_object('author_id',target,'evidence_strength','supported'); END IF;
 UPDATE emailmonitor.author_email_associations SET record=updated WHERE organization_id=p_org AND batch_id=p_batch AND id=p_association;
 DELETE FROM emailmonitor.association_evidence_links WHERE organization_id=p_org AND batch_id=p_batch AND association_id=p_association;
 FOREACH cited IN ARRAY p_evidence LOOP
 INSERT INTO emailmonitor.association_evidence_links VALUES(p_org,p_batch,p_association,cited);
 END LOOP;
 actor:=emailmonitor.job_actor();
 INSERT INTO emailmonitor.association_reviews(organization_id,batch_id,id,association_id,actor,action,previous_record,new_record,expected_revision,reason)
 VALUES(p_org,p_batch,p_review,p_association,actor,p_action,a.record,updated,p_revision,p_reason);
 FOREACH cited IN ARRAY p_evidence LOOP
 INSERT INTO emailmonitor.association_review_evidence VALUES(p_org,p_batch,p_review,cited);
 END LOOP;
 INSERT INTO emailmonitor.association_outbox(organization_id,batch_id,event_id,association_id,revision,event_type)
 VALUES(p_org,p_batch,p_event,p_association,a.revision+1,'association.reviewed');
 INSERT INTO emailmonitor.audit_events(organization_id,id,actor_id,action,resource_id)
 VALUES(p_org,p_event,actor,'association.reviewed',p_association);
 RETURN a.revision+1;
END $$;
CREATE FUNCTION emailmonitor.association_insert_allowed(p_org uuid,p_batch uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT emailmonitor.tenant_allowed(p_org) AND EXISTS(SELECT 1 FROM emailmonitor.association_batches b
 WHERE b.organization_id=p_org AND b.id=p_batch AND NOT b.sealed AND emailmonitor.job_write_allowed(p_org,b.job_id))
$$;

CREATE FUNCTION emailmonitor.lock_association_batch(p_org uuid,p_batch uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE b emailmonitor.association_batches;
BEGIN
 SELECT * INTO b FROM emailmonitor.association_batches WHERE organization_id=p_org AND id=p_batch FOR SHARE;
 PERFORM emailmonitor.association_parent_fence(b.organization_id,b.job_id,b.article_url,b.source_revision);
 IF b.id IS NULL OR NOT b.sealed OR b.expires_at<=clock_timestamp()
 THEN RAISE EXCEPTION 'ASSOCIATION_DENIED' USING ERRCODE='EM009'; END IF;
END $$;

-- Forced tenant/current-source RLS and isolated function privileges.
ALTER TABLE emailmonitor.association_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.association_batches FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.association_batches TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_read ON emailmonitor.association_batches FOR SELECT TO emailmonitor_runtime USING(emailmonitor.association_visible(organization_id,id));
REVOKE ALL ON emailmonitor.association_batches FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT SELECT ON emailmonitor.association_batches TO emailmonitor_runtime;
CREATE POLICY tenant_insert ON emailmonitor.association_batches FOR INSERT TO emailmonitor_runtime WITH CHECK(emailmonitor.job_write_allowed(organization_id,job_id) AND NOT sealed);
GRANT INSERT ON emailmonitor.association_batches TO emailmonitor_runtime;
ALTER TABLE emailmonitor.association_authors ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.association_authors FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.association_authors TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_read ON emailmonitor.association_authors FOR SELECT TO emailmonitor_runtime USING(emailmonitor.association_visible(organization_id,batch_id));
REVOKE ALL ON emailmonitor.association_authors FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT SELECT ON emailmonitor.association_authors TO emailmonitor_runtime;
CREATE POLICY tenant_insert ON emailmonitor.association_authors FOR INSERT TO emailmonitor_runtime WITH CHECK(emailmonitor.association_insert_allowed(organization_id,batch_id));
GRANT INSERT ON emailmonitor.association_authors TO emailmonitor_runtime;
ALTER TABLE emailmonitor.association_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.association_candidates FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.association_candidates TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_read ON emailmonitor.association_candidates FOR SELECT TO emailmonitor_runtime USING(emailmonitor.association_visible(organization_id,batch_id));
REVOKE ALL ON emailmonitor.association_candidates FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT SELECT ON emailmonitor.association_candidates TO emailmonitor_runtime;
CREATE POLICY tenant_insert ON emailmonitor.association_candidates FOR INSERT TO emailmonitor_runtime WITH CHECK(emailmonitor.association_insert_allowed(organization_id,batch_id));
GRANT INSERT ON emailmonitor.association_candidates TO emailmonitor_runtime;
ALTER TABLE emailmonitor.association_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.association_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.association_evidence TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_read ON emailmonitor.association_evidence FOR SELECT TO emailmonitor_runtime USING(emailmonitor.association_visible(organization_id,batch_id));
REVOKE ALL ON emailmonitor.association_evidence FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT SELECT ON emailmonitor.association_evidence TO emailmonitor_runtime;
CREATE POLICY tenant_insert ON emailmonitor.association_evidence FOR INSERT TO emailmonitor_runtime WITH CHECK(emailmonitor.association_insert_allowed(organization_id,batch_id));
GRANT INSERT ON emailmonitor.association_evidence TO emailmonitor_runtime;
ALTER TABLE emailmonitor.author_email_associations ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.author_email_associations FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.author_email_associations TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_read ON emailmonitor.author_email_associations FOR SELECT TO emailmonitor_runtime USING(emailmonitor.association_visible(organization_id,batch_id));
REVOKE ALL ON emailmonitor.author_email_associations FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT SELECT ON emailmonitor.author_email_associations TO emailmonitor_runtime;
CREATE POLICY tenant_insert ON emailmonitor.author_email_associations FOR INSERT TO emailmonitor_runtime WITH CHECK(emailmonitor.association_insert_allowed(organization_id,batch_id));
GRANT INSERT ON emailmonitor.author_email_associations TO emailmonitor_runtime;
ALTER TABLE emailmonitor.association_affiliations ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.association_affiliations FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.association_affiliations TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_read ON emailmonitor.association_affiliations FOR SELECT TO emailmonitor_runtime USING(emailmonitor.association_visible(organization_id,batch_id));
REVOKE ALL ON emailmonitor.association_affiliations FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT SELECT ON emailmonitor.association_affiliations TO emailmonitor_runtime;
CREATE POLICY tenant_insert ON emailmonitor.association_affiliations FOR INSERT TO emailmonitor_runtime WITH CHECK(emailmonitor.association_insert_allowed(organization_id,batch_id));
GRANT INSERT ON emailmonitor.association_affiliations TO emailmonitor_runtime;
ALTER TABLE emailmonitor.association_raw_variants ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.association_raw_variants FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.association_raw_variants TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_read ON emailmonitor.association_raw_variants FOR SELECT TO emailmonitor_runtime USING(emailmonitor.association_visible(organization_id,batch_id));
REVOKE ALL ON emailmonitor.association_raw_variants FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT SELECT ON emailmonitor.association_raw_variants TO emailmonitor_runtime;
CREATE POLICY tenant_insert ON emailmonitor.association_raw_variants FOR INSERT TO emailmonitor_runtime WITH CHECK(emailmonitor.association_insert_allowed(organization_id,batch_id));
GRANT INSERT ON emailmonitor.association_raw_variants TO emailmonitor_runtime;
ALTER TABLE emailmonitor.association_author_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.association_author_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.association_author_evidence TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_read ON emailmonitor.association_author_evidence FOR SELECT TO emailmonitor_runtime USING(emailmonitor.association_visible(organization_id,batch_id));
REVOKE ALL ON emailmonitor.association_author_evidence FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT SELECT ON emailmonitor.association_author_evidence TO emailmonitor_runtime;
CREATE POLICY tenant_insert ON emailmonitor.association_author_evidence FOR INSERT TO emailmonitor_runtime WITH CHECK(emailmonitor.association_insert_allowed(organization_id,batch_id));
GRANT INSERT ON emailmonitor.association_author_evidence TO emailmonitor_runtime;
ALTER TABLE emailmonitor.association_candidate_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.association_candidate_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.association_candidate_evidence TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_read ON emailmonitor.association_candidate_evidence FOR SELECT TO emailmonitor_runtime USING(emailmonitor.association_visible(organization_id,batch_id));
REVOKE ALL ON emailmonitor.association_candidate_evidence FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT SELECT ON emailmonitor.association_candidate_evidence TO emailmonitor_runtime;
CREATE POLICY tenant_insert ON emailmonitor.association_candidate_evidence FOR INSERT TO emailmonitor_runtime WITH CHECK(emailmonitor.association_insert_allowed(organization_id,batch_id));
GRANT INSERT ON emailmonitor.association_candidate_evidence TO emailmonitor_runtime;
ALTER TABLE emailmonitor.association_evidence_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.association_evidence_links FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.association_evidence_links TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_read ON emailmonitor.association_evidence_links FOR SELECT TO emailmonitor_runtime USING(emailmonitor.association_visible(organization_id,batch_id));
REVOKE ALL ON emailmonitor.association_evidence_links FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT SELECT ON emailmonitor.association_evidence_links TO emailmonitor_runtime;
CREATE POLICY tenant_insert ON emailmonitor.association_evidence_links FOR INSERT TO emailmonitor_runtime WITH CHECK(emailmonitor.association_insert_allowed(organization_id,batch_id));
GRANT INSERT ON emailmonitor.association_evidence_links TO emailmonitor_runtime;
ALTER TABLE emailmonitor.association_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.association_reviews FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.association_reviews TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_read ON emailmonitor.association_reviews FOR SELECT TO emailmonitor_runtime USING(emailmonitor.association_visible(organization_id,batch_id));
REVOKE ALL ON emailmonitor.association_reviews FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT SELECT ON emailmonitor.association_reviews TO emailmonitor_runtime;
ALTER TABLE emailmonitor.association_review_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.association_review_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.association_review_evidence TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_read ON emailmonitor.association_review_evidence FOR SELECT TO emailmonitor_runtime USING(emailmonitor.association_visible(organization_id,batch_id));
REVOKE ALL ON emailmonitor.association_review_evidence FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT SELECT ON emailmonitor.association_review_evidence TO emailmonitor_runtime;
ALTER TABLE emailmonitor.association_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.association_outbox FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_all ON emailmonitor.association_outbox TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_read ON emailmonitor.association_outbox FOR SELECT TO emailmonitor_runtime USING(emailmonitor.association_visible(organization_id,batch_id));
REVOKE ALL ON emailmonitor.association_outbox FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT SELECT ON emailmonitor.association_outbox TO emailmonitor_runtime;
REVOKE ALL ON FUNCTION emailmonitor.association_parent_fence(uuid,uuid,text,bigint,boolean) FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
REVOKE ALL ON FUNCTION emailmonitor.association_visible(uuid,uuid) FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT EXECUTE ON FUNCTION emailmonitor.association_visible(uuid,uuid) TO emailmonitor_runtime;
REVOKE ALL ON FUNCTION emailmonitor.guard_association_batch() FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
REVOKE ALL ON FUNCTION emailmonitor.guard_association_record() FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
REVOKE ALL ON FUNCTION emailmonitor.guard_association_relation() FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
REVOKE ALL ON FUNCTION emailmonitor.seal_association_batch(uuid,uuid) FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT EXECUTE ON FUNCTION emailmonitor.seal_association_batch(uuid,uuid) TO emailmonitor_runtime;
REVOKE ALL ON FUNCTION emailmonitor.review_association(uuid,uuid,uuid,bigint,text,uuid,uuid[],text,uuid,uuid) FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT EXECUTE ON FUNCTION emailmonitor.review_association(uuid,uuid,uuid,bigint,text,uuid,uuid[],text,uuid,uuid) TO emailmonitor_runtime;
REVOKE ALL ON FUNCTION emailmonitor.association_insert_allowed(uuid,uuid) FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT EXECUTE ON FUNCTION emailmonitor.association_insert_allowed(uuid,uuid) TO emailmonitor_runtime;
REVOKE ALL ON FUNCTION emailmonitor.lock_association_batch(uuid,uuid) FROM PUBLIC,emailmonitor_authenticator,emailmonitor_runtime;
GRANT EXECUTE ON FUNCTION emailmonitor.lock_association_batch(uuid,uuid) TO emailmonitor_runtime;
RESET ROLE;
