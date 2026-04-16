"""AgentCard builder for a2a-sdk"""
from a2a.types import AgentCard, AgentCapabilities, AgentExtension

A2A_PORT = 3011

def build_agent_card() -> AgentCard:
    """Build AgentCard with A2A extensions for a2a-sdk"""
    return AgentCard(
        name="stargate-agent",
        description="Stargate A2A Agent with MCP-UI support",
        url=f"http://localhost:{A2A_PORT}",
        version="0.1.0",
        capabilities=AgentCapabilities(
            streaming=True,
            extensions=[
                AgentExtension(uri="https://stargate.example.com/ext/a2a-structured-data/v1", name="structured-data", required=True),
                AgentExtension(uri="https://stargate.example.com/ext/a2a-streaming/v1", name="streaming", required=True),
                AgentExtension(uri="https://stargate.example.com/ext/a2a-tool-protocol/v1", name="tool-protocol", required=True),
            ]
        ),
        defaultInputModes=["text/plain"],
        defaultOutputModes=["text/plain"],
        skills=[]
    )
