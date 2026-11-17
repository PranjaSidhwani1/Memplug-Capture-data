"""Validate a proposed memory operation before anything is written."""

from __future__ import annotations

_OPERATIONS = {"ADD", "REPLACE", "MERGE", "NOOP"}
_MIN_CONFIDENCE = 0.55
_MAX_CONTENT = 2000


def normalize_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.casefold().split())


def clip_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def validate_decision(proposal: dict, candidate: dict, retrieved: list[dict]) -> dict:
    """Return one operation the writer is allowed to run.

    Target ids must come from the memories retrieved for this candidate.
    Low confidence, an empty fact, or a replace that does not change the
    text becomes NOOP.
    """
    retrieved_ids = {str(row.get("memory_id") or "") for row in retrieved}
    retrieved_ids.discard("")
    by_id = {str(row.get("memory_id") or ""): normalize_text(row.get("content")) for row in retrieved}
    operation = str(proposal.get("operation") or "").strip().upper()
    if operation not in _OPERATIONS:
        operation = "NOOP"
    confidence = _confidence(proposal.get("confidence"))
    targets = []
    for raw in proposal.get("target_memory_ids") or []:
        memory_id = str(raw or "").strip()
        if memory_id in retrieved_ids and memory_id not in targets:
            targets.append(memory_id)
    content = clip_text(proposal.get("final_content"), _MAX_CONTENT)
    if operation in {"ADD", "REPLACE", "MERGE"} and not content:
        content = clip_text(candidate.get("content"), _MAX_CONTENT)
    if confidence < _MIN_CONFIDENCE:
        operation = "NOOP"
    if operation in {"REPLACE", "MERGE"} and not targets:
        operation = "ADD" if content else "NOOP"
    if operation in {"ADD", "REPLACE", "MERGE"} and not content:
        operation = "NOOP"
    if operation == "REPLACE" and len(targets) == 1 and normalize_text(content) == by_id.get(targets[0], ""):
        operation = "NOOP"
    if operation == "ADD":
        targets = []
    if operation == "NOOP":
        targets = []
        content = ""
    return {
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "operation": operation,
        "target_memory_ids": targets,
        "final_content": content,
        "confidence": confidence,
        "domain": str(candidate.get("domain") or ""),
        "memory_type": str(candidate.get("memory_type") or "fact"),
        "scope": str(candidate.get("scope") or "user"),
        "source_message_ids": list(candidate.get("source_message_ids") or []),
        "candidate_content": clip_text(candidate.get("content"), _MAX_CONTENT),
    }


def align_decisions(candidates: list[dict], proposals: list[dict], retrieved_by_candidate: dict[str, list[dict]]) -> list[dict]:
    by_id = {}
    for proposal in proposals:
        if isinstance(proposal, dict):
            by_id[str(proposal.get("candidate_id") or "")] = proposal
    aligned = []
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        proposal = by_id.get(candidate_id)
        if proposal is None:
            proposal = {
                "candidate_id": candidate_id,
                "operation": "ADD",
                "target_memory_ids": [],
                "final_content": candidate.get("content") or "",
                "confidence": candidate.get("confidence") or 0,
            }
        aligned.append(validate_decision(proposal, candidate, retrieved_by_candidate.get(candidate_id) or []))
    return aligned


def _confidence(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number < 0:
        return 0.0
    if number > 1:
        return 1.0
    return number
