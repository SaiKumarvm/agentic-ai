"""A tool that returns the current local date and time.

Same shape as every other tool module: NAME, SCHEMA, run(**kwargs).
This one takes no input.
"""

from datetime import datetime

NAME = "get_current_time"

# Exposed as a constant (not just inlined in run()) so tests can parse
# run()'s output back into a datetime without duplicating the format string.
FORMAT = "%Y-%m-%d %H:%M:%S %A"

SCHEMA = {
    "name": NAME,
    "description": "Get the current local date and time on the machine running this agent.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


def run() -> str:
    """Return the current local date and time as a human-readable string."""
    return datetime.now().strftime(FORMAT)
