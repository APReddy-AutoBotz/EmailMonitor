"""Exact owned pg8000 error translation does not hide unexpected SQL failures."""

import pytest
from emailmonitor.organizations.database import AuthorizationDenied, RevisionConflict
from emailmonitor.progress.service import translate
from sqlalchemy.exc import DBAPIError


@pytest.mark.parametrize(
    "code,reason,expected",
    [
        ("EM010", "EXECUTION_SCOPE_DENIED", AuthorizationDenied),
        ("EM010", "EXECUTION_WORK_FENCE", AuthorizationDenied),
        ("EM010", "EXECUTION_RETRY_DENIED", AuthorizationDenied),
        ("EM409", "EXECUTION_REVISION", RevisionConflict),
        ("EM409", "EXECUTION_CONTROL_STATE", RevisionConflict),
    ],
)
def test_owned_code_and_reason(code: str, reason: str, expected: type[Exception]) -> None:
    error = DBAPIError("SELECT owned_fence", {}, Exception({"C": code, "M": reason}), False)
    with pytest.raises(expected):
        translate(error)


@pytest.mark.parametrize(
    "code,reason",
    [("EM010", "unknown"), ("23503", "EXECUTION_WORK_FENCE"), ("EM409", "unexpected")],
)
def test_arbitrary_failure_remains_the_actual_error(code: str, reason: str) -> None:
    error = DBAPIError("SELECT broken", {}, Exception({"C": code, "M": reason}), False)
    with pytest.raises(DBAPIError) as caught:
        translate(error)
    assert caught.value is error
