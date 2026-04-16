"""Tool Protocol for A2A-based tool calling"""
import uuid
from typing import Optional
from a2a.types import Message, DataPart, TextPart


TOOL_REQUEST_SCHEMA = "https://stargate.example.com/schemas/tool-request-v1"
TOOL_RESPONSE_SCHEMA = "https://stargate.example.com/schemas/tool-response-v1"


def make_tool_request_message(
    request_id: str,
    tool_name: str,
    arguments: dict
) -> Message:
    """Create A2A message with ToolRequestPart"""
    return Message(
        messageId=str(uuid.uuid4()),
        role="user",
        parts=[
            DataPart(
                data={
                    "kind": "tool_request",
                    "id": request_id,
                    "toolName": tool_name,
                    "arguments": arguments
                },
                metadata={"schema": TOOL_REQUEST_SCHEMA}
            )
        ]
    )


def parse_tool_response_message(message: Message, expected_request_id: str) -> dict:
    """Parse A2A message to extract tool response"""
    for part in message.parts:
        content = part.root if hasattr(part, 'root') else part
        
        if isinstance(content, DataPart):
            data = content.data
            if data.get("kind") == "tool_response":
                if data.get("requestId") != expected_request_id:
                    raise ValueError(
                        f"requestId mismatch: expected {expected_request_id!r}, "
                        f"got {data.get('requestId')!r}"
                    )
                return data.get("result", {})
    
    raise ValueError("No tool_response found in message")


def new_request_id() -> str:
    """Generate new unique request ID"""
    return f"req-{uuid.uuid4().hex[:12]}"
