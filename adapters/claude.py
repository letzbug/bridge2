"""Anthropic Claude (claude.ai).

Claude marks streaming messages with data-is-streaming="true", which is used as generation signal.
The input is a ProseMirror contenteditable. Anthropic's consumer terms restrict automated access –
the clipboard mode is the recommended integration.
Status: REQUIRES LIVE VALIDATION.
"""

from __future__ import annotations

from .selector_adapter import SelectorAdapter


class ClaudeAdapter(SelectorAdapter):
    """Independent adapter for provider id 'claude'.

    Behaviour is driven by config/providers.json (plus local overrides); override
    methods here for provider-specific extraction or completion logic.
    """

    provider_id = "claude"
