"""Custom AI website.

Uses generic selector candidates until provider-specific ones are configured locally.
Status: REQUIRES CONFIGURATION AND LIVE VALIDATION.
"""

from __future__ import annotations

from .selector_adapter import SelectorAdapter


class CustomAdapter(SelectorAdapter):
    """Independent adapter for provider id 'custom'.

    Behaviour is driven by config/providers.json (plus local overrides); override
    methods here for provider-specific extraction or completion logic.
    """

    provider_id = "custom"
