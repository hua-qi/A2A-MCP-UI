import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from stargate_mcp_ui_server.tools import get_ui_resource, RESOURCE_URI, get_lazy_ui_resource, LAZY_RESOURCE_URI

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../../../.env"))

_port = int(os.environ.get("PORT", 3005))
mcp = FastMCP("stargate-mcp-ui-server", host="0.0.0.0", port=_port)


@mcp.tool()
async def query_employee_trend() -> dict:
    r = get_ui_resource()
    return {
        "_meta": {"ui": {"resourceUri": RESOURCE_URI}},
        "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
        "resource": r["resource"],
        "toolName": "query_employee_trend",
    }


@mcp.resource(RESOURCE_URI, mime_type="text/html;profile=mcp-app")
async def employee_trend_resource() -> str:
    r = get_ui_resource()
    return r["resource"]["text"]


@mcp.tool()
async def query_employee_trend_lazy() -> dict:
    r = get_lazy_ui_resource()
    return {
        "_meta": {"ui": {"resourceUri": LAZY_RESOURCE_URI}},
        "content": [{"type": "text", "text": "正在为您准备员工趋势数据，请稍候..."}],
        "resource": r["resource"],
        "toolName": "query_employee_trend_lazy",
    }


@mcp.resource(LAZY_RESOURCE_URI, mime_type="text/html;profile=mcp-app")
async def employee_trend_lazy_resource() -> str:
    r = get_lazy_ui_resource()
    return r["resource"]["text"]


def main():
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
