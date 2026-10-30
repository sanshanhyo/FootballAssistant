"""Import an observation envelope; never read a game process or original save."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from football_assistant_contracts.validation import validate_observation
from .config import Settings


def main():
    parser = argparse.ArgumentParser(description="Import one observation JSON envelope")
    parser.add_argument("path",type=Path)
    parser.add_argument("--fixture",action="store_true",help="Require explicitly synthetic input")
    args = parser.parse_args()
    settings = Settings.from_env()
    try:
        if args.path.stat().st_size > settings.max_request_bytes:
            raise ValueError("Observation file exceeds size limit")
        body = json.loads(args.path.read_text(encoding="utf-8"))
        validate_observation(body)
        if args.fixture and body["synthetic"] is not True:
            raise ValueError("--fixture requires synthetic=true")
        runtime = json.loads(settings.runtime_file.read_text(encoding="utf-8"))
        base_url = runtime["base_url"]
        if base_url != f"http://127.0.0.1:{settings.port}":
            raise ValueError("Runtime address does not match configured loopback port")
        request = Request(base_url+"/v1/observations",data=json.dumps(body,ensure_ascii=False).encode(),headers={"Authorization":"Bearer "+runtime["token"],"Content-Type":"application/json"},method="POST")
        with urlopen(request,timeout=10) as response:
            print(response.read().decode())
    except (OSError,ValueError,KeyError,HTTPError,URLError):
        print("Observation import failed: check the file, running backend and local runtime configuration.",file=sys.stderr)
        raise SystemExit(1) from None
