-- Audited association unlink: same tenant, reviewer role, evidence and revision fences.
SET ROLE emailmonitor_owner;
ALTER TABLE emailmonitor.association_reviews DROP CONSTRAINT association_reviews_action_check;
ALTER TABLE emailmonitor.association_reviews ADD CONSTRAINT association_reviews_action_check
 CHECK(action IN ('accept','reject','correct','unlink'));

CREATE OR REPLACE FUNCTION emailmonitor.guard_association_record() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
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
 OR OLD.record->>'state'='suppressed'
 OR NOT COALESCE((
  (NEW.record->>'state' IN ('accepted','rejected') AND NEW.record->>'reason'='reviewed_evidence')
  OR (NEW.record->>'state'='needs_review' AND NEW.record->>'reason'='reviewed_unlinked'
   AND OLD.record->>'author_id' IS NOT NULL AND NEW.record->'author_id'='null'::jsonb
   AND NEW.record->>'evidence_strength'='ambiguous'
   AND NEW.record->'evidence_ids' IS NOT DISTINCT FROM OLD.record->'evidence_ids')
 ),false)
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


CREATE OR REPLACE FUNCTION emailmonitor.review_association(p_org uuid,p_batch uuid,p_association uuid,p_revision bigint,
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
 IF p_action IS NULL OR p_action NOT IN ('accept','reject','correct','unlink') OR a.state='suppressed'
 OR p_evidence IS NULL OR cardinality(p_evidence) NOT BETWEEN 1 AND 40
 OR cardinality(p_evidence)<>(SELECT count(DISTINCT e) FROM unnest(p_evidence) e)
 OR p_reason IS NULL OR length(p_reason) NOT BETWEEN 1 AND 300 OR p_review IS NULL OR p_event IS NULL
 OR (p_action='correct' AND p_author IS NULL) OR (p_action='reject' AND p_author IS NOT NULL)
 OR (p_action='unlink' AND (p_author IS NOT NULL OR a.author_id IS NULL
 OR a.record->'evidence_ids' IS DISTINCT FROM to_jsonb(p_evidence)))
 OR EXISTS(SELECT 1 FROM unnest(p_evidence) e WHERE NOT EXISTS(SELECT 1 FROM emailmonitor.association_evidence x
 WHERE x.organization_id=p_org AND x.batch_id=p_batch AND x.id=e))
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.association_candidate_evidence x WHERE x.organization_id=p_org AND x.batch_id=p_batch
 AND x.candidate_id=a.candidate_id AND x.evidence_id=ANY(p_evidence))
 THEN RAISE EXCEPTION 'ASSOCIATION_REVIEW_INPUT'; END IF;
 target:=COALESCE(p_author,a.author_id);
 IF p_action IN ('accept','correct') AND (target IS NULL
 OR NOT EXISTS(SELECT 1 FROM emailmonitor.association_author_evidence x WHERE x.organization_id=p_org AND x.batch_id=p_batch AND x.author_id=target AND x.evidence_id=ANY(p_evidence))
 OR EXISTS(SELECT 1 FROM emailmonitor.association_evidence x WHERE x.organization_id=p_org AND x.batch_id=p_batch AND x.id=ANY(p_evidence) AND length(x.excerpt)=0))
 THEN RAISE EXCEPTION 'ASSOCIATION_ACCEPTANCE_EVIDENCE'; END IF;
 updated:=a.record||jsonb_build_object('state',CASE WHEN p_action='unlink' THEN 'needs_review'
 WHEN p_action='reject' THEN 'rejected' ELSE 'accepted' END,
 'reason',CASE WHEN p_action='unlink' THEN 'reviewed_unlinked' ELSE 'reviewed_evidence' END,
 'revision',a.revision+1,'evidence_ids',to_jsonb(p_evidence));
 IF p_action='unlink' THEN updated:=updated||jsonb_build_object('author_id',NULL,'evidence_strength','ambiguous');
 ELSIF p_action<>'reject' THEN updated:=updated||jsonb_build_object('author_id',target,'evidence_strength','supported'); END IF;
 UPDATE emailmonitor.author_email_associations SET record=updated WHERE organization_id=p_org AND batch_id=p_batch AND id=p_association;
 IF p_action<>'unlink' THEN
  DELETE FROM emailmonitor.association_evidence_links WHERE organization_id=p_org AND batch_id=p_batch AND association_id=p_association;
  FOREACH cited IN ARRAY p_evidence LOOP
   INSERT INTO emailmonitor.association_evidence_links VALUES(p_org,p_batch,p_association,cited);
  END LOOP;
 END IF;
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

CREATE OR REPLACE FUNCTION emailmonitor.service_schema_ready() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT (SELECT count(*)=1 AND min(version_num)='0021_review_unlink' FROM public.alembic_version)
$$;
RESET ROLE;
