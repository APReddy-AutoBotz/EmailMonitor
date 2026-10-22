"""Portable synthetic schema seals shared by migration and restore acceptance."""

# OIDs, relfilenodes, planner statistics and database names are intentionally
# excluded. Definitions, owners, explicit ACLs (including column ACLs), policies,
# indexes and triggers are compared, not just the Alembic revision string.
CATALOG_QUERIES = {
    "schemas": """
        SELECT nspname,pg_get_userbyid(nspowner),nspacl::text FROM pg_namespace
        WHERE nspname='emailmonitor' ORDER BY nspname
    """,
    "relations": """
        SELECT c.relname,c.relkind,pg_get_userbyid(c.relowner),c.relrowsecurity,
        c.relforcerowsecurity,
        (CASE WHEN c.relkind IN ('r','p','v','m','f','S') THEN
          COALESCE(c.relacl,acldefault(
            CASE WHEN c.relkind='S' THEN 's'::"char" ELSE 'r'::"char" END,c.relowner))
          ELSE c.relacl END)::text AS relacl,c.reloptions
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='emailmonitor' ORDER BY c.relname
    """,
    "columns": """
        SELECT c.relname,a.attnum,a.attname,format_type(a.atttypid,a.atttypmod),
        a.attnotnull,a.attidentity,a.attgenerated,a.attacl::text,
        pg_get_expr(d.adbin,d.adrelid)
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        WHERE n.nspname='emailmonitor' AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY c.relname,a.attnum
    """,
    "constraints": """
        SELECT c.relname,k.conname,k.contype,pg_get_constraintdef(k.oid,true),
        k.convalidated,k.condeferrable,k.condeferred
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='emailmonitor' ORDER BY c.relname,k.conname
    """,
    "indexes": """
        SELECT tablename,indexname,indexdef FROM pg_indexes
        WHERE schemaname='emailmonitor' ORDER BY tablename,indexname
    """,
    "functions": """
        SELECT p.proname,pg_get_function_identity_arguments(p.oid),
        pg_get_userbyid(p.proowner),p.proacl::text,p.prosecdef,p.proconfig,
        pg_get_functiondef(p.oid)
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='emailmonitor'
        ORDER BY p.proname,pg_get_function_identity_arguments(p.oid)
    """,
    "policies": """
        SELECT tablename,policyname,permissive,roles,cmd,qual,with_check
        FROM pg_policies WHERE schemaname='emailmonitor'
        ORDER BY tablename,policyname
    """,
    "triggers": """
        SELECT c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid,true)
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='emailmonitor' AND NOT t.tgisinternal
        ORDER BY c.relname,t.tgname
    """,
    "default_acls": """
        SELECT pg_get_userbyid(d.defaclrole),n.nspname,d.defaclobjtype,d.defaclacl::text
        FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace
        WHERE n.nspname='emailmonitor' OR d.defaclnamespace=0
        ORDER BY 1,2,3
    """,
    "revision_acl": """
        SELECT pg_get_userbyid(c.relowner),c.relacl::text FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname='alembic_version'
    """,
}
