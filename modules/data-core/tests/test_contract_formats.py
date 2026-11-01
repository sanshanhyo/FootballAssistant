"""Prevent optional format dependencies from silently weakening observation checks."""
import json
from pathlib import Path

import pytest
from jsonschema import FormatChecker
from jsonschema.exceptions import FormatError
from football_assistant_contracts.validation import VALIDATORS, _schema_formats, _validator, validate_observation


@pytest.mark.parametrize("version", VALIDATORS)
def test_every_schema_format_rejects_invalid_values(version):
    validator = VALIDATORS[version]
    samples = {
        "uuid": ("9769268e-6ed3-4f9c-a7e2-6abc050e5551", "not-a-uuid"),
        "date-time": ("2026-10-30T00:00:00Z", "2026-02-30T00:00:00Z"),
    }
    formats = set(_schema_formats(validator.schema))
    # Adding a schema format requires adding positive and negative coverage here.
    assert formats <= samples.keys()
    for format_name in formats:
        good, bad = samples[format_name]
        validator.format_checker.check(good, format_name)
        with pytest.raises(FormatError):
            validator.format_checker.check(bad, format_name)


@pytest.mark.parametrize("field,bad", [
    ("event_id", "not-a-uuid"),
    ("captured_at", "2026-02-30T00:00:00Z"),
    ("captured_at", "2026-10-30T00:00:00"),
    ("observed_at", "not-a-date"),
])
def test_observation_rejects_bad_formats(field, bad):
    root = Path(__file__).resolve().parents[3]
    body = json.loads((root / "contracts/examples/runtime-observation.json").read_text(encoding="utf-8"))
    validate_observation(body)
    body[field] = bad
    with pytest.raises(ValueError, match="versioned schema"):
        validate_observation(body)


@pytest.mark.parametrize("format_name", ["uuid", "date-time"])
def test_missing_checker_fails_at_validator_construction(monkeypatch, format_name):
    monkeypatch.delitem(FormatChecker.checkers, format_name)
    with pytest.raises(RuntimeError, match="Missing schema format checkers"):
        _validator("observation-envelope.v0.1.schema.json")
