"""Frozen desktop entry point; no shell, dependency download or implicit dotenv."""
import os
import sys

if __name__ == "__main__":
    os.environ["FOOTBALL_ASSISTANT_DESKTOP"] = "1"
    if len(sys.argv) > 1 and sys.argv[1] == "--bridge-setup":
        from football_assistant_data.bridge_setup import main
        raise SystemExit(main(sys.argv[2:]))
    from football_assistant_data.app import main
    main()
