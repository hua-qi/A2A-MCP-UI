import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
from a2a.types import AgentCard, AgentCapabilities, AgentExtension
from codeflicker_agent.extension_negotiation import validate_extensions, ExtensionNegotiationError

REQUIRED_EXT_URIS = [
    "https://stargate.example.com/ext/a2a-structured-data/v1",
    "https://stargate.example.com/ext/a2a-streaming/v1",
    "https://stargate.example.com/ext/a2a-tool-protocol/v1",
]

def _make_card(extensions):
    return AgentCard(
        name="test",
        description="test",
        url="http://localhost",
        version="1.0",
        capabilities=AgentCapabilities(extensions=extensions),
        defaultInputModes=["text/plain"],
        defaultOutputModes=["text/plain"],
        skills=[]
    )

def test_validate_passes_when_all_required():
    extensions = [
        AgentExtension(uri=uri, required=True) for uri in REQUIRED_EXT_URIS
    ]
    card = _make_card(extensions)
    validate_extensions(card)  # 不抛出异常

def test_validate_fails_when_extension_missing():
    extensions = [
        AgentExtension(uri=REQUIRED_EXT_URIS[0], required=True),
        AgentExtension(uri=REQUIRED_EXT_URIS[1], required=True),
    ]
    card = _make_card(extensions)
    with pytest.raises(ExtensionNegotiationError) as exc:
        validate_extensions(card)
    assert REQUIRED_EXT_URIS[2] in str(exc.value)

def test_validate_fails_when_extension_not_required():
    extensions = [
        AgentExtension(uri=REQUIRED_EXT_URIS[0], required=True),
        AgentExtension(uri=REQUIRED_EXT_URIS[1], required=False),
        AgentExtension(uri=REQUIRED_EXT_URIS[2], required=True),
    ]
    card = _make_card(extensions)
    with pytest.raises(ExtensionNegotiationError) as exc:
        validate_extensions(card)
    assert REQUIRED_EXT_URIS[1] in str(exc.value)

def test_validate_fails_when_no_extensions():
    card = _make_card(None)
    with pytest.raises(ExtensionNegotiationError):
        validate_extensions(card)
