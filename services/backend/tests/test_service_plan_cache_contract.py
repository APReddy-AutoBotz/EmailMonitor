"""Only an executable plan may be reused; the authority SELECT is unchanged."""

import ast
from pathlib import Path

import sqlparse

ROOT = Path(__file__).parents[1] / "migrations/versions"
OLD = ROOT / "0014_service_authority.sql"
NEW = ROOT / "0015_service_plan_cache.sql"


def test_forward_migration_preserves_exact_authority_select_and_function_properties() -> None:
    old, new = OLD.read_text(), NEW.read_text()
    prefix = "CREATE FUNCTION emailmonitor.service_delegation_current(p_org uuid,p_id uuid)"
    original = old.split(prefix, 1)[1].split("$$;", 1)[0]
    header, body = original.split("AS $$", 1)
    replacement = new.split(prefix.replace("CREATE", "CREATE OR REPLACE"), 1)[1].split("$$;", 1)[0]
    new_header, wrapper = replacement.split("AS $$", 1)
    assert new_header == header.replace("LANGUAGE sql", "LANGUAGE plpgsql")
    assert wrapper == "\nBEGIN\n RETURN (" + body + ");\nEND;\n"
    # Live clocks remain expressions inside the same SELECT, never variables.
    assert body.count("clock_timestamp()") == 3
    assert "FOR UPDATE" not in body and "FOR SHARE" not in body
    assert "EXECUTE " not in wrapper
    statements = sqlparse.split(new)
    assert len(statements) == 4
    assert statements[0].endswith("SET ROLE emailmonitor_owner;")
    assert statements[-1] == "RESET ROLE;"
    assert all("GRANT " not in statement and "REVOKE " not in statement for statement in statements)


def test_schema_sentinel_changes_only_exact_revision() -> None:
    old = (
        OLD.read_text()
        .split("CREATE FUNCTION emailmonitor.service_schema_ready()", 1)[1]
        .split("$$;", 1)[0]
    )
    new = (
        NEW.read_text()
        .split("CREATE OR REPLACE FUNCTION emailmonitor.service_schema_ready()", 1)[1]
        .split("$$;", 1)[0]
    )
    assert new == old.replace("0014_service_authority", "0015_service_plan_cache")
    assert "0014_service_authority" not in new


def test_migration_is_forward_only_and_parented_to_published_authority_schema() -> None:
    module = ast.parse(NEW.with_suffix(".py").read_text())
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
    }
    assert assignments["revision"] == "0015_service_plan_cache"
    assert assignments["down_revision"] == "0014_service_authority"
    downgrade = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
    )
    assert len(downgrade.body) == 1 and isinstance(downgrade.body[0], ast.Raise)
