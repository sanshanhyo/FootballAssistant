#!/usr/bin/env python3
"""Build only this observer and its independent tests; never launch a game."""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sanitize", choices=("address", "thread"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    # Keep the already loaded header-only release immutable.
    build = root / "build" / "packet-v1" / (args.sanitize or "release")
    build.mkdir(parents=True, exist_ok=True)
    sources = [root / "src/observer_core.cpp", root / "src/packet_capture.cpp",
               root / "src/observer_api.cpp"]
    system = platform.system()
    if system == "Windows":
        compiler = shutil.which("cl")
        if compiler is None:
            raise SystemExit("Run from an x64 Visual Studio developer prompt (cl required).")
        if args.sanitize:
            raise SystemExit("The local sanitizer build is currently documented for clang.")
        common = [compiler, "/nologo", "/std:c++20", "/EHsc", "/W4", "/O2",
                  f"/I{root / 'include'}", f"/I{root / 'src'}"]
        subprocess.run([*common, "/LD", *map(str, sources), "/link",
                        f"/OUT:{build / 'footballassistant_native_observer.dll'}"],
                       cwd=build, check=True)
        subprocess.run([*common, *map(str, sources), str(root / "tests/observer_tests.cpp"),
                        f"/Fe:{build / 'observer_tests.exe'}"], cwd=build, check=True)
        subprocess.run([*common, *map(str, sources), str(root / "tests/packet_tests.cpp"),
                        f"/Fe:{build / 'packet_tests.exe'}"], cwd=build, check=True)
    else:
        compiler = shutil.which("clang++")
        if compiler is None:
            raise SystemExit("clang++ is required; no global tools are installed by this script.")
        common = [compiler, "-std=c++20", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
                  "-fexceptions", "-funwind-tables", "-fno-omit-frame-pointer",
                  "-fvisibility=hidden", "-pthread", f"-I{root / 'include'}",
                  f"-I{root / 'src'}"]
        if args.sanitize:
            common += [f"-fsanitize={args.sanitize}"]
        extension = ".dylib" if system == "Darwin" else ".so"
        shared = "-dynamiclib" if system == "Darwin" else "-shared"
        subprocess.run([*common, shared, "-fPIC", *map(str, sources), "-o",
                        str(build / f"libfootballassistant_native_observer{extension}")],
                       cwd=root, check=True)
        subprocess.run([*common, *map(str, sources), str(root / "tests/observer_tests.cpp"),
                        "-o", str(build / "observer_tests")], cwd=root, check=True)
        subprocess.run([*common, *map(str, sources), str(root / "tests/packet_tests.cpp"),
                        "-o", str(build / "packet_tests")], cwd=root, check=True)
        subprocess.run([*common, "-DFA_OBSERVER_TESTING=1", *map(str, sources),
                        str(root / "tests/dobby_toy_test.cpp"),
                        *([str(root / "tests/dispatch_fixture_arm64.S")]
                          if system == "Darwin" and platform.machine() == "arm64" else []), "-o",
                        str(build / "observer_dobby_toy_test")], cwd=root, check=True)
        if system == "Darwin" and not args.sanitize:
            subprocess.run(["codesign", "--force", "--sign", "-", "--entitlements",
                            str(root / "tests/test-entitlements.plist"),
                            str(build / "observer_dobby_toy_test")], check=True)
    print(build)


if __name__ == "__main__":
    main()
