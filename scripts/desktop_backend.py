"""Frozen desktop entry point; no shell, dependency download or implicit dotenv."""
import os

if __name__ == "__main__":
    os.environ["FOOTBALL_ASSISTANT_DESKTOP"] = "1"
    from football_assistant_data.app import main
    main()
