"""Google Gemini (gemini.google.com).

Gemini renders responses in custom elements (model-response / message-content) and uses a Quill
editor (rich-textarea .ql-editor) as input. Google may refuse sign-in in automated browsers; this
adapter does not work around that – use the standard Firefox backend + clipboard mode instead.
Status: REQUIRES LIVE VALIDATION.
"""

from __future__ import annotations

from .selector_adapter import SelectorAdapter


class GeminiAdapter(SelectorAdapter):
    """Independent adapter for provider id 'gemini'.

    Behaviour is driven by config/providers.json (plus local overrides); override
    methods here for provider-specific extraction or completion logic.
    """

    provider_id = "gemini"
