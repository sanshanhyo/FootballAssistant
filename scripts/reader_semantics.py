#!/usr/bin/env python3
"""Compare private copied packet manifests offline; emit candidate evidence only."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a", type=Path, required=True, help="Baseline copied packet manifest")
    parser.add_argument("--b", type=Path, required=True, help="Changed-state copied packet manifest")
    parser.add_argument("--return-a", type=Path, help="Optional return-to-baseline copied packet manifest")
    parser.add_argument("--registry-sidecar", type=Path, help="Optional same-session property registry JSON")
    parser.add_argument("--max-changes", type=int, default=128, help="Output candidate budget (1..512)")
    parser.add_argument("--output", type=Path, help="New report file, never overwrite; default stdout")
    args = parser.parse_args()
    try:
        root = Path(__file__).resolve().parents[1]
        source = root / "modules/data-core/src/football_assistant_data/semantic_evidence.py"
        spec = importlib.util.spec_from_file_location("reader_semantic_evidence", source)
        if spec is None or spec.loader is None:
            raise ValueError("workbench_unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.compare_manifests(args.a, args.b, args.return_a, args.registry_sidecar,
                                          max_changes=args.max_changes)
        encoded = json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False, indent=2) + "\n"
        if len(encoded.encode("ascii")) > module.MAX_OUTPUT_BYTES:
            raise ValueError("report_byte_budget")
        if args.output is None:
            print(encoded, end="")
        else:
            # Exclusive creation also refuses an existing symlink. No directory creation.
            with args.output.open("x", encoding="ascii") as stream:
                stream.write(encoded)
        return 0 if result["status"] == "candidate_evidence_only" else 2
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError, OverflowError):
        # Never echo input values, private filenames or absolute paths in diagnostics.
        print('{"status":"refused","reason":"invalid_or_unavailable_input_or_output"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
