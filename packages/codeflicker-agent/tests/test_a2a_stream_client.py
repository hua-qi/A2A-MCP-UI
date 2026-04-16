import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
from a2a.types import TaskStatusUpdateEvent, Message, DataPart, TextPart, TaskStatus, TaskState
from codeflicker_agent.a2a_stream_client import A2AStreamClient


def test_convert_status_event():
    client = A2AStreamClient("http://localhost:3011")
    
    event = TaskStatusUpdateEvent(
        contextId="ctx-1",
        taskId="task-1",
        final=False,
        status=TaskStatus(
            state=TaskState.working,
            message=Message(
                messageId="msg-1",
                role="agent",
                parts=[TextPart(text="正在处理...")]
            )
        )
    )
    
    result = client._convert_event(event)
    assert result["type"] == "status"
    assert result["state"] == "working"
    assert result["message"] == "正在处理..."
    assert result["final"] is False


def test_convert_message_event():
    client = A2AStreamClient("http://localhost:3011")
    
    event = Message(
        messageId="msg-1",
        role="agent",
        parts=[
            TextPart(text="完成"),
            DataPart(data={"text": "完成", "result": "ok"})
        ]
    )
    
    result = client._convert_event(event)
    assert result["type"] == "complete"
    assert result["result"]["text"] == "完成"


def test_extract_text():
    client = A2AStreamClient("http://localhost:3011")
    
    message = Message(
        messageId="msg-1",
        role="agent",
        parts=[TextPart(text="测试文本")]
    )
    
    text = client._extract_text(message)
    assert text == "测试文本"
