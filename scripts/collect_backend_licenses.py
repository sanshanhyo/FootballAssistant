"""Collect notices for distributions present in PyInstaller's actual analysis.

No network requests. Missing distribution/runtime licenses fail the build. This
inventory is not a legal compatibility review or a native-library source offer.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import shutil
import sys
import sysconfig

ROOT = Path(__file__).resolve().parents[1]
KINDS = {"PYMODULE", "PYSOURCE", "EXTENSION", "DATA", "BINARY"}


def entries(value):
    if isinstance(value, (list, tuple)):
        if len(value) == 3 and all(isinstance(x, str) for x in value) and value[2] in KINDS:
            yield value
        else:
            for child in value:
                yield from entries(child)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(destination):
    data = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    if not data.get("components"):
        raise ValueError("License manifest has no components")
    if "coverage" in data:
        record = data["coverage"]
        path = (destination / record["path"]).resolve()
        if not path.is_relative_to(destination.resolve()) or not path.is_file() or digest(path) != record["sha256"]:
            raise ValueError("Missing/changed coverage inventory")
        if json.loads(path.read_text(encoding="utf-8")).get("unresolved"):
            raise ValueError("Unresolved bundled Python/data provenance")
    for component in data["components"]:
        if not component["files"]:
            raise ValueError(f"No notice files: {component['name']}")
        for record in component["files"]:
            path = (destination / record["path"]).resolve()
            if not path.is_relative_to(destination.resolve()) or not path.is_file() or digest(path) != record["sha256"]:
                raise ValueError(f"Missing/changed license: {record['path']}")
    return data


def cpython_framework_metadata(name, path, kind):
    """Recognize only the running interpreter's macOS framework Info.plist.

    PyInstaller collects this outside stdlib alongside the Python framework
    binary. Wheel metadata cannot own it. Never accept a basename/path suffix
    alone: bind both destination and resolved source to this interpreter.
    """
    if kind != "DATA" or sys.platform != "darwin" or sysconfig.get_config_var("PYTHONFRAMEWORK") != "Python":
        return False
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    expected_name = f"Python.framework/Versions/{version}/Resources/Info.plist"
    if name != expected_name:
        return False
    candidates = [Path(sys.base_prefix) / "Resources/Info.plist"]
    framework_prefix = sysconfig.get_config_var("PYTHONFRAMEWORKPREFIX")
    if framework_prefix:
        candidates.append(Path(framework_prefix) / expected_name)
    return path.is_file() and any(path == candidate.resolve() for candidate in candidates)


def openssl_macos_notice(toc):
    """Bind reviewed notices to actual macOS OpenSSL input bytes, without loading them.

    The input hash is provenance before app code signing, not a hash assertion
    about a subsequently signed dylib. Other native libraries remain open.
    """
    if sys.platform != "darwin":
        return None
    libraries = {}
    for name, source, kind in toc:
        if kind == "BINARY" and Path(source).name in {"libcrypto.3.dylib", "libssl.3.dylib"}:
            path = Path(source).resolve()
            previous = libraries.get(path.name)
            if previous and previous != path:
                raise ValueError("Multiple OpenSSL runtime sources require review")
            libraries[path.name] = path
    if not libraries:
        return None
    if set(libraries) != {"libcrypto.3.dylib", "libssl.3.dylib"}:
        raise ValueError("Incomplete OpenSSL runtime pair requires review")
    if len({p.parent for p in libraries.values()}) != 1:
        raise ValueError("OpenSSL runtime libraries have different source directories")
    crypto = libraries["libcrypto.3.dylib"].read_bytes()
    versions = set(re.findall(rb"OpenSSL ([0-9]+\.[0-9]+\.[0-9]+[a-z]?) [^\x00]{1,40}", crypto))
    if versions != {b"3.0.16"}:
        raise ValueError(f"Unreviewed OpenSSL version markers: {versions!r}")
    folder = ROOT / "packaging/licenses/openssl-3.0.16"
    provenance = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    if provenance["version"] != "3.0.16" or provenance["license"] != "Apache-2.0":
        raise ValueError("Unexpected OpenSSL notice provenance")
    notices = []
    for record in provenance["files"]:
        notice = (folder / record["file"]).resolve()
        if not notice.is_relative_to(folder.resolve()) or not notice.is_file() or digest(notice) != record["sha256"]:
            raise ValueError("OpenSSL upstream notice hash mismatch")
        notices.append(notice)
    if not any(p.name == "LICENSE.txt" for p in notices):
        raise ValueError("OpenSSL license text missing")
    notices.extend([folder / "provenance.json", folder / "REVIEW.md"])
    evidence = [{"name": name, "sha256": digest(path), "bytes": path.stat().st_size,
                 "hash_stage": "build-input-before-app-signing"} for name, path in sorted(libraries.items())]
    return notices, evidence


def collect(analysis, destination):
    toc = list(entries(ast.literal_eval(analysis.read_text(encoding="utf-8"))))
    sources = {str(Path(source).resolve()) for _, source, _ in toc}
    components = []
    claimed = set()
    coverage = []
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "manifest.json").unlink(missing_ok=True)  # Failed rebuild cannot retain a passing receipt.
    # A contaminated build environment can restore jsonschema's GPL extra even
    # after the lock changes. Fail on the actual input, including missing RECORD.
    if any(name == "rfc3987" or Path(source).name == "rfc3987.py"
           for name, source, _ in toc):
        raise ValueError("rfc3987 is not approved for this build; use a clean format-nongpl environment")

    def add(name, version, inputs, **extra):
        folder = re.sub(r"[^a-zA-Z0-9_.-]", "_", name + "-" + version)
        records = []
        for index, source in enumerate(inputs):
            if not source.is_file() or source.stat().st_size == 0:
                raise ValueError(f"Missing/empty license input: {source}")
            target = destination / folder / f"{index:03d}-{source.name}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            records.append({"path": target.relative_to(destination).as_posix(), "sha256": digest(target)})
        if not records:
            raise ValueError(f"No license supplied by {name} {version}; audit before shipping")
        components.append({"name": name, "version": version, "files": records, **extra})

    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata.get("Name", "")):
        files = list(dist.files or [])
        used = [f for f in files if str(Path(dist.locate_file(f)).resolve()) in sources]
        if not used:
            continue
        claimed.update(str(Path(dist.locate_file(f)).resolve()) for f in used)
        name, version = dist.metadata["Name"], dist.version
        if name == "football-assistant":
            continue  # Project license is packaged separately, not third-party.
        notices = [Path(dist.locate_file(f)) for f in files if
                   re.match(r"^(licen[cs]e|copying|notice|authors)([._-]|$)", Path(f).name, re.I)]
        # AUTHORS and NOTICE are supplementary attribution, not by themselves a
        # license grant. An SPDX expression alone also cannot replace full terms.
        license_files = [p for p in notices if re.match(r"^(licen[cs]e|copying)([._-]|$)", p.name, re.I)]
        extra = {"license_expression": dist.metadata.get("License-Expression"),
                 "bundled_files": sorted(str(f).replace('\\', '/') for f in used)}
        if re.sub(r"[-_.]+", "-", name).lower() == "rfc3987":
            raise ValueError("rfc3987 is not approved for this build; use a clean format-nongpl environment")
        if name == "logfire-api" and not license_files:
            notices = [ROOT / "packaging/licenses" / f"logfire-api-{version}-LICENSE"]
            license_files = notices
            extra["notice_source"] = f"https://github.com/pydantic/logfire/blob/v{version}/LICENSE"
        if not license_files:
            raise ValueError(f"No full license text for {name} {version}; AUTHORS/NOTICE or SPDX alone is insufficient")
        add(name, version, notices, **extra)

    stdlib_roots = {Path(sysconfig.get_path(key)).resolve() for key in ("stdlib", "platstdlib")}
    project_roots = [ROOT / path for path in ("scripts", "modules", "contracts", "build/backend-sources", "football_assistant.egg-info")]
    unknown = []
    for name, source, kind in toc:
        path = Path(source).resolve()
        if str(path) in claimed:
            category = "distribution"
        elif source == "-" and kind == "PYMODULE":
            category = "namespace-no-file"  # PyInstaller namespace package marker.
        elif any(path.is_relative_to(p.resolve()) for p in project_roots):
            category = "project"
        elif any(path.is_relative_to(p) for p in stdlib_roots) and not any(
                part in {"site-packages", "dist-packages"} for part in path.parts):
            category = "cpython-stdlib"
        elif cpython_framework_metadata(name, path, kind):
            category = "cpython-framework-metadata"
        elif kind == "DATA" and name == "base_library.zip" and path == (analysis.parent / "base_library.zip").resolve():
            category = "pyinstaller-generated-stdlib-archive"
        elif kind in {"BINARY", "EXTENSION"}:
            category = "native-release-review"
        else:
            category = "unresolved"
            unknown.append({"name": name, "source_file": path.name, "kind": kind})
        coverage.append({"name": name, "kind": kind, "category": category})
    # Keep a diagnostic even on failure. Never print Verified for unknown Python
    # modules/data merely because their wheel has missing/incomplete RECORD data.
    (destination / "coverage.json").write_text(json.dumps({"entries": coverage, "unresolved": unknown}, indent=2) + "\n", encoding="utf-8")
    if unknown:
        raise ValueError(f"Unresolved bundled Python/data provenance; audit coverage.json: {unknown}")

    add("FootballAssistant", "project", [ROOT / "LICENSE", ROOT / "LICENSE-SCOPE.md"],
        license_expression="MIT",
        scope="Own source code and documentation only; see LICENSE-SCOPE.md for exclusions")
    candidates = [Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
                  Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE"]
    runtime_license = next((p for p in candidates if p.is_file()), None)
    if runtime_license is None:
        raise ValueError("CPython LICENSE.txt missing from build runtime; provide audited runtime")
    add("CPython", sys.version.split()[0], [runtime_license])
    openssl = openssl_macos_notice(toc)
    if openssl:
        notices, evidence = openssl
        add("OpenSSL", "3.0.16", notices, license_expression="Apache-2.0",
            binary_evidence=evidence,
            scope="Upstream notices retained; binary hashes precede app signing. Native review remains open.")
    native = sorted({Path(source).name for _, source, kind in toc if kind in {"BINARY", "EXTENSION"}
                     and str(Path(source).resolve()) not in claimed})
    manifest = {"schema_version": 1, "components": components,
                "coverage": {"path": "coverage.json", "sha256": digest(destination / "coverage.json")},
                "native_runtime_files_for_release_review": native,
                "scope": "Distribution notices and CPython license; native system libraries, source delivery and compatibility require separate release review."}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    verify(destination)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        result = verify(args.destination)
    else:
        if not args.analysis:
            parser.error("--analysis is required when collecting")
        result = collect(args.analysis, args.destination)
    print(f"Verified {len(result['components'])} backend license components")
