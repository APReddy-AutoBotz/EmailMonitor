"""Pure closed browser operator grammar and opt-in assertions; no service proof."""

import ast
from pathlib import Path

import pytest
from operator_ui_protocol import validate_journey

ROOT = Path(__file__).resolve().parents[3]


def bootstrap() -> dict[str, object]:
    return {
        "kind": "bootstrap",
        "origin": "https://app.example.test",
        "journey": "controlled_browser",
        "cookies": [],
        "assets": {},
        "initial_organization": "synthetic-a",
        "other_organization": "synthetic-b",
    }


def test_only_fixed_browser_journey_without_route_parameters() -> None:
    validate_journey(bootstrap())
    validate_journey({})
    validate_journey({"journey": "controlled_provider", "direct_article_url": True})


@pytest.mark.parametrize(
    "field", ["url", "route", "profile", "direct_article_url", "allow_browser"]
)
def test_browser_bootstrap_refuses_general_route_or_permission_parameters(field: str) -> None:
    with pytest.raises(ValueError, match="Fixed controlled browser bootstrap"):
        validate_journey({**bootstrap(), field: "https://unknown.example/"})


@pytest.mark.parametrize("journey", ["browser", "custom", "", 1, True, [], {}])
def test_unknown_journey_is_not_a_static_fallback(journey: object) -> None:
    with pytest.raises(ValueError, match="Fixed controlled operator journey"):
        validate_journey({"journey": journey})


def test_browser_journey_has_fixed_url_and_keyboard_only_explicit_opt_in() -> None:
    guest = (ROOT / "scripts/isolation/operator_ui_acceptance.py").read_text()
    branch = next(
        node
        for node in ast.walk(ast.parse(guest))
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "setup.get('journey') == 'controlled_browser'"
    )
    code = ast.unparse(branch)
    assert "https://synthetic.publisher.example/tooltip.html" in code
    assert "await expect(browser_opt_in).not_to_be_checked()" in code
    assert "await activate(page, browser_opt_in)" in code
    assert "await expect(browser_opt_in).to_be_checked()" in code
    assert code.index("not_to_be_checked") < code.index("activate(page, browser_opt_in)")
    assert "'html_browser'" in code and "'allow_browser': True" in code
    assert "wait_for(timeout=75000)" in code
    assert "elena.park@example.org" in code
    assert "fetch(" not in code and "route_from_har" not in code
    host = (ROOT / "scripts/isolation/test_operator_browser_acceptance.py").read_text()
    assert 'options["allow_browser"] is True' in host
    assert 'retained[0].route == "browser_dom"' in host
    assert 'len(calls) == 2 and len(receipts["queries"]) == 4' in host
    assert "topology.browser()" in host and host.count("topology.browser()") == 1
    assert "with browser_worker(" in host
    assert '"guest_stopped"' in host
