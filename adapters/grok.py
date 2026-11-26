"""xAI Grok (grok.com).

Markup unknown at development time: generic, low-confidence candidates only.
Status: REQUIRES LIVE VALIDATION – expect to configure selectors locally.
"""

from __future__ import annotations

from .selector_adapter import SelectorAdapter


class GrokAdapter(SelectorAdapter):
    """Independent adapter for provider id 'grok'.

    Behaviour is driven by config/providers.json (plus local overrides); override
    methods here for provider-specific extraction or completion logic.
    """

    provider_id = "grok"
