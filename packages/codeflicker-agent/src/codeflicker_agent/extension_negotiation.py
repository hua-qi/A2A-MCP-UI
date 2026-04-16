"""Extension negotiation for A2A protocol"""
from a2a.types import AgentCard

REQUIRED_EXT_URIS = [
    "https://stargate.example.com/ext/a2a-structured-data/v1",
    "https://stargate.example.com/ext/a2a-streaming/v1",
    "https://stargate.example.com/ext/a2a-tool-protocol/v1",
]


class ExtensionNegotiationError(Exception):
    """Raised when required extensions are not supported by remote agent"""
    pass


def validate_extensions(agent_card: AgentCard) -> None:
    """Validate that all required extensions are present and marked required"""
    extensions = agent_card.capabilities.extensions or []
    declared = {e.uri: e.required for e in extensions}
    
    for uri in REQUIRED_EXT_URIS:
        if uri not in declared:
            raise ExtensionNegotiationError(
                f"Required extension not declared by remote agent: {uri}"
            )
        if not declared[uri]:
            raise ExtensionNegotiationError(
                f"Extension exists but not marked required: {uri}"
            )
