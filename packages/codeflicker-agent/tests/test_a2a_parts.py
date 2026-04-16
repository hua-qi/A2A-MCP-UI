import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
from a2a.types import Message, DataPart, TextPart
from codeflicker_agent.a2a_parts import (
    make_agent_request_message,
    parse_agent_response_message,
    make_agent_response_message,
    _get_part_content,
    REQUEST_SCHEMA,
    RESPONSE_SCHEMA,
)


def test_make_request_has_data_part():
    msg = make_agent_request_message(text="查询员工", mode="endpoint")
    assert msg.role == "user"
    assert len(msg.parts) == 1
    
    part = _get_part_content(msg.parts[0])
    assert isinstance(part, DataPart)
    assert part.data["text"] == "查询员工"
    assert part.data["mode"] == "endpoint"
    assert part.metadata["schema"] == REQUEST_SCHEMA


def test_parse_response_extracts_data():
    response_msg = Message(
        messageId="test-1",
        role="agent",
        parts=[
            TextPart(text="回复内容"),
            DataPart(
                data={"text": "回复内容", "mcp_ui_resource": None},
                metadata={"schema": RESPONSE_SCHEMA}
            )
        ]
    )
    result = parse_agent_response_message(response_msg)
    assert result["text"] == "回复内容"
    assert "mcp_ui_resource" in result


def test_parse_response_with_resource():
    resource = {
        "kind": "mcp_ui_resource",
        "resourceUri": "ui://stargate/employee-trend",
        "toolName": "query_employee_trend",
    }
    response_msg = Message(
        messageId="test-2",
        role="agent",
        parts=[
            DataPart(
                data={"text": "已查询", "mcp_ui_resource": resource},
                metadata={"schema": RESPONSE_SCHEMA}
            )
        ]
    )
    result = parse_agent_response_message(response_msg)
    assert result["mcp_ui_resource"]["resourceUri"] == "ui://stargate/employee-trend"


def test_parse_raises_when_no_datapart():
    response_msg = Message(messageId="test-3", role="agent", parts=[TextPart(text="纯文本")])
    with pytest.raises(ValueError, match="No DataPart"):
        parse_agent_response_message(response_msg)


def test_make_response_message():
    resource = {"kind": "mcp_ui_resource", "resourceUri": "ui://test"}
    msg = make_agent_response_message(text="已查询", mcp_ui_resource=resource)

    assert msg.role == "agent"
    assert len(msg.parts) == 2

    text_parts = [_get_part_content(p) for p in msg.parts if isinstance(_get_part_content(p), TextPart)]
    data_parts = [_get_part_content(p) for p in msg.parts if isinstance(_get_part_content(p), DataPart)]

    assert len(text_parts) == 1
    assert len(data_parts) == 1
    assert text_parts[0].text == "已查询"
    assert data_parts[0].data["mcp_ui_resource"] == resource
