"""Transfer templates.

Placeholders use the square-bracket syntax from the specification:

    [speaker] [destination] [round] [turn] [topic] [host] [guest] [original_message]

The message text is inserted LAST and is never scanned for placeholders, so an
AI response that contains "[speaker]" or "{settings}" stays exactly as written.
"""

from __future__ import annotations

MESSAGE_PLACEHOLDER = "[original_message]"
ATTRIBUTED_TEMPLATE = "Message from [speaker]:\n\n[original_message]"
RAW_TEMPLATE = "[original_message]"
DEFAULT_HUMAN_TEMPLATE = "[original_message]"
DEFAULT_INITIAL_PROMPT = (
    "Hello [recipient]. You are about to have a conversation with another AI assistant, [other]. "
    "A human researcher relays the messages between you with a research tool, and every relayed "
    "message is labelled with its sender.\n\n"
    "Research topic: [topic]\n\n"
    "Please open the conversation with a first thought or question for [other]."
)

KNOWN_PLACEHOLDERS = ("[speaker]", "[destination]", "[round]", "[turn]", "[topic]", "[host]", "[guest]",
                      "[recipient]", "[other]")


class TemplateError(ValueError):
    pass


def validate_transfer_template(template: str) -> None:
    if MESSAGE_PLACEHOLDER not in template:
        raise TemplateError("A transfer template must contain [original_message].")
    if template.count(MESSAGE_PLACEHOLDER) > 1:
        raise TemplateError("[original_message] may appear only once.")


def _subst(fragment: str, values: dict[str, object]) -> str:
    for key, val in values.items():
        fragment = fragment.replace(f"[{key}]", str(val))
    return fragment


def render_transfer(template: str, message: str, **values: object) -> str:
    """Render *template*, inserting *message* verbatim."""
    if MESSAGE_PLACEHOLDER not in template:
        template = template.rstrip() + "\n\n" + MESSAGE_PLACEHOLDER
    before, _, after = template.partition(MESSAGE_PLACEHOLDER)
    return _subst(before, values) + message + _subst(after, values)


def render_prompt(template: str, **values: object) -> str:
    """Render a prompt template that has no message slot (e.g. the initial prompt)."""
    return _subst(template, values)
