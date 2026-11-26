"""Experiment conditions and session comparison metrics.

Metrics are computed only from observed transcript data. Nothing is inferred
about hidden model states or memory activity; user-reported conditions are
shown as user-reported.
"""

from __future__ import annotations

from statistics import mean
from typing import Any

from .transcript import Transcript

#: user-reported experiment variables (the application never changes provider settings)
CONDITION_FIELDS: dict[str, list[str]] = {
    "conversation_context": ["", "existing conversation", "new conversation"],
    "memory_setting": ["", "memory enabled (user-reported)", "memory disabled (user-reported)", "unknown"],
    "transfer_variant": ["", "attributed transfer", "raw transfer"],
    "prompt_variant": [""],
}


def session_metrics(t: Transcript) -> dict[str, Any]:
    responses = t.responses()
    by_role: dict[str, list] = {"host": [], "guest": []}
    for e in responses:
        by_role.setdefault(e.speaker_role, []).append(e)

    def avg(values):
        values = [v for v in values if v is not None]
        return round(mean(values), 1) if values else None

    return {
        "session_id": t.meta.session_id,
        "title": t.meta.title,
        "experiment": t.meta.experiment,
        "condition": t.meta.condition,
        "guest": f"{t.meta.guest_name} ({t.meta.guest_provider})",
        "template_mode": t.meta.template_mode,
        "simulated": t.meta.demo,
        "end_state": t.meta.end_state,
        "completed_rounds": min(len(by_role["host"]), len(by_role["guest"])),
        "host_responses": len(by_role["host"]),
        "guest_responses": len(by_role["guest"]),
        "host_avg_chars": avg([len(e.original_text) for e in by_role["host"]]),
        "guest_avg_chars": avg([len(e.original_text) for e in by_role["guest"]]),
        "host_avg_seconds": avg([e.duration_s for e in by_role["host"]]),
        "guest_avg_seconds": avg([e.duration_s for e in by_role["guest"]]),
        "loop_warnings": sum(1 for e in responses if any(f.startswith("possible_loop") for f in e.flags)),
        "edited_transfers": sum(1 for e in responses if e.edited),
        "human_interventions": sum(1 for e in t.entries if e.kind == "human_intervention"),
        "errors": sum(1 for ev in t.events if ev.level == "error"),
        "user_reported": {k: v.get("value") for k, v in t.meta.facts.items() if v.get("provenance") == "user_reported"},
    }


def compare(transcripts: list[Transcript]) -> list[dict[str, Any]]:
    return [session_metrics(t) for t in transcripts]
