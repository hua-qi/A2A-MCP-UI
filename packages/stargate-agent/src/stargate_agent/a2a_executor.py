"""A2A Agent Executor for stargate-agent using a2a-sdk"""
import asyncio
import json
import uuid
from datetime import datetime
from typing import AsyncGenerator

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import (
    Task,
    TaskStatus,
    TaskState,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    Message,
    DataPart,
    TextPart,
)

from stargate_agent import llm
from stargate_agent.agent_card_builder import build_agent_card


class StargateAgentExecutor(AgentExecutor):
    """Custom Agent Executor for handling A2A tasks"""

    def _create_status_event(self, task_id: str, context_id: str, state: TaskState, message_text: str, final: bool = False) -> TaskStatusUpdateEvent:
        """Helper to create TaskStatusUpdateEvent"""
        return TaskStatusUpdateEvent(
            contextId=context_id,
            taskId=task_id,
            final=final,
            status=TaskStatus(
                state=state,
                message=Message(
                    messageId=str(uuid.uuid4()),
                    role="agent",
                    parts=[TextPart(text=message_text)]
                )
            )
        )

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Execute task and publish events to event_queue"""
        task = context.current_task
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or str(uuid.uuid4())

        try:
            # Initial status
            await event_queue.enqueue_event(
                self._create_status_event(task_id, context_id, TaskState.working, "收到请求，开始处理...")
            )

            # Get message from context
            message = context.message
            if not message or not message.parts:
                await event_queue.enqueue_event(
                    self._create_status_event(task_id, context_id, TaskState.failed, "Empty message received", final=True)
                )
                return

            # Parse request from DataPart
            request_data = self._parse_request(message)

            # Check if this is a tool request (tool-protocol extension)
            if request_data.get("kind") == "tool_request":
                await self._handle_tool_request(task_id, context_id, request_data, event_queue)
                return

            # Regular agent request (structured-data extension)
            user_text = request_data.get("text", "")
            mode = request_data.get("mode", "endpoint")

            # Tool selection
            await event_queue.enqueue_event(
                self._create_status_event(task_id, context_id, TaskState.working, "正在识别工具...")
            )

            tool_name, tool_args = await llm.select_tool(user_text)

            # Execute tool
            await event_queue.enqueue_event(
                self._create_status_event(task_id, context_id, TaskState.working, f"执行工具: {tool_name}...")
            )

            # Process based on tool
            if tool_name == "query_employee_trend":
                result = await self._handle_employee_trend(mode)
            elif tool_name == "query_employee_trend_lazy":
                result = await self._handle_employee_trend_lazy(mode)
            elif tool_name == "open_github":
                result = await self._handle_open_github()
            else:
                result = {"text": "抱歉，我目前只支持查询员工趋势数据。"}

            response_message = self._create_response_message(result)

            await event_queue.enqueue_event(
                self._create_status_event(task_id, context_id, TaskState.completed, "处理完成", final=False)
            )

            await event_queue.enqueue_event(response_message)

        except Exception as e:
            await event_queue.enqueue_event(
                self._create_status_event(task_id, context_id, TaskState.failed, f"处理失败: {str(e)}", final=True)
            )

    async def _handle_tool_request(self, task_id: str, context_id: str, request_data: dict, event_queue: EventQueue) -> None:
        """Handle tool-protocol extension requests"""
        tool_name = request_data.get("toolName", "")
        arguments = request_data.get("arguments", {})
        request_id = request_data.get("id", "")

        await event_queue.enqueue_event(
            self._create_status_event(task_id, context_id, TaskState.working, f"执行工具: {tool_name}...")
        )

        # Execute tool based on name
        if tool_name == "query_employee_trend":
            result_data = await self._handle_employee_trend("endpoint")
        elif tool_name == "query_employee_trend_lazy":
            result_data = await self._handle_employee_trend_lazy("endpoint")
        elif tool_name == "open_github":
            result_data = await self._handle_open_github()
        else:
            result_data = {"error": f"Unknown tool: {tool_name}"}

        # Create tool response message
        response_message = self._create_tool_response_message(request_id, result_data)

        await event_queue.enqueue_event(
            self._create_status_event(task_id, context_id, TaskState.completed, "工具执行完成", final=False)
        )

        await event_queue.enqueue_event(response_message)

    def _create_tool_response_message(self, request_id: str, result: dict) -> Message:
        """Create tool response message with DataPart"""
        return Message(
            messageId=str(uuid.uuid4()),
            role="agent",
            parts=[
                DataPart(
                    data={
                        "kind": "tool_response",
                        "requestId": request_id,
                        "result": result
                    },
                    metadata={"schema": "https://stargate.example.com/schemas/tool-response-v1"}
                )
            ]
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Cancel a running task"""
        task_id = context.task_id or "unknown"
        context_id = context.context_id or "unknown"

        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                contextId=context_id,
                taskId=task_id,
                final=True,
                status=TaskStatus(
                    state=TaskState.canceled,
                    message=Message(
                        messageId=str(uuid.uuid4()),
                        role="agent",
                        parts=[TextPart(text="Task cancelled")]
                    )
                )
            )
        )

    def _parse_request(self, message: Message) -> dict:
        """Parse request data from message parts"""
        for part in message.parts:
            # Handle Part wrapper
            content = part.root if hasattr(part, 'root') else part

            if isinstance(content, DataPart):
                return content.data

        # Fallback: try to get text from TextPart
        for part in message.parts:
            content = part.root if hasattr(part, 'root') else part
            if isinstance(content, TextPart):
                return {"text": content.text, "mode": "endpoint"}

        return {}

    def _create_response_message(self, result: dict) -> Message:
        """Create response message with DataPart"""
        parts = []

        # Add text part if available
        if "text" in result:
            parts.append(TextPart(text=result["text"]))

        # Add DataPart with full result
        parts.append(DataPart(
            data=result,
            metadata={"schema": "https://stargate.example.com/schemas/agent-response-v1"}
        ))

        return Message(
            messageId=str(uuid.uuid4()),
            role="agent",
            parts=parts
        )

    async def _handle_employee_trend(self, mode: str) -> dict:
        """Handle employee trend query"""
        # Mock data for now
        return {
            "text": "已为您查询快手历年员工趋势数据，共 5 年记录。",
            "mcp_ui_resource": {
                "kind": "mcp_ui_resource",
                "resourceUri": "ui://stargate/employee-trend",
                "toolName": "query_employee_trend",
                "toolResult": {
                    "content": [{"type": "text", "text": "已为您查询快手历年员工趋势数据，共 5 年记录。"}],
                    "data": [
                        {"year": 2019, "count": 7000},
                        {"year": 2020, "count": 10000},
                        {"year": 2021, "count": 16000},
                        {"year": 2022, "count": 22000},
                        {"year": 2023, "count": 18000},
                    ],
                    "token": "mock-stargate-token-12345",
                },
                "uiMetadata": {
                    "preferred-frame-size": {"width": 560, "height": 420}
                },
            },
        }

    async def _handle_employee_trend_lazy(self, mode: str) -> dict:
        """Handle lazy employee trend query"""
        return {
            "text": "正在为您准备员工趋势数据，请稍候...",
            "mcp_ui_resource": {
                "kind": "mcp_ui_resource",
                "resourceUri": "ui://stargate/employee-trend-lazy",
                "toolName": "query_employee_trend_lazy",
                "toolResult": {
                    "content": [{"type": "text", "text": "正在为您准备员工趋势数据，请稍候..."}],
                    "token": "mock-stargate-token-12345",
                },
                "uiMetadata": {
                    "preferred-frame-size": {"width": 560, "height": 420}
                },
            },
        }

    async def _handle_open_github(self) -> dict:
        """Handle open GitHub request using externalUrl resource"""
        return {
            "text": "已为您打开 GitHub 主页。",
            "mcp_ui_resource": {
                "kind": "mcp_ui_resource",
                "resourceUri": "ui://stargate/github",
                "toolName": "open_github",
                "toolResult": {
                    "content": [{"type": "text", "text": "已为您打开 GitHub 主页。"}],
                },
                "uiMetadata": {
                    "preferred-frame-size": {"width": 800, "height": 600}
                },
            },
        }
