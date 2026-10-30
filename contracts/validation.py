"""Strict, versioned validation shared by adapters and Data Core."""
from importlib.resources import files
import json

from jsonschema import Draft202012Validator, FormatChecker


def _validator(name: str) -> Draft202012Validator:
    schema = json.loads(files("football_assistant_contracts").joinpath("schemas", name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


VALIDATORS = {
    "0.1.0": _validator("observation-envelope.v0.1.schema.json"),
    "0.2.0": _validator("observation-envelope.v0.2.schema.json"),
    "0.3.0": _validator("observation-envelope.v0.3.schema.json"),
}


def validate_observation(body: dict) -> None:
    try:
        json.dumps(body, allow_nan=False)
    except (ValueError, TypeError):
        raise ValueError("Observation must contain only finite JSON values") from None
    version = body.get("schema_version")
    if not isinstance(version, str) or version not in VALIDATORS:
        raise ValueError("Unsupported observation schema_version")
    errors = sorted(VALIDATORS[version].iter_errors(body), key=lambda e: str(e.path))
    if errors:
        # Never reflect values, paths, personal fields or full validator messages.
        raise ValueError("Observation does not match the versioned schema")

    if version == "0.3.0":
        for fact in body["payload"].get("facts", []):
            provenance = fact["provenance"]
            if provenance["source"] != body["source"]["kind"] or provenance["adapter_id"] != body["source"]["adapter_id"]:
                raise ValueError("Field provenance differs from observation source")
            if body["source"]["kind"] == "save" and provenance["snapshot_sha256"] != body["source"]["save_metadata"]["sha256"]:
                raise ValueError("Field provenance differs from snapshot digest")
            if provenance["validation_method"] == "ui_crosscheck_exact_snapshot" and provenance["snapshot_sha256"] != provenance["ui_evidence_sample_sha256"]:
                raise ValueError("Exact UI verification must identify the current snapshot digest")
