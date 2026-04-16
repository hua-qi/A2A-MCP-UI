"""A2A Streaming Client for connecting to SG-Agent (simplified HTTP version)"""
import json
import uuid
from typing import AsyncGenerator, Optional
import httpx

from codeflicker_agent.a2a_parts import make_agent_request_message


class A2AStreamClient:
    """Client for streaming A2A communication with SG-Agent"""

    def __init__(self, endpoint_url: str):
        self.endpoint_url = endpoint_url

    async def send_message_stream(
        self,
        text: str,
        mode: str = "endpoint"
    ) -> AsyncGenerator[dict, None]:
        """
        Send message and receive streaming response via HTTP SSE.
        Yields events: status updates and final result.
        """
        # Build A2A JSON-RPC request
        message = make_agent_request_message(text, mode)
        
        # Convert to dict
        message_dict = {
            "messageId": message.message_id,
            "role": message.role,
            "parts": []
        }
        for part in message.parts:
            content = part.root if hasattr(part, 'root') else part
            if hasattr(content, 'kind') and content.kind == 'data':
                message_dict["parts"].append({
                    "kind": "data",
                    "data": content.data,
                    "metadata": content.metadata
                })
        
        request_payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "message/stream",
            "params": {
                "message": message_dict,
                "metadata": {}
            }
        }
        
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"{self.endpoint_url}",
                    json=request_payload,
                    headers={"Content-Type": "application/json"},
                    timeout=60.0
                ) as response:
                    response.raise_for_status()
                    
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            try:
                                event_data = json.loads(line[6:])
                                yield self._convert_event(event_data)
                            except json.JSONDecodeError:
                                continue
                        elif line.strip() == "":
                            continue
                        
        except Exception as e:
            yield {
                "type": "error",
                "code": -32000,
                "message": f"Streaming error: {str(e)}"
            }

    def _convert_event(self, event: dict) -> dict:
        """Convert A2A JSON-RPC response to dict format for frontend"""
        # Check for error
        if "error" in event:
            return {
                "type": "error",
                "code": event["error"].get("code", -32000),
                "message": event["error"].get("message", "Unknown error"),
            }
        
        result = event.get("result", {})
        
        # Check event type based on kind field
        kind = result.get("kind", "")
        
        if kind == "status-update":
            status = result.get("status", {})
            message = status.get("message", {})
            parts = message.get("parts", [])
            text = ""
            for part in parts:
                content = part.get("root", part)
                if content.get("kind") == "text":
                    text = content.get("text", "")
                    break
            
            return {
                "type": "status",
                "state": status.get("state", "unknown"),
                "message": text,
                "final": result.get("final", False),
            }
        elif kind == "message":
            # Final response message
            parts = result.get("parts", [])
            data = None
            for part in parts:
                content = part.get("root", part)
                if content.get("kind") == "data":
                    data = content.get("data", {})
                    break
            
            return {
                "type": "complete",
                "result": data or {"text": "No data"},
            }
        elif kind == "task":
            return {
                "type": "task",
                "task_id": result.get("id", ""),
                "state": result.get("status", {}).get("state", "unknown"),
            }
        else:
            return {
                "type": "unknown",
                "event_type": kind or "unknown",
            }


async def call_sg_agent_streaming(
    endpoint_url: str,
    text: str,
    mode: str = "endpoint"
) -> AsyncGenerator[dict, None]:
    """Convenience function for streaming calls"""
    client = A2AStreamClient(endpoint_url)
    async for event in client.send_message_stream(text, mode):
        yield event
