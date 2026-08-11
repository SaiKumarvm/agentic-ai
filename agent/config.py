"""Configuration and environment loading for the agent.

Nothing here raises at import time (so importing this module is always
safe); get_api_key() only raises when the agent actually tries to run.
"""

import os
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-opus-5"
MAX_TOKENS = 1024
MAX_ITERATIONS = 8  # safety cap on tool-call round trips, to avoid infinite loops


class ConfigError(Exception):
    """Raised when required configuration (e.g. the API key) is missing."""


def get_api_key() -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ConfigError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return api_key
