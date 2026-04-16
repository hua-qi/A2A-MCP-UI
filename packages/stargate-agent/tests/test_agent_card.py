import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from stargate_agent.agent_card_builder import build_agent_card

REQUIRED_EXTENSIONS = [
    ("https://stargate.example.com/ext/a2a-structured-data/v1", "structured-data"),
    ("https://stargate.example.com/ext/a2a-streaming/v1", "streaming"),
    ("https://stargate.example.com/ext/a2a-tool-protocol/v1", "tool-protocol"),
]

def test_agent_card_has_three_extensions():
    card = build_agent_card()
    extensions = card.capabilities.extensions or []
    assert len(extensions) == 3, f"Expected 3 extensions, got {len(extensions)}"
    
    ext_uris = [e.uri for e in extensions]
    for uri, _ in REQUIRED_EXTENSIONS:
        assert uri in ext_uris, f"Missing extension: {uri}"

def test_agent_card_all_extensions_required():
    card = build_agent_card()
    for ext in card.capabilities.extensions or []:
        assert ext.required is True, f"Extension {ext.uri} not marked required"

def test_agent_card_streaming_enabled():
    card = build_agent_card()
    assert card.capabilities.streaming is True
