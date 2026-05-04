"""Compatibility wrapper for the FastAPI Scanntech API."""

from api_fastapi import *  # noqa: F401,F403
from api_fastapi import main


if __name__ == "__main__":
    main()
