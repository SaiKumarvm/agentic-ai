"""A random integer generator tool.

Same shape as every other tool module: NAME, SCHEMA, run(**kwargs).
"""

import random

NAME = "random_number"

SCHEMA = {
    "name": NAME,
    "description": "Generate a random integer between minimum and maximum, inclusive.",
    "input_schema": {
        "type": "object",
        "properties": {
            "minimum": {"type": "integer", "description": "The lower bound, inclusive."},
            "maximum": {"type": "integer", "description": "The upper bound, inclusive."},
        },
        "required": ["minimum", "maximum"],
    },
}


def run(minimum: int, maximum: int) -> str:
    """Return a random integer in [minimum, maximum] as a string."""
    if minimum > maximum:
        return "Error: minimum must be less than or equal to maximum."
    return str(random.randint(minimum, maximum))
