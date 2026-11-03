-- EM-002. Run through the migration role, never through application credentials.
-- Roles have no passwords; deployment credentials remain an operator decision.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='emailmonitor_owner') THEN
    CREATE ROLE emailmonitor_owner NOLOGIN NOSUPERUSER NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='emailmonitor_runtime') THEN
    CREATE ROLE emailmonitor_runtime NOLOGIN NOSUPERUSER NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='emailmonitor_authenticator') THEN
    CREATE ROLE emailmonitor_authenticator NOLOGIN NOSUPERUSER NOBYPASSRLS;
  END IF;
END $$;
CREATE SCHEMA emailmonitor AUTHORIZATION emailmonitor_owner;
REVOKE ALL ON SCHEMA emailmonitor FROM PUBLIC;
GRANT USAGE ON SCHEMA emailmonitor TO emailmonitor_runtime,emailmonitor_authenticator;
SET ROLE emailmonitor_owner;

CREATE TABLE emailmonitor.identities (
  id uuid PRIMARY KEY, issuer text NOT NULL, subject text NOT NULL,
  active boolean NOT NULL DEFAULT true, permission_revision bigint NOT NULL DEFAULT 1,
  UNIQUE (issuer,subject)
);
CREATE TABLE emailmonitor.organizations (
  id uuid PRIMARY KEY, display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
  status text NOT NULL CHECK (status IN ('provisioning','active','suspended','offboarding','deleted')),
  region text NOT NULL, timezone text NOT NULL DEFAULT 'UTC', row_version bigint NOT NULL DEFAULT 1
);
CREATE TABLE emailmonitor.memberships (
  organization_id uuid NOT NULL REFERENCES emailmonitor.organizations(id),
  identity_id uuid NOT NULL REFERENCES emailmonitor.identities(id),
  role text NOT NULL CHECK (role IN ('owner','admin','data_steward','operator','reviewer','viewer')),
  status text NOT NULL CHECK (status IN ('active','revoked')),
  row_version bigint NOT NULL DEFAULT 1,
  PRIMARY KEY(organization_id, identity_id)
);
CREATE TABLE emailmonitor.sessions (
  token_hash text PRIMARY KEY CHECK (length(token_hash)=64),
  csrf_hash text NOT NULL CHECK (length(csrf_hash)=64),
  identity_id uuid NOT NULL REFERENCES emailmonitor.identities(id),
  permission_revision bigint NOT NULL, expires_at timestamptz NOT NULL,
  revoked_at timestamptz
);
CREATE TABLE emailmonitor.login_flows (
  state_hash text PRIMARY KEY CHECK (length(state_hash)=64),
  nonce text NOT NULL, verifier text NOT NULL, expires_at timestamptz NOT NULL
);
CREATE TABLE emailmonitor.audit_events (
  organization_id uuid NOT NULL REFERENCES emailmonitor.organizations(id),
  id uuid NOT NULL, actor_id uuid NOT NULL REFERENCES emailmonitor.identities(id),
  action text NOT NULL, resource_id uuid NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(organization_id,id)
);

CREATE FUNCTION emailmonitor.resolve_session(p_hash text)
RETURNS TABLE(identity_id uuid, csrf_hash text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
  SELECT s.identity_id,s.csrf_hash FROM emailmonitor.sessions s
  JOIN emailmonitor.identities i ON i.id=s.identity_id
  WHERE s.token_hash=p_hash AND s.revoked_at IS NULL AND s.expires_at>now()
    AND i.active AND s.permission_revision=i.permission_revision
$$;
CREATE FUNCTION emailmonitor.session_role(p_org uuid)
RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
  SELECT m.role FROM emailmonitor.memberships m
  JOIN emailmonitor.resolve_session(current_setting('emailmonitor.session_hash',true)) s
    ON s.identity_id=m.identity_id
  WHERE m.organization_id=p_org AND m.status='active'
$$;
CREATE FUNCTION emailmonitor.tenant_allowed(p_org uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
  SELECT p_org::text = current_setting('emailmonitor.organization_id',true)
    AND emailmonitor.session_role(p_org) IS NOT NULL
    AND EXISTS(SELECT 1 FROM emailmonitor.organizations o WHERE o.id=p_org AND
      (o.status='active' OR (current_setting('emailmonitor.lifecycle_recovery',true)='true'
       AND emailmonitor.session_role(p_org)='owner' AND o.status<>'deleted')))
$$;
CREATE FUNCTION emailmonitor.resolve_membership(p_hash text,p_org uuid)
RETURNS TABLE(identity_id uuid,role text,organization_status text,row_version bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
  SELECT s.identity_id,m.role,o.status,m.row_version FROM emailmonitor.resolve_session(p_hash) s
  JOIN emailmonitor.memberships m ON m.identity_id=s.identity_id AND m.status='active'
  JOIN emailmonitor.organizations o ON o.id=m.organization_id
  WHERE m.organization_id=p_org
$$;
CREATE FUNCTION emailmonitor.list_memberships(p_hash text)
RETURNS TABLE(organization_id uuid,role text,organization_status text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
  SELECT m.organization_id,m.role,o.status FROM emailmonitor.resolve_session(p_hash) s
  JOIN emailmonitor.memberships m ON m.identity_id=s.identity_id AND m.status='active'
  JOIN emailmonitor.organizations o ON o.id=m.organization_id
$$;
CREATE FUNCTION emailmonitor.member_identity_allowed(p_identity uuid,p_issuer text)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
  SELECT emailmonitor.session_role(nullif(current_setting('emailmonitor.organization_id',true),'')::uuid)
    IN ('owner','admin') AND EXISTS(SELECT 1 FROM emailmonitor.identities i
      WHERE i.id=p_identity AND i.issuer=p_issuer AND i.active)
$$;
CREATE FUNCTION emailmonitor.put_login_flow(p_state text,p_nonce text,p_verifier text)
RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
  INSERT INTO emailmonitor.login_flows VALUES(p_state,p_nonce,p_verifier,now()+interval '5 minutes')
$$;
CREATE FUNCTION emailmonitor.consume_login_flow(p_state text)
RETURNS TABLE(nonce text,verifier text)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
  DELETE FROM emailmonitor.login_flows WHERE state_hash=p_state AND expires_at>now()
  RETURNING nonce,verifier
$$;
CREATE FUNCTION emailmonitor.establish_session(p_issuer text,p_subject text,p_token text,p_csrf text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
DECLARE v_identity uuid; v_revision bigint;
BEGIN
  SELECT id,permission_revision INTO v_identity,v_revision FROM emailmonitor.identities
    WHERE issuer=p_issuer AND subject=p_subject AND active;
  IF v_identity IS NULL THEN RAISE EXCEPTION 'IDENTITY_UNAVAILABLE'; END IF;
  INSERT INTO emailmonitor.sessions VALUES(p_token,p_csrf,v_identity,v_revision,
    now()+interval '1 hour',NULL);
END $$;
CREATE FUNCTION emailmonitor.revoke_session(p_hash text)
RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
  UPDATE emailmonitor.sessions SET revoked_at=now() WHERE token_hash=p_hash
$$;

-- Every tenant relation has explicit forced RLS. Owner migration/bootstrap access
-- is a separate named policy, never a grant of table ownership to runtime.
ALTER TABLE emailmonitor.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.organizations FORCE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.memberships FORCE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE emailmonitor.audit_events FORCE ROW LEVEL SECURITY;
CREATE POLICY org_owner ON emailmonitor.organizations TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY member_owner ON emailmonitor.memberships TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY audit_owner ON emailmonitor.audit_events TO emailmonitor_owner USING(true) WITH CHECK(true);
CREATE POLICY org_read ON emailmonitor.organizations FOR SELECT TO emailmonitor_runtime
  USING(emailmonitor.tenant_allowed(id));
CREATE POLICY org_write ON emailmonitor.organizations FOR UPDATE TO emailmonitor_runtime
  USING(emailmonitor.tenant_allowed(id) AND emailmonitor.session_role(id)='owner')
  WITH CHECK(emailmonitor.tenant_allowed(id) AND emailmonitor.session_role(id)='owner');
CREATE POLICY member_read ON emailmonitor.memberships FOR SELECT TO emailmonitor_runtime
  USING(emailmonitor.tenant_allowed(organization_id));
CREATE POLICY member_write ON emailmonitor.memberships FOR UPDATE TO emailmonitor_runtime
  USING(emailmonitor.tenant_allowed(organization_id) AND
    (emailmonitor.session_role(organization_id)='owner' OR
     (emailmonitor.session_role(organization_id)='admin' AND role<>'owner')))
  WITH CHECK(emailmonitor.tenant_allowed(organization_id) AND
    (emailmonitor.session_role(organization_id)='owner' OR
     (emailmonitor.session_role(organization_id)='admin' AND role<>'owner')));
CREATE POLICY member_insert ON emailmonitor.memberships FOR INSERT TO emailmonitor_runtime
  WITH CHECK(emailmonitor.tenant_allowed(organization_id) AND
    (emailmonitor.session_role(organization_id)='owner' OR
     (emailmonitor.session_role(organization_id)='admin' AND role<>'owner')));
CREATE POLICY audit_read ON emailmonitor.audit_events FOR SELECT TO emailmonitor_runtime
  USING(emailmonitor.tenant_allowed(organization_id) AND
        emailmonitor.session_role(organization_id) IN ('owner','admin'));
CREATE POLICY audit_insert ON emailmonitor.audit_events FOR INSERT TO emailmonitor_runtime
  WITH CHECK(emailmonitor.tenant_allowed(organization_id) AND actor_id=(
    SELECT identity_id FROM emailmonitor.resolve_session(current_setting('emailmonitor.session_hash',true))));

CREATE FUNCTION emailmonitor.guard_membership() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
  PERFORM 1 FROM emailmonitor.organizations WHERE id=OLD.organization_id FOR UPDATE;
  IF NEW.organization_id<>OLD.organization_id OR NEW.identity_id<>OLD.identity_id THEN
    RAISE EXCEPTION 'MEMBERSHIP_ID_IMMUTABLE';
  END IF;
  IF OLD.role='owner' AND OLD.status='active' AND
    (NEW.role<>'owner' OR NEW.status<>'active') AND
    (SELECT count(*) FROM emailmonitor.memberships
      WHERE organization_id=OLD.organization_id AND role='owner' AND status='active')<=1 THEN
    RAISE EXCEPTION 'LAST_OWNER_REQUIRED';
  END IF;
  NEW.row_version=OLD.row_version+1;
  RETURN NEW;
END $$;
CREATE TRIGGER membership_guard BEFORE UPDATE ON emailmonitor.memberships
  FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_membership();

CREATE FUNCTION emailmonitor.invalidate_membership_sessions() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
  IF NEW.role<>OLD.role OR NEW.status<>OLD.status THEN
    UPDATE emailmonitor.identities SET permission_revision=permission_revision+1 WHERE id=OLD.identity_id;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER membership_session_revision AFTER UPDATE ON emailmonitor.memberships
  FOR EACH ROW EXECUTE FUNCTION emailmonitor.invalidate_membership_sessions();

CREATE FUNCTION emailmonitor.guard_organization() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
BEGIN
  IF NEW.id<>OLD.id THEN RAISE EXCEPTION 'ORGANIZATION_ID_IMMUTABLE'; END IF;
  IF NEW.status<>OLD.status AND NOT (
    (OLD.status='provisioning' AND NEW.status IN ('active','offboarding')) OR
    (OLD.status='active' AND NEW.status IN ('suspended','offboarding')) OR
    (OLD.status='suspended' AND NEW.status IN ('active','offboarding')) OR
    (OLD.status='offboarding' AND NEW.status='deleted')) THEN
    RAISE EXCEPTION 'INVALID_ORGANIZATION_TRANSITION';
  END IF;
  IF NEW.status='active' AND NOT EXISTS(SELECT 1 FROM emailmonitor.memberships
      WHERE organization_id=NEW.id AND role='owner' AND status='active') THEN
    RAISE EXCEPTION 'ACTIVE_OWNER_REQUIRED';
  END IF;
  NEW.row_version=OLD.row_version+1;
  RETURN NEW;
END $$;
CREATE TRIGGER organization_guard BEFORE UPDATE ON emailmonitor.organizations
  FOR EACH ROW EXECUTE FUNCTION emailmonitor.guard_organization();

REVOKE ALL ON ALL TABLES IN SCHEMA emailmonitor FROM PUBLIC,emailmonitor_runtime;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA emailmonitor FROM PUBLIC;
GRANT SELECT,UPDATE ON emailmonitor.organizations,emailmonitor.memberships TO emailmonitor_runtime;
GRANT INSERT ON emailmonitor.memberships TO emailmonitor_runtime;
GRANT SELECT,INSERT ON emailmonitor.audit_events TO emailmonitor_runtime;
GRANT EXECUTE ON FUNCTION emailmonitor.resolve_session(text),emailmonitor.session_role(uuid),
 emailmonitor.tenant_allowed(uuid),emailmonitor.resolve_membership(text,uuid),
 emailmonitor.list_memberships(text),emailmonitor.member_identity_allowed(uuid,text),
 emailmonitor.revoke_session(text) TO emailmonitor_runtime;
-- Authentication is a separate trusted verifier principal. Tenant runtime cannot
-- create sessions or read/consume pending PKCE material. Never grant membership
-- between these roles; runtime connection startup checks both MEMBER and SET.
GRANT EXECUTE ON FUNCTION emailmonitor.put_login_flow(text,text,text),
 emailmonitor.consume_login_flow(text),emailmonitor.establish_session(text,text,text,text)
 TO emailmonitor_authenticator;
RESET ROLE;
