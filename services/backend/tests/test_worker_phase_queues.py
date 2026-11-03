"""Pure owned namespace grammar; separate consumers require actual RabbitMQ CI."""

import pytest
from emailmonitor.jobs.queues import owned_queues, phase_queue


def test_exact_owned_phase_queues_preserve_legacy_namespace() -> None:
    assert owned_queues("em-fixture-authored") == (
        "em-fixture-authored",
        "em-fixture-authored-fixture-io",
        "em-fixture-authored-parse",
        "em-fixture-authored-export",
    )
    assert len(set(owned_queues("em-fixture-authored"))) == 4


@pytest.mark.parametrize(
    "namespace",
    ["shared", "em-fixture-", "em-fixture-" + "x" * 61, "em-fixture-name/escape", "em-fixture-X"],
)
def test_unknown_queue_namespace_cannot_be_deleted_or_consumed(namespace: str) -> None:
    with pytest.raises(ValueError):
        owned_queues(namespace)


@pytest.mark.parametrize("phase", ["http", "browser", "arbitrary", "../export"])
def test_unimplemented_or_unknown_celery_phases_refuse(phase: str) -> None:
    with pytest.raises(ValueError):
        phase_queue("em-fixture-authored", phase)  # type: ignore[arg-type]
