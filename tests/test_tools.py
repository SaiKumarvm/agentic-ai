"""Tests for the tool layer.

These are pure-logic tests only — no network calls, no API key, no
`claude` CLI invocation. They check the tool functions directly and the
registries both backends build from them.

Run with:
    python -m unittest discover -s tests -v
"""

import unittest
from datetime import datetime

from agent.sdk_tools import ALLOWED_TOOL_NAMES, MCP_SERVER_NAME
from agent.tools import REGISTRY, SCHEMAS, calculator, get_current_time, random_number


class CalculatorToolTests(unittest.TestCase):
    def test_basic_arithmetic(self):
        self.assertEqual(calculator.run("2 + 2"), "4")
        self.assertEqual(calculator.run("12 * (3 + 4)"), "84")

    def test_rejects_disallowed_characters(self):
        # Blocks anything outside digits/operators/parentheses/whitespace,
        # which is what stops arbitrary code injection via the expression.
        self.assertTrue(calculator.run("__import__('os')").startswith("Error"))

    def test_handles_runtime_errors(self):
        self.assertTrue(calculator.run("1 / 0").startswith("Error"))


class GetCurrentTimeToolTests(unittest.TestCase):
    def test_returns_a_non_empty_string(self):
        result = get_current_time.run()
        self.assertIsInstance(result, str)
        self.assertTrue(result)

    def test_matches_the_current_local_time(self):
        result = get_current_time.run()
        parsed = datetime.strptime(result, get_current_time.FORMAT)
        now = datetime.now()

        # The format's resolution is whole seconds, so allow a small window
        # for the time it takes to call run() and then datetime.now() here.
        self.assertLess(abs((now - parsed).total_seconds()), 5)

    def test_reflects_the_actual_local_date(self):
        result = get_current_time.run()
        parsed = datetime.strptime(result, get_current_time.FORMAT)
        today = datetime.now().date()
        self.assertEqual(parsed.date(), today)


class RandomNumberToolTests(unittest.TestCase):
    def test_returns_a_value_within_range(self):
        result = int(random_number.run(minimum=1, maximum=10))
        self.assertGreaterEqual(result, 1)
        self.assertLessEqual(result, 10)

    def test_handles_a_single_value_range(self):
        self.assertEqual(random_number.run(minimum=5, maximum=5), "5")

    def test_rejects_an_inverted_range(self):
        self.assertTrue(random_number.run(minimum=10, maximum=1).startswith("Error"))


class ToolRegistryTests(unittest.TestCase):
    """Checks agent/tools/__init__.py, used by the `api` backend."""

    def test_registry_includes_all_tools(self):
        self.assertEqual(
            set(REGISTRY.keys()), {"calculator", "get_current_time", "random_number"}
        )

    def test_registry_functions_are_callable_by_name(self):
        self.assertEqual(REGISTRY["calculator"](expression="1 + 1"), "2")
        self.assertIsInstance(REGISTRY["get_current_time"](), str)
        self.assertEqual(REGISTRY["random_number"](minimum=3, maximum=3), "3")

    def test_schemas_include_all_tools(self):
        names = {schema["name"] for schema in SCHEMAS}
        self.assertEqual(names, {"calculator", "get_current_time", "random_number"})


class SdkToolRegistrationTests(unittest.TestCase):
    """Checks agent/sdk_tools.py, used by the `sdk` backend."""

    def test_allowed_tool_names_include_all_tools(self):
        self.assertEqual(
            set(ALLOWED_TOOL_NAMES),
            {
                f"mcp__{MCP_SERVER_NAME}__calculator",
                f"mcp__{MCP_SERVER_NAME}__get_current_time",
                f"mcp__{MCP_SERVER_NAME}__random_number",
            },
        )


if __name__ == "__main__":
    unittest.main()
