from __future__ import annotations

import pytest
from s17code.coding.edit import EditError, EditLedger

from remediation_agent.sast.templates.base import TemplateNotApplicableError
from remediation_agent.sast.templates.dotnet_insecure_deserialization import (
    DotNetInsecureDeserializationTemplate,
)
from remediation_agent.sast.templates.registry import get as get_template

RULE_ID = "csharp.lang.security.insecure-deserialization.insecure-deserialization"
REL_PATH = "src/Controllers/ProductController.cs"
VULNERABLE_LINE_NO = 9


def _finding(rule_id: str = RULE_ID) -> dict:
    return {
        "id": rule_id,
        "tool": "semgrep",
        "category": "SAST",
        "lane": "code",
        "file": REL_PATH,
        "severity": "HIGH",
        "title": "Insecure deserialization detected",
        "line": VULNERABLE_LINE_NO,
        "snippet": "var model = JsonConvert.DeserializeObject<ProductModel>(data);",
        "cwe_ids": ["CWE-502"],
        "correlated": True,
    }


def _location(dotnet_sast_workspace) -> dict:
    # Reads whatever is currently on disk at the flagged line -- tests that
    # mutate the fixture file before calling this (e.g. to add a second
    # argument) rely on that.
    text = dotnet_sast_workspace.resolve(REL_PATH).read_text(encoding="utf-8").splitlines()
    line_text = text[VULNERABLE_LINE_NO - 1]
    return {"file": REL_PATH, "pattern_kind": "sast_line", "line": VULNERABLE_LINE_NO, "text": line_text}


def test_location_helper_sanity_check(dotnet_sast_workspace):
    location = _location(dotnet_sast_workspace)
    assert "JsonConvert.DeserializeObject<ProductModel>(data)" in location["text"]


def test_registry_matches_exact_rule_id():
    template = get_template(_finding())
    assert isinstance(template, DotNetInsecureDeserializationTemplate)


def test_registry_returns_none_for_unknown_rule_id():
    assert get_template(_finding(rule_id="some.other.rule.id")) is None


def test_template_rewrites_vulnerable_line(dotnet_sast_workspace):
    ledger = EditLedger()
    finding = _finding()
    location = _location(dotnet_sast_workspace)

    template = DotNetInsecureDeserializationTemplate()
    result = template.apply(dotnet_sast_workspace, ledger, finding, location)

    assert result["supported"] is True
    assert result["changed_files"] == [REL_PATH]
    assert result["fix_tier"] == "template"

    updated = dotnet_sast_workspace.resolve(REL_PATH).read_text(encoding="utf-8")
    # The injected safe settings object.
    assert "new JsonSerializerSettings" in updated
    assert "TypeNameHandling.None" in updated
    assert "__remediationSerializerSettings" in updated
    # The original call site, now passing the settings explicitly.
    assert (
        "JsonConvert.DeserializeObject<ProductModel>(data, __remediationSerializerSettings);"
        in updated
    )
    # The surrounding method/class structure is untouched -- still "valid-looking" C#.
    assert "public void UpdateProduct(string data)" in updated
    assert updated.count("{") == updated.count("}")


def test_template_raises_when_call_already_has_settings_argument(dotnet_sast_workspace):
    path = dotnet_sast_workspace.resolve(REL_PATH)
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "JsonConvert.DeserializeObject<ProductModel>(data);",
        "JsonConvert.DeserializeObject<ProductModel>(data, existingSettings);",
    )
    path.write_text(text, encoding="utf-8")

    ledger = EditLedger()
    finding = _finding()
    location = _location(dotnet_sast_workspace)

    template = DotNetInsecureDeserializationTemplate()
    with pytest.raises(TemplateNotApplicableError):
        template.apply(dotnet_sast_workspace, ledger, finding, location)


def test_template_edit_error_propagates_on_ambiguous_anchor(dotnet_sast_workspace):
    # Duplicate the vulnerable line so the anchor text is no longer unique in
    # the file -- apply_edit itself should refuse with EditError, not
    # TemplateNotApplicableError (the pattern DID match, it's just ambiguous
    # which occurrence to rewrite).
    path = dotnet_sast_workspace.resolve(REL_PATH)
    text = path.read_text(encoding="utf-8")
    line = "            var model = JsonConvert.DeserializeObject<ProductModel>(data);"
    duplicated = text.replace(line, line + "\n" + line, 1)
    path.write_text(duplicated, encoding="utf-8")

    ledger = EditLedger()
    finding = _finding()
    location = _location(dotnet_sast_workspace)

    template = DotNetInsecureDeserializationTemplate()
    with pytest.raises(EditError):
        template.apply(dotnet_sast_workspace, ledger, finding, location)
