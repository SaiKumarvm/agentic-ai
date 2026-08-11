"""Builds the Anthropic API client used by the agent."""

from anthropic import Anthropic

from . import config


def get_client() -> Anthropic:
    """Create an Anthropic client using the configured API key.

    Raises agent.config.ConfigError if no API key is set.
    """
    api_key = config.get_api_key()
    return Anthropic(api_key=api_key)
