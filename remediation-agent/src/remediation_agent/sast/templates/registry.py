"""Template registry: the curated, exact-rule-id fix templates, in order.

`TEMPLATES` is a list, not a dict keyed by rule id, since multiple templates
could in principle target variations of the same rule id later (e.g. a
stricter/looser variant); `get()` iterates and returns the first whose
`applies_to` returns true.
"""
from __future__ import annotations

from typing import Any

from .base import RuleTemplate
from .dotnet_insecure_deserialization import DotNetInsecureDeserializationTemplate

TEMPLATES: list[RuleTemplate] = [
    DotNetInsecureDeserializationTemplate(),
]


def get(finding: dict[str, Any]) -> RuleTemplate | None:
    for template in TEMPLATES:
        if template.applies_to(finding):
            return template
    return None
