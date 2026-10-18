"""Pure closed browser operator grammar and opt-in assertions; no service proof."""

import ast
import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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
    assert "await focus(page, browser_opt_in)" in code
    assert "await page.keyboard.press('Space')" in code
    assert "await expect(browser_opt_in).to_be_checked()" in code
    assert code.index("not_to_be_checked") < code.index("focus(page, browser_opt_in)")
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


def test_guest_opt_in_uses_checkbox_key_without_submitting_the_plan() -> None:
    module = ast.parse((ROOT / "scripts/isolation/operator_ui_acceptance.py").read_text())
    branch = next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "setup.get('journey') == 'controlled_browser'"
    )
    start = next(
        index
        for index, node in enumerate(branch.body)
        if ast.unparse(node) == "await expect(browser_opt_in).not_to_be_checked()"
    )
    end = next(
        index
        for index, node in enumerate(branch.body)
        if ast.unparse(node) == "await expect(browser_opt_in).to_be_checked()"
    )
    state = {"checked": False, "focused": False, "submissions": 0}
    keys: list[str] = []
    target = object()

    class Keyboard:
        async def press(self, key: str) -> None:
            assert state["focused"]
            keys.append(key)
            if key == "Space":
                state["checked"] = not state["checked"]
            elif key == "Enter":
                state["submissions"] += 1

    class Expect:
        def __init__(self, value: object) -> None:
            assert value is target

        async def not_to_be_checked(self) -> None:
            assert not state["checked"]

        async def to_be_checked(self) -> None:
            assert state["checked"]

    page = SimpleNamespace(keyboard=Keyboard())

    async def focus(value: object, control: object) -> None:
        assert value is page and control is target
        state["focused"] = True

    # Preserve the real generic activation behavior so the old checkbox call
    # reproduces its unintended form submission and fails the checked assertion.
    activate = next(
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "activate"
    )
    wrapper = ast.parse("async def exercise():\n    pass\n")
    function = wrapper.body[0]
    assert isinstance(function, ast.AsyncFunctionDef)
    function.body = branch.body[start : end + 1]
    namespace: dict[str, Any] = {
        "page": page,
        "browser_opt_in": target,
        "expect": Expect,
        "focus": focus,
        "Page": object,
        "Locator": object,
    }
    exec(compile(ast.Module(body=[activate], type_ignores=[]), "<activation>", "exec"), namespace)
    exec(compile(ast.fix_missing_locations(wrapper), "<checkbox-input>", "exec"), namespace)
    asyncio.run(namespace["exercise"]())
    assert keys == ["Space"] and state["checked"] and state["submissions"] == 0


def test_tooltip_review_navigation_matches_observed_association_and_ui_filter() -> None:
    from emailmonitor.associations.mapping import map_observation
    from emailmonitor.associations.models import Review
    from emailmonitor.associations.review import apply_review
    from test_associations import ORG, SETTINGS
    from test_tooltip_execution import browser_observation

    observation = browser_observation()
    bundle = map_observation(SETTINGS, ORG, observation)
    assert observation.route == "browser_dom" and observation.status == "observed"
    assert len(bundle.associations) == 1
    association = bundle.associations[0]
    assert association.state == "accepted"
    assert association.reason == "explicit_observed_correspondence"

    module = ast.parse((ROOT / "scripts/isolation/operator_ui_acceptance.py").read_text())
    branch = next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "setup.get('journey') == 'controlled_browser'"
    )
    checkpoint = next(
        index
        for index, node in enumerate(branch.body)
        if ast.unparse(node) == "checkpoint('evidence_review')"
    )
    navigation = branch.body[checkpoint + 1]
    selector = next(
        node
        for node in ast.walk(navigation)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get_by_role"
    )
    screen = next(
        ast.literal_eval(value.value) for value in selector.keywords if value.arg == "name"
    )
    app = (ROOT / "apps/web/src/App.tsx").read_text()
    assert "filters[props.screen === 'Review queue' ? 'review' : 'contacts']" in app
    defaults = dict(re.findall(r"(contacts|review): \{ query: '', state: '([^']+)'", app))
    state = defaults["review" if screen == "Review queue" else "contacts"]
    assert sum(row.state == state for row in bundle.associations) == 1
    assert screen == "Contacts" and state == "accepted"

    # Opening an accepted contact must still perform the genuine evidence-backed
    # human review, rather than treating automatic acceptance as the review receipt.
    code = ast.unparse(branch)
    assert "name='Evidence and review'" in code and "name='Save review'" in code
    reason = "Inspected controlled tooltip citation through keyboard UI"
    assert reason in code
    reviewed = apply_review(
        SETTINGS,
        bundle,
        Review(
            association_id=association.id,
            expected_revision=association.revision,
            action="accept",
            author_id=association.author_id,
            evidence_ids=association.evidence_ids,
            reason=reason,
        ),
    )
    assert reviewed.associations[0].reason == "reviewed_evidence"
    assert reviewed.associations[0].revision == association.revision + 1
