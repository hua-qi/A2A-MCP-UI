import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
from stargate_mcp_ui_server.main import mcp
from stargate_mcp_ui_server.tools import RESOURCE_URI, LAZY_RESOURCE_URI


def test_mcp_server_name():
    assert mcp.name == "stargate-mcp-ui-server"


def test_tool_registered():
    tool_names = [t.name for t in mcp._tool_manager.list_tools()]
    assert "query_employee_trend" in tool_names


@pytest.mark.asyncio
async def test_query_employee_trend_returns_resource_uri():
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    tool = tools["query_employee_trend"]
    result = await tool.fn()
    assert isinstance(result, dict)
    assert result.get("_meta", {}).get("ui", {}).get("resourceUri") == RESOURCE_URI


@pytest.mark.asyncio
async def test_query_employee_trend_has_no_business_data_in_tool_result():
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    tool = tools["query_employee_trend"]
    result = await tool.fn()
    tool_result = result.get("toolResult", {})
    assert "data" not in tool_result
    assert "token" not in tool_result


def test_lazy_tool_registered():
    tool_names = [t.name for t in mcp._tool_manager.list_tools()]
    assert "query_employee_trend_lazy" in tool_names


@pytest.mark.asyncio
async def test_query_employee_trend_lazy_has_no_tool_result():
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    tool = tools["query_employee_trend_lazy"]
    result = await tool.fn()
    assert isinstance(result, dict)
    assert result.get("_meta", {}).get("ui", {}).get("resourceUri") == LAZY_RESOURCE_URI
    assert "toolResult" not in result
