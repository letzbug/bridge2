"""Adapter exception hierarchy."""

from __future__ import annotations


class AdapterError(RuntimeError):
    """Generic adapter failure.

    submission_attempted is True when the failure happened after the adapter
    may already have submitted the message (the engine then asks the operator
    to verify instead of resending).
    """

    code = "adapter_error"

    def __init__(self, message: str, *, submission_attempted: bool = False) -> None:
        super().__init__(message)
        self.submission_attempted = submission_attempted


class BrowserClosedError(AdapterError):
    code = "browser_closed"


class AuthenticationRequiredError(AdapterError):
    code = "authentication_required"


class ElementNotFoundError(AdapterError):
    code = "element_not_found"


class MessageTooLongError(AdapterError):
    code = "message_too_long"


class ParticipantBusyError(AdapterError):
    code = "participant_busy"


class RateLimitedError(AdapterError):
    code = "rate_limited"


class ResponseTimeoutError(AdapterError):
    code = "timeout"

    def __init__(self, message: str, *, partial_text: str | None = None) -> None:
        super().__init__(message)
        self.partial_text = partial_text


class SubmissionBlockedError(AdapterError):
    """Raised when the send gate is closed (emergency stop)."""

    code = "submission_blocked"


class CapabilityNotSupportedError(AdapterError):
    code = "not_supported"


class DependencyMissingError(AdapterError):
    code = "dependency_missing"
