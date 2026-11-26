"""ChatGPT (chatgpt.com) – host adapter for Cameron.

ChatGPT exposes semantic attributes (data-message-author-role, data-message-id, data-testid on
the send/stop buttons), so message identity and generation status are usually detectable.
Status: REQUIRES LIVE VALIDATION – selectors are candidates, not verified against the live site.
"""

from __future__ import annotations

from .selector_adapter import SelectorAdapter


class ChatGPTAdapter(SelectorAdapter):
    """Independent adapter for provider id 'chatgpt'.

    Behaviour is driven by config/providers.json (plus local overrides); override
    methods here for provider-specific extraction or completion logic once the
    live markup has been validated.
    """

    provider_id = "chatgpt"
