#!/usr/bin/env python3
"""Reuse the authenticated local reader or start reader-only, then open its console.

Runs in the current terminal. Reader.command / Reader.cmd create the OS console.
Never opens the game or companion and never stops an existing listener.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

from football_assistant_data.config import ROOT, Settings
from football_assistant_data.reader_client import ReaderClient, ReaderError, default_runtime_file
from football_assistant_data.reader_cli import main as console_main
from football_assistant_data.process_utils import process_is_alive


def ensure_service(runtime_file: Path,*,start: bool):
    client = ReaderClient(runtime_file,timeout=1)
    try:
        state = client.status()
        client.snapshot(limit=1)
        return {"service":"reused","reader_api":state["reader_api"]}
    except ReaderError as error:
        if not start:raise
        if error.code not in ("runtime_unavailable","disconnected"):
            raise ReaderError("incompatible_service","Existing runtime is not a compatible authenticated reader; leaving it untouched.") from None
    settings = Settings.from_env(reader_only=True)
    if runtime_file.exists():
        try:
            pid = json.loads(runtime_file.read_text()).get("pid")
            if isinstance(pid,int) and pid>0:
                if process_is_alive(pid):
                    raise ReaderError("service_unresponsive","Existing service process is alive; leaving it untouched.")
        except (OSError,ValueError,TypeError,AttributeError):
            pass
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(("127.0.0.1",settings.port))==0:
            raise ReaderError("port_in_use","Configured port has a listener without a compatible runtime; leaving it untouched.")
    settings.data_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    log_path = settings.data_dir / "reader.log"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os,"O_NOFOLLOW",0)
    descriptor = os.open(log_path,flags,0o600)
    environment = {**os.environ,"FOOTBALL_ASSISTANT_RUNTIME_FILE":str(runtime_file)}
    # The reader ignores .env and all model configuration; token is never an argv value.
    options = {"cwd":str(ROOT),"env":environment,"stdin":subprocess.DEVNULL,
               "stdout":descriptor,"stderr":subprocess.STDOUT,"close_fds":True}
    if os.name=="nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:options["start_new_session"] = True
    try:
        child = subprocess.Popen([sys.executable,"-m","football_assistant_data.reader"],**options)
    finally:os.close(descriptor)
    deadline = time.monotonic()+20
    while time.monotonic()<deadline:
        try:
            state = client.status()
            if state.get("reader_api")==1:
                return {"service":"started","reader_api":1}
        except ReaderError:pass
        if child.poll() is not None:
            raise ReaderError("startup_failed","Reader exited during startup; inspect the private reader.log.")
        time.sleep(0.25)
    raise ReaderError("startup_timeout","Reader did not become ready; no process was stopped. Inspect reader.log.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-file",type=Path,default=default_runtime_file())
    parser.add_argument("--check",action="store_true",help="Only verify current service; do not start anything.")
    parser.add_argument("--no-start",action="store_true",help="Reuse only; fail if no compatible service exists.")
    parser.add_argument("command",nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        result = ensure_service(args.runtime_file,start=not (args.check or args.no_start))
        if args.check:
            print(json.dumps(result));return 0
        if sys.stdin.isatty():print(json.dumps(result))
        return console_main(["--runtime-file",str(args.runtime_file),*args.command])
    except (ReaderError,OSError,ValueError) as error:
        print(json.dumps({"error":{"code":error.code if isinstance(error,ReaderError) else "launch_failed",
                                   "message":error.message if isinstance(error,ReaderError) else "Cannot start local reader; check runtime and private log permissions."}}),file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
