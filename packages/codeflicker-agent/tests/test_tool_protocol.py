import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
from a2a.types import Message, DataPart
from codeflicker_agent.tool_protocol import (
    make_tool_request_message,
    parse_tool_response_message,
    new_request_id,
)


def test_make_tool_request_message():
    msg = make_tool_request_message(
        request_id="req-001",
        tool_name="query_employee_trend",
        arguments={"year": 2023}
    )
    
    assert msg.role == "user"
    assert len(msg.parts) == 1
    
    content = msg.parts[0].root if hasattr(msg.parts[0], 'root') else msg.parts[0]
    assert content.data["kind"] == "tool_request"
    assert content.data["id"] == "req-001"
    assert content.data["toolName"] == "query_employee_trend"
    assert content.data["arguments"]["year"] == 2023


def test_parse_tool_response_message_ok():
    response_msg = Message(
        messageId="msg-1",
        role="agent",
        parts=[
            DataPart(
                data={
                    "kind": "tool_response",
                    "requestId": "req-001",
                    "result": {"data": [1, 2, 3]}
                }
            )
        ]
    )
    
    result = parse_tool_response_message(response_msg, expected_request_id="req-001")
    assert result == {"data": [1, 2, 3]}


def test_parse_tool_response_wrong_id_raises():
    response_msg = Message(
        messageId="msg-1",
        role="agent",
        parts=[
            DataPart(
                data={
                    "kind": "tool_response",
                    "requestId": "req-999",
                    "result": {}
                }
            )
        ]
    )
    
    with pytest.raises(ValueError, match="requestId mismatch"):
        parse_tool_response_message(response_msg, expected_request_id="req-001")


def test_parse_tool_response_wrong_kind_raises():
    response_msg = Message(
        messageId="msg-1",
        role="agent",
        parts=[
            DataPart(
                data={
                    "kind": "data",
                    "requestId": "req-001",
                    "result": {}
                }
            )
        ]
    )
    
    with pytest.raises(ValueError, match="No tool_response"):
        parse_tool_response_message(response_msg, expected_request_id="req-001")


def test_new_request_id_format():
    req_id = new_request_id()
    assert req_id.startswith("req-")
    assert len(req_id) > 4
