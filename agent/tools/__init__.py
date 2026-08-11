"""Tool registry.

To add a new tool later:
1. Create a module in this package that exposes NAME, SCHEMA, and run(**kwargs).
2. Import it below and add it to _TOOL_MODULES.

No other file in the project needs to change — agent/core.py only ever
sees SCHEMAS and REGISTRY, never a specific tool.
"""

from . import calculator, get_current_time, random_number

_TOOL_MODULES = [calculator, get_current_time, random_number]

SCHEMAS = [module.SCHEMA for module in _TOOL_MODULES]
REGISTRY = {module.NAME: module.run for module in _TOOL_MODULES}
