"""Pure candidate-presence semantics; this grants no retained-data visibility.

The SQL retained selector independently enforces current source binding and supports
only its existing HTML/browser/XML persistence. PDF semantics here are conceptual,
using the already supported offline parser; there is no durable PDF read route.
"""

from typing import Literal

from emailmonitor.extraction.html import ArticleObservation
from emailmonitor.extraction.pdf import PdfObservation
from emailmonitor.extraction.xml_retained import RetainedXml

Presence = Literal["observed_candidate", "completed_without_candidate", "unresolved"]


def observation_presence(value: ArticleObservation | RetainedXml | PdfObservation) -> Presence:
    # Revalidate frozen/constructed/mutated objects before relying on their facts.
    observation = type(value).model_validate_json(value.model_dump_json())
    if observation.candidates:
        return "observed_candidate"
    if observation.status == "no_contact":
        if isinstance(observation, PdfObservation) and (
            not observation.complete_scan or observation.reason != "complete"
        ):
            return "unresolved"
        return "completed_without_candidate"
    return "unresolved"
