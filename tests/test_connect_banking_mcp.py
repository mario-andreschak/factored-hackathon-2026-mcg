"""The registration probe must agree with the configured MCP mode."""
import json

import pytest

from scripts.connect_banking_mcp import ACTION_TOOLS, READ_TOOLS, assert_ready_tools


@pytest.mark.parametrize("mode,expected", [
    ("delegated", READ_TOOLS | ACTION_TOOLS),
    ("operator-test", READ_TOOLS),
    ("synthetic-demo", READ_TOOLS),
])
def test_readiness_requires_exact_mode_tool_set(tmp_path, mode, expected):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"mode": mode}))
    names = sorted(expected)
    assert assert_ready_tools(config, {"tools": [{"name": name} for name in names]}) == names
    for invalid in (names[:-1], names + ["unexpected"], names + names[:1]):
        with pytest.raises(ValueError, match="not ready"):
            assert_ready_tools(config, {"tools": [{"name": name} for name in invalid]})
