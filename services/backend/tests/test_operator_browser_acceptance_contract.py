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
        and ast.unparse(node.test)
        == "setup.get('journey') in ('controlled_browser', 'controlled_keyword_browser')"
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
        and ast.unparse(node.test)
        == "setup.get('journey') in ('controlled_browser', 'controlled_keyword_browser')"
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
        and ast.unparse(node.test)
        == "setup.get('journey') in ('controlled_browser', 'controlled_keyword_browser')"
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


@pytest.mark.parametrize("journey", ["controlled_browser", "controlled_keyword_browser"])
def test_both_browser_journeys_have_closed_bootstrap(journey: str) -> None:
    setup = {**bootstrap(), "journey": journey}
    validate_journey(setup)
    for field in ("url", "route", "profile", "allow_browser", "keyword", "addresses"):
        with pytest.raises(ValueError, match="Fixed controlled browser bootstrap"):
            validate_journey({**setup, field: "untrusted"})
    for field in set(setup) - {"journey"}:
        with pytest.raises(ValueError):
            validate_journey({key: value for key, value in setup.items() if key != field})


def test_combined_keyword_checkpoint_matches_actual_authored_pages() -> None:
    from dataclasses import asdict

    from emailmonitor.discovery.planning import plan_input
    from emailmonitor.discovery.state import advance
    from test_discovery import initial, page, request
    from test_operator_browser_acceptance import _assert_keyword_checkpoint

    state = advance(advance(initial(), page(1), 2, 500), page(2), 2, 500)
    _assert_keyword_checkpoint(asdict(plan_input(request())), state.model_dump())
    for key, wrong in (("raw_entries", 4), ("duplicates", 0), ("reported_total", 4)):
        with pytest.raises(AssertionError):
            _assert_keyword_checkpoint(
                asdict(plan_input(request())), {**state.model_dump(), key: wrong}
            )


@pytest.mark.parametrize("format", ["csv", "xlsx"])
def test_combined_export_assertion_requires_exact_four_associations(format: str) -> None:
    from uuid import uuid4

    from emailmonitor.results.models import Contact
    from emailmonitor.results.render import csv_bytes, package, xlsx_bytes
    from test_operator_browser_acceptance import _assert_exact_export
    from test_result_serialization import contact

    contacts = tuple(
        Contact.model_validate(
            {
                **contact().model_dump(),
                "association_id": uuid4(),
                "raw_address": name + "@example.org",
                "author_name": name,
            }
        )
        for name in ("alex.chen", "ravi.das", "noor.ibrahim", "elena.park")
    )
    rows = [["Association ID", "Observed address", "Association state", "Author"]]
    rows += [
        [str(c.association_id), c.raw_address, "accepted", c.raw_address.split("@")[0]]
        for c in contacts
    ]

    def render(values: list[list[str]]) -> bytes:
        return (
            package({"contacts.csv": csv_bytes(values)})
            if format == "csv"
            else xlsx_bytes([("Contacts", values)])
        )

    _assert_exact_export(render(rows), format, contacts)
    for wrong in (rows[:-1], rows + [rows[-1]], rows[:-1] + [rows[1]]):
        with pytest.raises(AssertionError):
            _assert_exact_export(render(wrong), format, contacts)


def test_combined_journey_keeps_separate_guest_and_four_pass_gate() -> None:
    module = (ROOT / "scripts/isolation/test_operator_keyword_browser_acceptance.py").read_text()
    assert 'scope="module"' in module and module.count("topology.browser()") == 1
    assert "from test_transport_acceptance import topology as topology" in module
    assert "keyword=True" in module
    gate = (ROOT / "scripts/packaging/check_xml_transport.sh").read_text()
    assert "test_operator_keyword_browser_acceptance.py" in gate
    assert "NORMAL_OPERATOR_KEYWORD_BROWSER_ISOLATED_REVIEW_EXPORT" in gate
    assert "4 passed" in gate and "41 passed" in gate
    guest = (ROOT / "scripts/isolation/operator_ui_acceptance.py").read_text()
    assert 'page.get_by_label("Keyword", exact=True), "Myocardial Infarction"' in guest
    assert '"Inspected combined keyword citation for " + address' in guest
