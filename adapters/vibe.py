""""Vibe" – URL and markup configured by the user.

No default URL is shipped because the intended service could not be identified with certainty.
Enter the URL in the guest panel and configure selectors in Settings > Providers.
Status: REQUIRES CONFIGURATION AND LIVE VALIDATION.
"""

from __future__ import annotations

from .selector_adapter import SelectorAdapter


class VibeAdapter(SelectorAdapter):
    """Independent adapter for provider id 'vibe'.

    Behaviour is driven by config/providers.json (plus local overrides); override
    methods here for provider-specific extraction or completion logic.
    """

    provider_id = "vibe"
