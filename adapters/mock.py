"""Local mock chat page shipped in assets/mock_chat.html.

Not an AI. Used to validate the complete browser pipeline (input, send, streaming, completion
detection, stop control) offline. Status: VALIDATED by the automated test-suite.
"""

from __future__ import annotations

from .selector_adapter import SelectorAdapter


class MockPageAdapter(SelectorAdapter):
    """Independent adapter for provider id 'mock'.

    Behaviour is driven by config/providers.json (plus local overrides); override
    methods here for provider-specific extraction or completion logic.
    """

    provider_id = "mock"
