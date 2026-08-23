"""CWE-keyed curated guidance for the SAST LLM-fix fallback path.

The orchestrator's `enrichment` field carries descriptive CWE metadata only,
no fix guidance -- the agent needs its own curated per-vulnerability-class
cheat sheet to hand the LLM when no deterministic template applies. This is
exactly session-17's "skill" mechanism (a markdown file, no code, no access
to any capability/authority system -- see `s17code/skills/manager.py`'s own
docstring), reused here by import only, the same reuse pattern as
`s17code.coding.*`.

`CWE_TO_SKILL` is the only place a new CWE class needs registering: add one
dict entry plus one new `SKILL.md` folder under `sast/skills/`, nothing else
changes.
"""
from __future__ import annotations

from pathlib import Path

from s17code.skills import SkillManager

# Built once at import time, pointing at the `sast/skills/` directory shipped
# alongside this module. A missing/unreadable skills directory is recorded in
# `_MANAGER.errors` by SkillManager.discover itself, never raised -- so a
# broken or absent skills tree degrades `guidance_for` to always returning
# None rather than breaking the SAST strategy.
_MANAGER = SkillManager.discover(Path(__file__).parent / "skills")

# CWE id -> skill name (the skill's own `name` frontmatter field, not its
# folder name, though they match here for readability).
CWE_TO_SKILL: dict[str, str] = {
    "CWE-502": "cwe-502-insecure-deserialization",
}


def guidance_for(cwe_ids: list[str]) -> str | None:
    """Curated guidance text for the given CWE ids, or None if none apply.

    Never raises: an unknown CWE id, a CWE with no mapped skill, or a mapped
    skill that failed to load are all skipped cleanly. Returns `.instructions`
    (the skill body, without the "## Skill: ..." manifest header) for each
    matched skill, since this module composes its own prompt rather than
    injecting into a planner's system prompt the way session-17 does.
    Multiple matches are concatenated with a blank line between. Returns
    `None` (never `""`) when nothing matches, so callers can cleanly say "no
    curated guidance available" and proceed with a generic prompt.
    """
    texts: list[str] = []
    for cwe_id in cwe_ids or []:
        skill_name = CWE_TO_SKILL.get(cwe_id)
        if not skill_name:
            continue
        skill = _MANAGER.get(skill_name)
        if skill is None:
            continue
        texts.append(skill.instructions)

    if not texts:
        return None
    return "\n\n".join(texts)
