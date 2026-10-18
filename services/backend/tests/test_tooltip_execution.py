"""Trusted composition routing and fail-closed sequence; fake browser is test-only."""

from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from emailmonitor.extraction.fixture import BROWSER_ACQUISITION_DIGEST, DIGESTS
from emailmonitor.extraction.html import ArticleObservation, parse_article
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.progress.binding import CURRENT, Lease
from emailmonitor.progress.execution import ExecutionDispatcher
from emailmonitor.progress.service import Progress, Work
from emailmonitor.progress.tooltip import TOOLTIP_URL, TooltipDispatch, TooltipJourney
from test_html_extraction import SETTINGS, parse, payload


def browser_observation() -> ArticleObservation:
    # This authored synthetic DOM is deliberately confined to unit/SQL tests.
    revealed = payload("tooltip.html").replace(
        b"</div>", b'<span id="contact-tooltip" role="tooltip">elena.park@example.org</span></div>'
    )
    return parse_article(
        SETTINGS,
        TOOLTIP_URL,
        revealed,
        browser_dom=True,
        acquisition_digest=BROWSER_ACQUISITION_DIGEST,
    )


def claimed() -> Work:
    return Work(Lease(uuid4(), uuid4(), uuid4(), uuid4(), 1, 1), "article", TOOLTIP_URL, 999)


@pytest.mark.parametrize(
    "url,kind",
    [
        (TOOLTIP_URL, "discover"),
        (TOOLTIP_URL + "?x=1", "article"),
        (TOOLTIP_URL + "/", "article"),
        ("https://synthetic.publisher.example/article-a.html", "article"),
    ],
)
def test_only_exact_tooltip_article_routes(url: str, kind: str) -> None:
    progress = cast(Progress, SimpleNamespace(process_fixture=lambda *args: "default"))
    work = cast(Work, SimpleNamespace(url=url, kind=kind))
    assert ExecutionDispatcher(progress, tooltip=cast(Any, object())).process(work) == "default"


def test_no_composition_keeps_default() -> None:
    progress = cast(Progress, SimpleNamespace(process_fixture=lambda *args: "requires_browser"))
    assert ExecutionDispatcher(progress).process(claimed()) == "requires_browser"


@pytest.mark.parametrize("failure", [None, "prepare", "dispatch", "invalid", "commit", "callback"])
@pytest.mark.parametrize("replay", [False, True])
def test_bound_sequence_current_revision_and_no_fallback(
    failure: str | None, replay: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = claimed()
    calls: list[str] = []
    error = RuntimeError("refused")
    observed = browser_observation()
    row = {"article_url": TOOLTIP_URL, "observation": observed.model_dump(), "revision": 7}

    def hit(name: str) -> None:
        assert CURRENT.get() == work.lease
        calls.append(name)
        if failure == name:
            raise error

    def prepare(*args: object, browser: bool = False) -> dict[str, object]:
        hit("prepare" if browser else "static_prepare")
        return {"revision": 4}

    def fixture(*args: object) -> dict[str, object]:
        hit("fixture")
        assert args[-1] == 4
        return {"observation": parse("tooltip.html").model_dump(), "revision": 1}

    def commit(*args: object, **kwargs: object) -> dict[str, object]:
        hit("commit")
        assert kwargs == {"expected_revision": 4, "source_digest": DIGESTS["tooltip.html"]}
        return row

    def derive(*args: object) -> Any:
        hit("derive")
        assert args[-1] == 7
        return uuid4()

    def finish(*args: object) -> str:
        hit("finish")
        return "needs_review"

    class Dispatch:
        def acquire(
            self, progress: Progress, actual: Work, *, context: dict[str, object]
        ) -> ArticleObservation:
            assert actual is work and context == {"revision": 4}
            hit("dispatch")
            return parse("tooltip.html") if failure == "invalid" else observed

    progress = cast(
        Progress,
        SimpleNamespace(
            extraction=SimpleNamespace(
                prepare=prepare,
                read=lambda *args: [row] if replay else [],
                fixture=fixture,
                commit=commit,
            ),
            associations=SimpleNamespace(derive=derive),
            finish=finish,
        ),
    )
    monkeypatch.setattr(TooltipJourney, "_allow_browser", lambda *args: True)
    dispatch: TooltipDispatch = Dispatch()
    executor = ExecutionDispatcher(progress, tooltip=dispatch)

    def callback() -> None:
        hit("callback")

    should_fail = failure in {"prepare", "callback"} or (
        not replay and failure in {"dispatch", "invalid", "commit"}
    )
    if should_fail:
        with pytest.raises(FetchDenied if failure == "invalid" else RuntimeError):
            executor.process(work, after_observation=callback)
        assert "derive" not in calls and "finish" not in calls
    else:
        assert executor.process(work, after_observation=callback) == "needs_review"
        assert calls[-3:] == ["callback", "derive", "finish"]
    assert ("dispatch" in calls) is (not replay and failure != "prepare")
    assert CURRENT.get() is None


def test_optout_never_prepares_browser_or_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    work = claimed()
    observation = parse("tooltip.html")
    calls: list[str] = []

    def prepare(*args: object, browser: bool = False) -> dict[str, object]:
        assert not browser
        return {"revision": 4}

    def derive(*args: object) -> object:
        assert args[-1] == 1
        calls.append("derive")
        return uuid4()

    progress = cast(
        Progress,
        SimpleNamespace(
            extraction=SimpleNamespace(
                prepare=prepare,
                read=lambda *args: [
                    {
                        "article_url": TOOLTIP_URL,
                        "revision": 1,
                        "observation": observation.model_dump(),
                    }
                ],
            ),
            associations=SimpleNamespace(derive=derive),
            finish=lambda *args: "unsupported",
        ),
    )
    monkeypatch.setattr(TooltipJourney, "_allow_browser", lambda *args: False)
    assert ExecutionDispatcher(progress, tooltip=cast(Any, object())).process(work) == "unsupported"
    assert calls == ["derive"]
