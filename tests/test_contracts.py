import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "schema,example",
    [
        ("job-request", "keyword-job"),
        ("job-request", "url-job"),
        ("contact-record", "contact-record"),
        ("event", "event"),
        ("source-policy", "source-policy"),
    ],
)
def test_committed_contract_examples(schema: str, example: str) -> None:
    definition = json.loads((ROOT / "contracts" / f"{schema}.schema.json").read_text())
    Draft202012Validator.check_schema(definition)
    validator = Draft202012Validator(definition, format_checker=FormatChecker())
    validator.validate(json.loads((ROOT / "contracts/examples" / f"{example}.json").read_text()))
