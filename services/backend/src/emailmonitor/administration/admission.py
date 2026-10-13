"""Bounded source-independent fixture CPU admission, shared with durable work."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import text

from emailmonitor.administration.binding import FixtureLease, bound
from emailmonitor.administration.service import Administration
from emailmonitor.organizations.roles import Capability


class FixtureAdvice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    admitted: bool
    inherited: bool
    reference: UUID | None

    @model_validator(mode="after")
    def relationship(self) -> "FixtureAdvice":
        if self.inherited and (not self.admitted or self.reference is not None):
            raise ValueError("Inherited admission requires a live durable lease")
        if self.admitted and not self.inherited and self.reference is None:
            raise ValueError("Fresh admission requires its owned reference")
        return self


class Admission(Administration):
    @contextmanager
    def fixture(self, organization: UUID, job: UUID, url: str) -> Iterator[None]:
        nonce = uuid4()
        with self._tenant(organization, Capability.ACQUIRE_SOURCE) as connection:
            value: object = connection.execute(
                text("""SELECT emailmonitor.fixture_admission_claim(
:organization,:job,:url,:nonce,30)"""),
                {"organization": organization, "job": job, "url": url, "nonce": nonce},
            ).scalar_one()
        advice = FixtureAdvice.model_validate_json(json.dumps(value))
        if not advice.admitted:
            raise HTTPException(409, "Current fixture processing capacity or budget unavailable")

        def release(success: bool) -> None:
            if not advice.inherited and advice.reference is not None:
                with self._tenant(organization, Capability.READ_ORGANIZATION) as connection:
                    connection.execute(
                        text("""SELECT emailmonitor.fixture_admission_release(
:organization,:job,:reference,:nonce,:success)"""),
                        {
                            "organization": organization,
                            "job": job,
                            "reference": advice.reference,
                            "nonce": nonce,
                            "success": success,
                        },
                    )

        def complete() -> Iterator[None]:
            try:
                yield
            except BaseException as error:
                try:
                    release(False)
                except Exception:
                    error.add_note("Owned fixture cleanup failed; lease remains bounded")
                raise
            else:
                release(True)

        if advice.inherited:
            with contextmanager(complete)():
                yield
        else:
            assert advice.reference is not None
            with bound(FixtureLease(organization, job, url, advice.reference, nonce)):
                with contextmanager(complete)():
                    yield
