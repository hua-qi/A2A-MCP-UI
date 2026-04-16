"""A2A Message parts helpers for structured data transmission"""
import uuid
from a2a.types import Message, DataPart, TextPart, Part

REQUEST_SCHEMA = "https://stargate.example.com/schemas/agent-request-v1"
RESPONSE_SCHEMA = "https://stargate.example.com/schemas/agent-response-v1"


def _generate_id() -> str:
    """Generate unique message ID"""
    return str(uuid.uuid4())


def _get_part_content(part: Part):
    """Extract actual content from Part wrapper"""
    if hasattr(part, 'root'):
        return part.root
    return part


def make_agent_request_message(text: str, mode: str) -> Message:
    """Create A2A request message with DataPart containing structured data"""
    return Message(
        messageId=_generate_id(),
        role="user",
        parts=[
            DataPart(
                data={"text": text, "mode": mode},
                metadata={"schema": REQUEST_SCHEMA}
            )
        ]
    )


def parse_agent_response_message(message: Message) -> dict:
    """Parse A2A response message to extract structured data from DataPart"""
    for part in message.parts:
        content = _get_part_content(part)
        if isinstance(content, DataPart):
            # Validate schema if present in metadata
            metadata = content.metadata or {}
            if metadata.get("schema") == RESPONSE_SCHEMA:
                return content.data
            # If no schema or different schema, still return data
            return content.data
    raise ValueError("No DataPart found in response")


def make_agent_response_message(text: str, mcp_ui_resource: dict = None) -> Message:
    """Create A2A response message with text and optional MCP-UI resource"""
    parts = [TextPart(text=text)]
    
    response_data = {"text": text}
    if mcp_ui_resource:
        response_data["mcp_ui_resource"] = mcp_ui_resource
    
    parts.append(
        DataPart(
            data=response_data,
            metadata={"schema": RESPONSE_SCHEMA}
        )
    )
    
    return Message(
        messageId=_generate_id(),
        role="agent",
        parts=parts
    )
