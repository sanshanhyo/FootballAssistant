"""A fixed, read-only JSON command console for people and future Agent clients."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import sys
import time

from .reader_client import ReaderClient, ReaderError

COMMANDS = {
    "help":"List these commands.",
    "status":"Current source, connection, sampling times and decoder availability.",
    "snapshot":"Latest selected observation: --after N --limit N --event-id ID.",
    "raw-ui":"Snapshot filtered to raw UI text; same paging options and cache limitations.",
    "watch":"Changes only: --after CURSOR --interval SECONDS --polls N (optional finite run). Ctrl-C returns to console.",
    "native":"Explicit sanitized native header diagnostics: --after N --limit N.",
    "event":"Read the full stored change event at a numeric cursor: event CURSOR.",
    "quit":"Exit the console; leave the service and game running.",
}
VISIBLE_EVENTS = {"snapshot_received","ui_text_changed","raw_fields_changed","source_connected","source_stale","source_disconnected"}


class CommandParser(argparse.ArgumentParser):
    def error(self,message):
        raise ReaderError("invalid_arguments",message)

    def exit(self,status=0,message=None):
        raise ReaderError("invalid_arguments",message or "Use help for supported commands.")


def emit(value):
    print(json.dumps(value,ensure_ascii=False,separators=(",",":"),allow_nan=False),flush=True)


def number(value):
    parsed = int(value)
    if parsed<0 or parsed>9223372036854775807:raise ValueError()
    return parsed


def arguments(command,args):
    parser = CommandParser(prog=command,add_help=False)
    if command in ("snapshot","raw-ui","native"):
        parser.add_argument("--after",type=number,default=0)
        parser.add_argument("--limit",type=int,default=20 if command=="native" else 100)
        if command!="native":parser.add_argument("--event-id")
    elif command=="watch":
        parser.add_argument("--after",type=number)
        parser.add_argument("--interval",type=float,default=1)
        parser.add_argument("--polls",type=int)
    elif command=="event":
        parser.add_argument("cursor",type=number)
    result = parser.parse_args(args)
    if hasattr(result,"limit") and not 1<=result.limit<=(100 if command=="native" else 200):
        raise ReaderError("invalid_arguments","Page limit must be 1..100 for native or 1..200 for facts.")
    if command=="watch" and (not 0.5<=result.interval<=60 or result.polls is not None and result.polls<1):
        raise ReaderError("invalid_arguments","Watch interval must be 0.5..60 seconds and polls must be positive.")
    return result


def watch(client,args,*,output=emit,sleep=time.sleep):
    cursor = args.after
    polls = 0
    last_error = None
    while args.polls is None or polls<args.polls:
        polls += 1
        try:
            if cursor is None:
                cursor = client.status()["latest_event_cursor"]
            page = client.get("/v1/events",after=cursor,limit=100)
            if page.get("cursor_reset_required"):
                output({"type":"cursor_reset","previous_cursor":cursor,"latest_cursor":page["latest_cursor"],"reason":"service_history_changed"})
                cursor = 0
            else:
                next_cursor = page.get("next_cursor")
                if not isinstance(next_cursor,int) or next_cursor<cursor or page.get("has_more") and next_cursor==cursor:
                    # Bounded pages must make progress, even when a single event is summarized.
                    raise ReaderError("cursor_stalled","Event page did not advance; retry later without a tight loop.")
                for event in page.get("events",[]):
                    if event.get("kind") in VISIBLE_EVENTS:
                        output({"type":"change",**event})
                cursor = next_cursor
            if last_error is not None:
                output({"type":"connection","state":"recovered","cursor":cursor})
            last_error = None
        except ReaderError as error:
            if last_error != error.code:
                output({"type":"connection","state":"unavailable","code":error.code,"message":error.message,"cursor":cursor})
            last_error = error.code
        # Backlog draining is bounded to the configured rate, including stalled pages.
        if args.polls is None or polls<args.polls:
            sleep(args.interval)
    return cursor


def execute(client,words,*,output=emit):
    if not words:return True
    command,*rest = words
    if command not in COMMANDS:
        raise ReaderError("unsupported","Unsupported command. Use help; game writes and arbitrary invocation are unavailable.")
    args = arguments(command,rest)
    if command=="help":output({"commands":COMMANDS,"read_only":True,"format":"JSON Lines"})
    elif command=="quit":return False
    elif command=="status":output(client.status())
    elif command in ("snapshot","raw-ui"):
        output(client.snapshot(args.after,args.limit,args.event_id,raw_ui=command=="raw-ui"))
    elif command=="native":
        output({"scope":"native_header_diagnostics_only","football_field_values":False,
                **client.get("/v1/interfaces/native-observers",after=args.after,limit=args.limit)})
    elif command=="event":output(client.get("/v1/events/"+str(args.cursor)))
    elif command=="watch":watch(client,args,output=output)
    return True


def console(client,*,stream=None,output=emit):
    stream = stream or sys.stdin
    interactive = stream.isatty()
    if interactive:output({"reader_console":"ready","read_only":True,"hint":"help for commands; quit leaves the backend running"})
    for_line = iter(stream.readline,"")
    while True:
        try:
            if interactive:print("fm-reader> ",end="",flush=True)
            line = next(for_line)
            if not execute(client,shlex.split(line),output=output):break
        except StopIteration:break
        except KeyboardInterrupt:
            output({"type":"watch_stopped","service_unchanged":True})
        except (ReaderError,ValueError) as error:
            output({"error":{"code":error.code if isinstance(error,ReaderError) else "invalid_arguments",
                             "message":error.message if isinstance(error,ReaderError) else "Cannot parse command quoting or arguments."}})
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only FootballAssistant JSON console; no model required.")
    parser.add_argument("--runtime-file",type=Path)
    parser.add_argument("command",nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    client = ReaderClient(args.runtime_file)
    if not args.command:return console(client)
    try:
        execute(client,args.command)
        return 0
    except KeyboardInterrupt:
        emit({"type":"watch_stopped","service_unchanged":True})
        return 0
    except ReaderError as error:
        emit({"error":{"code":error.code,"message":error.message}})
        return 1


if __name__=="__main__":
    raise SystemExit(main())
