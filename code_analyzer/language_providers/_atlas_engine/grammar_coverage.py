"""Explicit grammar coverage: only generic statement envelopes are implemented."""

from __future__ import annotations

from typing import Any

_GRAMMAR_FAMILIES = (
    "program_identity",
    "statement_boundaries",
    "comments_and_literals",
    "declarations",
    "procedures_and_groups",
    "stimulus_and_signals",
    "measurements_and_units",
    "limits_and_evaluation",
    "equipment_resources",
    "connection_and_setup",
    "control_flow",
    "vendor_extensions",
)


def grammar_register() -> list[dict[str, Any]]:
    """Describe conservative syntax capabilities without claiming ATLAS validity."""
    return [
        {
            "family": name,
            "status": (
                "structural_envelope_only" if name == "statement_boundaries" else (
                    "generic_tokenization_only" if name == "comments_and_literals"
                    else "not_implemented"
                )
            ),
            "source_evidence": None,
        }
        for name in _GRAMMAR_FAMILIES
    ]
