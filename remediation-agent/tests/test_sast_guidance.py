from __future__ import annotations

from remediation_agent.sast.guidance import guidance_for


def test_guidance_for_known_cwe_returns_curated_text():
    text = guidance_for(["CWE-502"])
    assert text is not None
    assert "TypeNameHandling" in text


def test_guidance_for_unknown_cwe_returns_none():
    assert guidance_for(["CWE-9999-does-not-exist"]) is None


def test_guidance_for_empty_list_returns_none():
    assert guidance_for([]) is None


def test_guidance_for_mixed_known_and_unknown_returns_only_known():
    text = guidance_for(["CWE-9999-does-not-exist", "CWE-502"])
    assert text is not None
    assert "TypeNameHandling" in text
