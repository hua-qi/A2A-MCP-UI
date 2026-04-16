"""CodeFlicker Agent - CF-Agent with a2a-sdk"""
import os
import json
from typing import AsyncGenerator
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from codeflicker_agent import llm
from codeflicker_agent.extension_negotiation import validate_extensions, ExtensionNegotiationError
from codeflicker_agent.a2a_stream_client import call_sg_agent_streaming
from codeflicker_agent.tool_protocol import (
    make_tool_request_message,
    parse_tool_response_message,
    new_request_id,
)

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../../../.env"))

SG_AGENT_A2A_URL = os.environ.get("SG_AGENT_A2A_URL", "http://localhost:3011")
SG_AGENT_BASE_URL = os.environ.get("SG_AGENT_BASE_URL", "http://localhost:3001")
PORT = int(os.environ.get("CF_AGENT_PORT", 3002))

app = FastAPI(title="codeflicker-agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

current_mode: str = "endpoint"


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/mode")
async def set_mode(request: Request):
    global current_mode
    body = await request.json()
    mode = body.get("mode", "endpoint")
    if mode not in ("endpoint", "mcp"):
        return JSONResponse({"error": "mode must be 'endpoint' or 'mcp'"}, status_code=400)
    current_mode = mode
    return {"mode": current_mode}


@app.get("/mode")
async def get_mode():
    return {"mode": current_mode}


async def validate_sg_extensions() -> bool:
    """Validate SG-Agent has required extensions"""
    try:
        import httpx
        from a2a.client.card_resolver import A2ACardResolver
        async with httpx.AsyncClient() as client:
            resolver = A2ACardResolver(client, SG_AGENT_A2A_URL)
            card = await resolver.get_agent_card()
            validate_extensions(card)
        return True
    except ExtensionNegotiationError as e:
        print(f"Extension validation failed: {e}")
        return False
    except Exception as e:
        print(f"Failed to resolve agent card: {e}")
        return False


@app.post("/chat-stream")
async def chat_stream(request: Request):
    """SSE streaming endpoint for chat messages"""
    body = await request.json()
    user_message: str = body.get("message", "")
    mode: str = body.get("mode", current_mode)

    async def generate() -> AsyncGenerator[str, None]:
        try:
            # Validate extensions first
            if not await validate_sg_extensions():
                error_data = {"type": "error", "code": -32001, "message": "Extension negotiation failed"}
                yield f"data: {json.dumps(error_data)}\n\n"
                return

            # Detect intent
            intent = await llm.detect_intent(user_message)

            if intent != "query_data":
                result = {"parts": [{"kind": "text", "text": "您好！我是 CodeFlicker 助手，可以帮您查询快手员工趋势等数据。"}]}
                yield f"data: {json.dumps({'type': 'complete', 'result': result})}\n\n"
                return

            # Stream from SG-Agent
            async for event in call_sg_agent_streaming(SG_AGENT_A2A_URL, user_message, mode):
                yield f"data: {json.dumps(event)}\n\n"

        except Exception as e:
            error_data = {"type": "error", "code": -32000, "message": str(e)}
            yield f"data: {json.dumps(error_data)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/a2a-tool-call")
async def a2a_tool_call(request: Request):
    """Handle tool calls via A2A protocol"""
    body = await request.json()
    tool_name = body.get("toolName", "")
    arguments = body.get("arguments", {})
    
    try:
        # Validate extensions
        if not await validate_sg_extensions():
            return JSONResponse(
                {"error": {"code": -32001, "message": "Extension negotiation failed"}},
                status_code=400
            )

        request_id = new_request_id()
        
        # Create tool request message
        message = make_tool_request_message(request_id, tool_name, arguments)
        
        # Send via A2A streaming
        result = None
        async for event in call_sg_agent_streaming(SG_AGENT_A2A_URL, "", "endpoint"):
            if event.get("type") == "complete":
                # Parse tool response from result
                result_data = event.get("result", {})
                # For now, return the full result
                result = result_data
                break
            elif event.get("type") == "error":
                return JSONResponse(
                    {"error": {"code": event.get("code", -32000), "message": event.get("message", "")}},
                    status_code=500
                )
        
        if result is None:
            return JSONResponse(
                {"error": {"code": -32000, "message": "No response from agent"}},
                status_code=500
            )
        
        return JSONResponse({"toolResult": result.get("toolResult", result)})
        
    except Exception as e:
        return JSONResponse(
            {"error": {"code": -32000, "message": str(e)}},
            status_code=500
        )


@app.get("/resource-proxy")
async def resource_proxy(uri: str, source: str = "host"):
    """Proxy resource requests to SG-Agent"""
    import httpx
    
    if uri.startswith("ui://stargate/"):
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{SG_AGENT_BASE_URL}/mcp/resources/read",
                params={"uri": uri},
            )
            if resp.status_code == 200:
                return JSONResponse(resp.json())
            return JSONResponse({"error": "Resource not found"}, status_code=resp.status_code)
    
    return JSONResponse({"error": "Unknown resource host"}, status_code=404)


def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
