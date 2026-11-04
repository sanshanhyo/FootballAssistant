"""Load the replaceable LGPL Edge adapter source, never from a user-writable cwd."""
from pathlib import Path
import importlib.util
import sys


def run(args):
    if getattr(sys, "frozen", False):
        source = Path(sys.executable).resolve().parent / "edge-tts-source" / "edge_tts"
        spec = importlib.util.spec_from_file_location(
            "edge_tts", source / "__init__.py", submodule_search_locations=[str(source)]
        )
        if spec is None or spec.loader is None or not (source / "__init__.py").is_file():
            raise RuntimeError("Packaged Edge TTS source is missing")
        module = importlib.util.module_from_spec(spec)
        sys.modules["edge_tts"] = module
        spec.loader.exec_module(module)
    from edge_tts.util import main
    sys.argv = [sys.argv[0], *args]
    main()
