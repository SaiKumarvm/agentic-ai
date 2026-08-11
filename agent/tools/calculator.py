"""A basic arithmetic calculator tool.

Every tool module exposes two things the registry (tools/__init__.py) picks up:
- NAME:   the tool's identifier
- SCHEMA: the JSON schema Claude sees, describing what the tool does and its inputs
- run():  the actual implementation, called with the inputs Claude provided
"""

NAME = "calculator"

SCHEMA = {
    "name": NAME,
    "description": "Evaluate a basic arithmetic expression, e.g. '12 * (3 + 4)'.",
    "input_schema": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "A basic arithmetic expression to evaluate.",
            }
        },
        "required": ["expression"],
    },
}

_ALLOWED_CHARS = set("0123456789+-*/(). ")


def run(expression: str) -> str:
    """Evaluate `expression` and return the result as a string.

    Only digits, basic operators, parentheses, and whitespace are allowed —
    this blocks arbitrary code injection via the expression string.
    """
    if not set(expression) <= _ALLOWED_CHARS:
        return "Error: expression contains disallowed characters."
    try:
        return str(eval(expression, {"__builtins__": {}}))
    except Exception as e:
        return f"Error: {e}"
