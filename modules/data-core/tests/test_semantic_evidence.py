"""Synthetic TEST bytes only: no capture, game process, or actual entity evidence.

The legacy decoder requires synthetic=False in its input schema. These deliberately
fabricated manifests exercise that gate, not attest origin. Matching hashes prove
only that the local test bytes match their test manifest.
"""
import hashlib
import json
from pathlib import Path
import struct
import uuid

import pytest

from football_assistant_data import semantic_evidence as evidence


# Pinned grammar identities copied from the existing decoder, NOT capture proof.
METADATA_SHA = "ff4780c66f37e088f363d0c4365110dd0d7968204cb36283a6262055badab21d"
ASSEMBLY_SHA = "266d02a57471b44f381b7b647828c58fd394e8222c3083613324a93a9db09dd7"
PLUGIN_SHA = "2e915b0f264920ae1205b111f45d50e354ac0e7d0b6e136b99189c24b265f431"
SESSION = "afe5c5bc-0000-4000-8000-000000000001"
OTHER_SESSION = "afe5c5bc-0000-4000-8000-000000000002"
SECRET = "TEST_PRIVATE_SECRET_DO_NOT_EMIT"


def typed(tag, raw=b""):
    return bytes((0, tag)) + raw


def integer(number):
    return typed(1, struct.pack("<i", number))


def string(value):
    raw = value.encode("utf-8")
    return typed(14, struct.pack("<I", len(raw)) + raw)


def payload(*nodes):
    return struct.pack("<I", len(nodes)) + b"".join(nodes)


def packet(tmp_path, label, keys=(42,), nodes=None, **overrides):
    """Build TEST-only files. A declared synthetic=False is intentionally untrusted."""
    directory = tmp_path / label
    directory.mkdir()
    raw_keys = b"".join(struct.pack("<Q", key) for key in keys)
    raw_payload = payload(*(nodes if nodes is not None else [integer(1)]))
    (directory / "TEST-keys.bin").write_bytes(raw_keys)
    (directory / "TEST-payload.bin").write_bytes(raw_payload)
    manifest = {
        "schema_version": 1, "synthetic": False, "complete_copy": True,
        "test_fixture_notice": "SYNTHETIC TEST construction; NOT an actual capture",
        "packet_id": str(uuid.uuid4()), "session_id": SESSION,
        "source": {"session_id": SESSION, "synthetic": False,
                   "game_build": "SYNTHETIC-TEST-NOT-A-CAPTURE",
                   "metadata_sha256": METADATA_SHA, "game_assembly_sha256": ASSEMBLY_SHA},
        "game_plugin_sha256": PLUGIN_SHA,
        "managed_build_sha256": "a" * 64, "observer_sha256": "b" * 64,
        "keys_count": str(len(keys)), "payload_bytes": str(len(raw_payload)),
        "keys_file": "TEST-keys.bin", "payload_file": "TEST-payload.bin",
        "keys_sha256": hashlib.sha256(raw_keys).hexdigest(),
        "payload_sha256": hashlib.sha256(raw_payload).hexdigest(),
    }
    manifest.update(overrides)
    path = directory / "TEST-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def edit_manifest(path, mutate):
    manifest = json.loads(path.read_text(encoding="utf-8"))
    mutate(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def registry(tmp_path, **source_overrides):
    source = {"session_id": SESSION, "synthetic": False,
              "game_build": "SYNTHETIC-TEST-NOT-A-CAPTURE",
              "metadata_sha256": METADATA_SHA, "game_assembly_sha256": ASSEMBLY_SHA}
    source.update(source_overrides)
    frame = {"source": source, "registry_enumerations": [{
        "registry_id": "PropertyIdentifierSet", "enumeration_id": "TEST-epoch",
        "dictionary_version": 1, "expected_count": 1, "complete": True,
        "status": "complete", "entries": [{"id": 80, "name": SECRET}],
    }]}
    path = tmp_path / "TEST-registry.json"
    path.write_text(json.dumps(frame), encoding="utf-8")
    return path


def compare(tmp_path, a_nodes=None, b_nodes=None, **kwargs):
    a = packet(tmp_path, "a", nodes=a_nodes)
    b = packet(tmp_path, "b", nodes=b_nodes)
    return evidence.compare_manifests(a, b, **kwargs)


def test_real_decoder_hash_verification_yields_candidates_not_game_truth(tmp_path):
    result = compare(tmp_path, [integer(1)], [integer(2)])
    assert result["status"] == "candidate_evidence_only"
    assert result["candidate_change_count"] == 1
    assert result["candidate_changes"][0]["classification"] == "candidate_not_confirmed"
    assert result["business_semantics_complete"] is False
    assert result["entity_identity_known"] is False
    assert result["channel_lifetime_mapping_known"] is False
    assert result["values_disclosed"] is False
    for captured in result["captures"].values():
        assert captured["copy_integrity_verified"] is True
        assert captured["live_origin_independently_verified"] is False


@pytest.mark.parametrize("file_name", ["TEST-payload.bin", "TEST-keys.bin"])
def test_changed_bytes_are_rejected_even_when_decodable(tmp_path, file_name):
    a, b = packet(tmp_path, "a"), packet(tmp_path, "b")
    path = b.parent / file_name
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(data)
    with pytest.raises(ValueError):
        evidence.compare_manifests(a, b)


@pytest.mark.parametrize("field,value", [
    ("session_id", OTHER_SESSION), ("game_build", "OTHER-TEST-BUILD"),
    ("metadata_sha256", "c" * 64), ("game_assembly_sha256", "d" * 64),
])
def test_source_provenance_mismatch_rejected(tmp_path, field, value):
    a, b = packet(tmp_path, "a"), packet(tmp_path, "b")
    def mutate(manifest):
        manifest["source"][field] = value
        if field == "session_id":
            manifest[field] = value
    edit_manifest(b, mutate)
    with pytest.raises(ValueError):
        evidence.compare_manifests(a, b)


@pytest.mark.parametrize("field", ["managed_build_sha256", "observer_sha256", "game_plugin_sha256"])
def test_capture_build_mismatch_rejected(tmp_path, field):
    a = packet(tmp_path, "a")
    b = packet(tmp_path, "b", **{field: "c" * 64})
    with pytest.raises(ValueError):
        evidence.compare_manifests(a, b)


@pytest.mark.parametrize("nodes,keys", [([typed(255)], (42,)), ([integer(1)], (42, 43))])
def test_unknown_grammar_and_mismatched_counts_have_no_candidates(tmp_path, nodes, keys):
    a = packet(tmp_path, "a")
    b = packet(tmp_path, "b", nodes=nodes, keys=keys)
    result = evidence.compare_manifests(a, b)
    assert result["status"] == "not_comparable"
    assert result["candidate_changes"] == []


def test_duplicate_channel_keys_block_entire_comparison(tmp_path):
    a = packet(tmp_path, "a", keys=(42, 42), nodes=[integer(1), integer(2)])
    b = packet(tmp_path, "b", keys=(42, 43), nodes=[integer(3), integer(4)])
    result = evidence.compare_manifests(a, b)
    assert result["status"] == "not_comparable"
    assert result["reason"] == "duplicate_channel_keys"
    assert result["candidate_changes"] == []


def test_absent_channel_is_not_observed_not_null_or_removed_entity(tmp_path):
    a = packet(tmp_path, "a", keys=(42,), nodes=[typed(0)])
    b = packet(tmp_path, "b", keys=(43,), nodes=[typed(0)])
    result = evidence.compare_manifests(a, b)
    changes = {row["channel_key"]: row for row in result["candidate_changes"]}
    assert changes["42"]["b"] == {"observation": "not_observed"}
    assert changes["43"]["a"] == {"observation": "not_observed"}
    assert changes["42"]["a"]["observation"] == "observed"
    assert result["entity_identity_known"] is False


def test_return_match_is_candidate_not_causation_or_verified_order(tmp_path):
    a = packet(tmp_path, "a", nodes=[integer(1)])
    b = packet(tmp_path, "b", nodes=[integer(2)])
    returned = packet(tmp_path, "return", nodes=[integer(1)])
    result = evidence.compare_manifests(a, b, return_a=returned)
    row = result["candidate_changes"][0]
    assert row["return_matches_a"] is True
    assert row["classification"] == "candidate_not_confirmed"
    assert result["capture_order"] == "user_supplied_not_independently_verified"
    assert result["causality_established"] is False
    assert result["entity_identity_known"] is False


def test_absent_return_does_not_establish_a_return_match(tmp_path):
    a = packet(tmp_path, "a")
    b = packet(tmp_path, "b", nodes=[integer(2)])
    returned = packet(tmp_path, "return", keys=(), nodes=[])
    result = evidence.compare_manifests(a, b, return_a=returned)
    assert result["candidate_changes"][0]["return_matches_a"] is None


@pytest.mark.parametrize("overrides", [{"session_id": OTHER_SESSION}, {"synthetic": True},
                                         {"game_build": "OTHER-TEST-BUILD"}])
def test_registry_requires_matching_provenance(tmp_path, overrides):
    sidecar = registry(tmp_path, **overrides)
    with pytest.raises(ValueError):
        compare(tmp_path, registry_sidecar=sidecar)


def test_registry_digest_retained_without_private_label_or_payload_leak(tmp_path):
    sidecar = registry(tmp_path)
    dynamic = typed(10, struct.pack("<II", 1, 80) + string(SECRET))
    blob = typed(16, b"\x00\x00" + struct.pack("<I", len(SECRET)) + SECRET.encode())
    a = packet(tmp_path, "private-" + SECRET, keys=(42, 43), nodes=[dynamic, blob])
    b = packet(tmp_path, "b", keys=(42, 43), nodes=[integer(2), integer(3)])
    result = evidence.compare_manifests(a, b, registry_sidecar=sidecar)
    encoded = json.dumps(result, allow_nan=False)
    assert SECRET not in encoded
    assert str(tmp_path) not in encoded
    assert "m_buffer_base64" not in encoded
    assert "property_name" not in encoded
    assert result["captures"]["a"]["registry_sidecar_sha256"] == hashlib.sha256(sidecar.read_bytes()).hexdigest()


@pytest.mark.parametrize("suffix", [',"schema_version":1}', ',"extra":NaN}', ',"extra":Infinity}', ',"extra":1e999}'])
def test_manifest_json_is_strict(tmp_path, suffix):
    a, b = packet(tmp_path, "a"), packet(tmp_path, "b")
    b.write_text(b.read_text()[:-1] + suffix)
    with pytest.raises(ValueError):
        evidence.compare_manifests(a, b)


def test_manifest_depth_and_byte_budgets(tmp_path):
    a, b = packet(tmp_path, "a"), packet(tmp_path, "b")
    original = b.read_text()
    b.write_text(original[:-1] + ',"extra":' + '[' * 60 + '0' + ']' * 60 + '}')
    with pytest.raises(ValueError):
        evidence.compare_manifests(a, b)
    b.write_text(original[:-1] + ',"extra":"' + 'x' * 65_536 + '"}')
    with pytest.raises(ValueError):
        evidence.compare_manifests(a, b)


def test_bounded_output_counts_all_candidates_without_disclosing_values(tmp_path):
    a = packet(tmp_path, "a", keys=range(40), nodes=[integer(n) for n in range(40)])
    b = packet(tmp_path, "b", keys=range(40), nodes=[integer(n + 1) for n in range(40)])
    result = evidence.compare_manifests(a, b, max_changes=3)
    assert result["candidate_change_count"] == 40
    assert len(result["candidate_changes"]) == 3
    assert result["truncated"] is True
    assert len(json.dumps(result).encode()) <= result["limits"]["max_output_bytes"]


@pytest.mark.parametrize("budget", [0, -1, 513, True, 1.5, "3"])
def test_invalid_output_budget_rejected(tmp_path, budget):
    with pytest.raises(ValueError):
        compare(tmp_path, max_changes=budget)


def test_duplicate_packet_identity_and_synthetic_manifest_rejected(tmp_path):
    a, b = packet(tmp_path, "a"), packet(tmp_path, "b")
    packet_id = json.loads(a.read_text())["packet_id"]
    edit_manifest(b, lambda m: m.update(packet_id=packet_id))
    with pytest.raises(ValueError):
        evidence.compare_manifests(a, b)
    edit_manifest(b, lambda m: m.update(packet_id=str(uuid.uuid4()), synthetic=True))
    with pytest.raises(ValueError):
        evidence.compare_manifests(a, b)


def test_registry_false_completion_and_duplicate_ids_rejected(tmp_path):
    sidecar = registry(tmp_path)
    frame = json.loads(sidecar.read_text())
    frame["registry_enumerations"][0]["expected_count"] = 2
    sidecar.write_text(json.dumps(frame))
    with pytest.raises(ValueError):
        compare(tmp_path, registry_sidecar=sidecar)
    frame["registry_enumerations"][0]["entries"] *= 2
    sidecar.write_text(json.dumps(frame))
    # Reuse manifests produced above rather than constructing directories twice.
    with pytest.raises(ValueError):
        evidence.compare_manifests(tmp_path / "a/TEST-manifest.json", tmp_path / "b/TEST-manifest.json", registry_sidecar=sidecar)


def test_nested_duplicate_property_ids_preserve_occurrence_paths(tmp_path):
    def dynamic(first, second):
        return typed(10, struct.pack("<I", 2) + struct.pack("<I", 80) + integer(first)
                     + struct.pack("<I", 80) + integer(second))
    result = compare(tmp_path, [dynamic(1, 2)], [dynamic(1, 3)])
    paths = [row["path"] for row in result["candidate_changes"]]
    assert ["property:80:1"] in paths
    assert ["property:80:0"] not in paths


def test_unchanged_values_do_not_invent_candidates(tmp_path):
    result = compare(tmp_path)
    assert result["candidate_change_count"] == 0
    assert result["candidate_changes"] == []


def test_return_capture_must_match_original_provenance(tmp_path):
    a, b, returned = packet(tmp_path, "a"), packet(tmp_path, "b"), packet(tmp_path, "return")
    edit_manifest(returned, lambda m: m["source"].update(game_build="OTHER-TEST-BUILD"))
    with pytest.raises(ValueError):
        evidence.compare_manifests(a, b, return_a=returned)


@pytest.mark.parametrize("field,value", [("complete", 1), ("expected_count", True), ("dictionary_version", False)])
def test_registry_bool_integer_coercion_rejected(tmp_path, field, value):
    sidecar = registry(tmp_path)
    frame = json.loads(sidecar.read_text())
    frame["registry_enumerations"][0][field] = value
    sidecar.write_text(json.dumps(frame))
    with pytest.raises(ValueError):
        compare(tmp_path, registry_sidecar=sidecar)


def test_cli_redacts_errors_and_never_overwrites_output(tmp_path):
    # Only invoke checkout-owned offline Python; no game or network interaction.
    import subprocess
    import sys
    script = Path(__file__).resolve().parents[3] / "scripts/reader_semantics.py"
    a, b = packet(tmp_path, "a"), packet(tmp_path, "b", nodes=[integer(2)])
    command = [sys.executable, str(script), "--a", str(a), "--b", str(b)]
    output = tmp_path / "report.json"
    good = subprocess.run(command + ["--output", str(output)], capture_output=True, text=True, timeout=10)
    assert good.returncode == 0, good.stderr
    report = json.loads(output.read_text())
    assert report["status"] == "candidate_evidence_only"
    original = output.read_bytes()
    refused = subprocess.run(command + ["--output", str(output)], capture_output=True, text=True, timeout=10)
    assert refused.returncode == 1
    assert output.read_bytes() == original
    missing = tmp_path / SECRET / "manifest.json"
    refused = subprocess.run([sys.executable, str(script), "--a", str(missing), "--b", str(b)],
                             capture_output=True, text=True, timeout=10)
    assert refused.returncode == 1
    assert SECRET not in refused.stdout + refused.stderr
    assert str(tmp_path) not in refused.stdout + refused.stderr
    assert json.loads(refused.stderr)["status"] == "refused"


def test_incomplete_registry_unknown_count_is_not_fabricated_completion(tmp_path):
    sidecar = registry(tmp_path)
    frame = json.loads(sidecar.read_text())
    frame["registry_enumerations"][0].update(complete=False, status="partial", expected_count=None,
                                              dictionary_version=None)
    sidecar.write_text(json.dumps(frame))
    result = compare(tmp_path, registry_sidecar=sidecar)
    assert result["status"] == "candidate_evidence_only"
    assert result["business_semantics_complete"] is False
