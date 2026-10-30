#!/usr/bin/env python3
"""Standalone own-process library/toy tests only; never load or launch a game."""
import ctypes
import pathlib
import platform
import shutil
import subprocess
root = pathlib.Path(__file__).resolve().parents[1]
build = root / "build" / "windows-reader-v1"
build.mkdir(parents=True, exist_ok=True)
src, test = root / "src/reader.cpp", root / "tests/reader_tests.cpp"
if platform.system() == "Windows":
    compiler = shutil.which("cl")
    if not compiler:
        raise SystemExit("Use an x64 Visual Studio developer prompt; no tools are installed.")
    flags = [compiler, "/nologo", "/std:c++20", "/EHsc", "/W4", "/O2", "/I" + str(root / "include")]
    subprocess.run([*flags, "/LD", str(src), "/link", "/OUT:" + str(build / "fa_windows_reader.dll")], cwd=build, check=True)
    executable = build / "reader_tests.exe"
    subprocess.run([*flags, str(src), str(test), "/Fe:" + str(executable)], cwd=build, check=True)
else:
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        raise SystemExit("C++20 compiler required; no tools are installed.")
    flags = [compiler, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-fvisibility=hidden", "-I" + str(root / "include")]
    executable = build / "reader_tests"
    subprocess.run([*flags, str(src), str(test), "-o", str(executable)], check=True)
    suffix, mode = (".dylib", "-dynamiclib") if platform.system() == "Darwin" else (".so", "-shared")
    subprocess.run([*flags, mode, "-fPIC", str(src), "-o", str(build / ("libfa_windows_reader" + suffix))], check=True)
subprocess.run([str(executable)], check=True)
if platform.system() == "Windows":
    # Load only this freshly built test artifact, then inspect its own export.
    library = ctypes.CDLL(str(build / "fa_windows_reader.dll"))
    inspect = library.fa_win_inspect_module_v1
    inspect.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
    inspect.restype = ctypes.c_int32
    report = ctypes.create_string_buffer(1080)
    if inspect(ctypes.cast(inspect, ctypes.c_void_p), report, len(report)) != 0:
        raise SystemExit("Built DLL self-inspection failed")
    if int.from_bytes(report.raw[12:16], "little") != 0x8664:
        raise SystemExit("Built DLL is not AMD64")
    print("Built DLL ctypes ABI/self-inspection passed")
print(build)
