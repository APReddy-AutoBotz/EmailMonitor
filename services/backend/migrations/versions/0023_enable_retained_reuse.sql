-- Packaging companion for the unchanged 0023 inline Alembic operations.
SET ROLE emailmonitor_owner;

ALTER TABLE emailmonitor.article_observations DROP CONSTRAINT retained_reuse_disabled;

CREATE OR REPLACE FUNCTION emailmonitor.service_schema_ready() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT (SELECT count(*)=1 AND min(version_num)='0023_enable_retained_reuse'
 FROM public.alembic_version)
$$;

RESET ROLE;
