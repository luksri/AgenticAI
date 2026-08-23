"""Tests for `sast.locate.locate_by_line`, especially the snippet-drift guard:
a finding's `line` is a position captured whenever the orchestrator's scan
ran, and can silently point at the wrong code if the file has since changed
above that point. `finding["snippet"]`, when present, is cross-checked
against what's actually at that line before it's ever handed to a fixer.
"""
from __future__ import annotations

from remediation_agent.sast.locate import locate_by_line

REL_PATH = "src/Controllers/ProductController.cs"
VULNERABLE_LINE_NO = 9
VULNERABLE_SNIPPET = "var model = JsonConvert.DeserializeObject<ProductModel>(data);"


def _finding(*, line: int | None = VULNERABLE_LINE_NO, snippet: str | None = VULNERABLE_SNIPPET) -> dict:
    finding: dict = {"file": REL_PATH}
    if line is not None:
        finding["line"] = line
    if snippet is not None:
        finding["snippet"] = snippet
    return finding


def test_no_snippet_trusts_the_line_number_unchanged(dotnet_sast_workspace):
    # Back-compat: a finding with no snippet at all has nothing to verify
    # against, so this falls back to the original line-trusting behavior.
    finding = _finding(snippet=None)
    locations = locate_by_line(dotnet_sast_workspace, finding)
    assert len(locations) == 1
    assert locations[0]["line"] == VULNERABLE_LINE_NO
    assert "line_drifted" not in locations[0]


def test_snippet_matches_current_line_no_drift(dotnet_sast_workspace):
    locations = locate_by_line(dotnet_sast_workspace, _finding())
    assert len(locations) == 1
    assert locations[0]["line"] == VULNERABLE_LINE_NO
    assert locations[0]["text"].strip() == VULNERABLE_SNIPPET
    assert "line_drifted" not in locations[0]


def test_snippet_matches_despite_whitespace_difference(dotnet_sast_workspace):
    # The payload's snippet is commonly trimmed/reformatted relative to the
    # file's actual indentation -- normalization must not treat that as drift.
    finding = _finding(snippet=f"   {VULNERABLE_SNIPPET}   ")
    locations = locate_by_line(dotnet_sast_workspace, finding)
    assert len(locations) == 1
    assert locations[0]["line"] == VULNERABLE_LINE_NO
    assert "line_drifted" not in locations[0]


def test_relocates_when_lines_shifted_above(dotnet_sast_workspace):
    path = dotnet_sast_workspace.resolve(REL_PATH)
    text = path.read_text(encoding="utf-8")
    # Insert three new lines above the vulnerable one -- the real code is
    # now three lines further down than the (stale) finding claims.
    text = text.replace(
        "public void UpdateProduct(string data)\n",
        "public void UpdateProduct(string data)\n"
        "        {\n"
        "            // added by an unrelated later commit\n"
        "        }\n"
        "\n"
        "        public void UpdateProductV2(string data)\n",
        1,
    )
    path.write_text(text, encoding="utf-8")

    locations = locate_by_line(dotnet_sast_workspace, _finding())  # still claims line 9

    assert len(locations) == 1
    location = locations[0]
    assert location["line"] != VULNERABLE_LINE_NO
    assert location["text"].strip() == VULNERABLE_SNIPPET
    assert location["line_drifted"] is True


def test_returns_empty_when_snippet_genuinely_gone(dotnet_sast_workspace):
    path = dotnet_sast_workspace.resolve(REL_PATH)
    text = path.read_text(encoding="utf-8")
    text = text.replace(VULNERABLE_SNIPPET, "var model = SafeParse(data);")
    path.write_text(text, encoding="utf-8")

    locations = locate_by_line(dotnet_sast_workspace, _finding())  # still claims line 9, old snippet

    assert locations == []


def test_returns_empty_when_snippet_is_ambiguous(dotnet_sast_workspace):
    path = dotnet_sast_workspace.resolve(REL_PATH)
    text = path.read_text(encoding="utf-8")
    # The original line 9 no longer matches (forcing a search), and the
    # snippet now appears at two *other* locations -- the search itself is
    # ambiguous, which is different from test_relocates_when_lines_shifted_above
    # (search finds exactly one candidate). Don't guess which one the
    # finding meant, the same "ambiguous anchor" stance apply_edit takes
    # elsewhere in this project.
    text = text.replace(VULNERABLE_SNIPPET, "var model = SafeParse(data);")  # line 9 no longer matches
    text = text.replace(
        "        }\n    }\n}\n",
        f"        }}\n\n        public void UpdateProductAgain(string data)\n"
        f"        {{\n            {VULNERABLE_SNIPPET}\n        }}\n\n"
        f"        public void UpdateProductAgainAgain(string data)\n"
        f"        {{\n            {VULNERABLE_SNIPPET}\n        }}\n    }}\n}}\n",
    )
    path.write_text(text, encoding="utf-8")

    locations = locate_by_line(dotnet_sast_workspace, _finding())  # still claims line 9

    assert locations == []


def test_returns_empty_when_line_out_of_bounds(dotnet_sast_workspace):
    assert locate_by_line(dotnet_sast_workspace, _finding(line=9999)) == []


def test_returns_empty_when_file_missing(dotnet_sast_workspace):
    finding = _finding()
    finding["file"] = "src/Controllers/DoesNotExist.cs"
    assert locate_by_line(dotnet_sast_workspace, finding) == []


def test_returns_empty_without_file_or_line(dotnet_sast_workspace):
    assert locate_by_line(dotnet_sast_workspace, {"snippet": VULNERABLE_SNIPPET}) == []
    assert locate_by_line(dotnet_sast_workspace, {"file": REL_PATH}) == []
