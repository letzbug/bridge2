"""Mistral Le Chat (chat.mistral.ai).

Markup unknown at development time: generic, low-confidence candidates only.
Status: REQUIRES LIVE VALIDATION – expect to configure selectors locally.
"""

from __future__ import annotations

from .selector_adapter import SelectorAdapter


class MistralAdapter(SelectorAdapter):
    """Independent adapter for provider id 'mistral'.

    Behaviour is driven by config/providers.json (plus local overrides); override
    methods here for provider-specific extraction or completion logic.
    """

    provider_id = "mistral"
