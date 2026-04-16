import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
import asyncio
from a2a.types import Task, Message, DataPart, TaskStatusUpdateEvent, TaskStatus, TaskState
from stargate_agent.a2a_executor import StargateAgentExecutor


@pytest.fixture
def executor():
    return StargateAgentExecutor()


@pytest.fixture
def sample_task():
    return Task(
        id="test-task-1",
        contextId="ctx-1",
        status=TaskStatus(
            state=TaskState.submitted,
            message=Message(
                messageId="msg-1",
                role="user",
                parts=[DataPart(data={"text": "查询员工趋势", "mode": "endpoint"})]
            )
        )
    )


@pytest.fixture
def tool_request_task():
    return Task(
        id="test-task-2",
        contextId="ctx-2",
        status=TaskStatus(
            state=TaskState.submitted,
            message=Message(
                messageId="msg-2",
                role="user",
                parts=[DataPart(data={
                    "kind": "tool_request",
                    "id": "req-001",
                    "toolName": "query_employee_trend",
                    "arguments": {}
                })]
            )
        )
    )


def test_parse_request_with_datapart(executor):
    message = Message(
        messageId="msg-1",
        role="user",
        parts=[DataPart(data={"text": "查询员工", "mode": "endpoint"})]
    )
    result = executor._parse_request(message)
    assert result["text"] == "查询员工"
    assert result["mode"] == "endpoint"


@pytest.mark.asyncio
async def test_execute_yields_events(executor, sample_task):
    events = []
    async for event in executor.execute(sample_task):
        events.append(event)
    
    assert len(events) >= 3
    
    status_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent)]
    assert len(status_events) >= 2
    
    final_status = status_events[-1]
    assert final_status.status.state in [TaskState.completed, TaskState.failed]


@pytest.mark.asyncio
async def test_handle_employee_trend(executor):
    result = await executor._handle_employee_trend("endpoint")
    assert "text" in result
    assert "mcp_ui_resource" in result
    assert result["mcp_ui_resource"]["toolName"] == "query_employee_trend"


@pytest.mark.asyncio
async def test_handle_tool_request(executor, tool_request_task):
    events = []
    async for event in executor.execute(tool_request_task):
        events.append(event)
    
    # Should have status events and final message
    assert len(events) >= 3
    
    # Check for completion
    status_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent)]
    assert status_events[-1].status.state == TaskState.completed
    
    # Check response message contains tool_response
    messages = [e for e in events if isinstance(e, Message)]
    assert len(messages) == 1
    
    content = messages[0].parts[0].root if hasattr(messages[0].parts[0], 'root') else messages[0].parts[0]
    assert content.data["kind"] == "tool_response"
    assert content.data["requestId"] == "req-001"
    assert "result" in content.data
