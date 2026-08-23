from __future__ import annotations

from remediation_agent.grouping import group_findings_into_units


def _finding(**overrides) -> dict:
    base = {
        "id": "CVE-1",
        "severity": "HIGH",
        "category": "SCA",
        "file": "src/a.csproj",
        "component": "Newtonsoft.Json",
        "fixed_version": "13.0.3",
        "risk": {"score": 50.0},
    }
    base.update(overrides)
    return base


def _settings(severity=None, scope=None) -> dict:
    return {
        "severity": severity or [],
        "scope": scope or {},
        "gates": {"build": "", "test": ""},
    }


def test_severity_filter_drops_unlisted_severities():
    findings = [_finding(id="CVE-low", severity="LOW"), _finding(id="CVE-high", severity="HIGH")]
    units = group_findings_into_units(findings, _settings(severity=["HIGH", "CRITICAL"]))
    ids = [f["id"] for unit in units for f in unit["findings"]]
    assert ids == ["CVE-high"]


def test_empty_severity_list_means_no_filter():
    findings = [_finding(severity="LOW"), _finding(id="CVE-2", severity="INFO")]
    units = group_findings_into_units(findings, _settings(severity=[]))
    ids = {f["id"] for unit in units for f in unit["findings"]}
    assert ids == {"CVE-1", "CVE-2"}


def test_scope_allow_restricts_to_matching_paths():
    findings = [
        _finding(id="CVE-in", file="src/keep.csproj"),
        _finding(id="CVE-out", file="vendor/skip.csproj"),
    ]
    units = group_findings_into_units(findings, _settings(scope={"allow": ["src/**"]}))
    ids = [f["id"] for unit in units for f in unit["findings"]]
    assert ids == ["CVE-in"]


def test_empty_allow_list_allows_everything_not_denied():
    findings = [_finding(id="CVE-1", file="anywhere/thing.csproj")]
    units = group_findings_into_units(findings, _settings(scope={"allow": [], "deny": []}))
    ids = [f["id"] for unit in units for f in unit["findings"]]
    assert ids == ["CVE-1"]


def test_deny_wins_even_when_allow_also_matches():
    findings = [_finding(id="CVE-1", file="src/skip.csproj")]
    settings = _settings(scope={"allow": ["src/**"], "deny": ["src/skip.csproj"]})
    units = group_findings_into_units(findings, settings)
    assert units == []


def test_groups_by_category_and_component():
    findings = [
        _finding(id="CVE-1", component="Newtonsoft.Json"),
        _finding(id="CVE-2", component="Newtonsoft.Json"),
        _finding(id="CVE-3", component="OtherLib"),
    ]
    units = group_findings_into_units(findings, _settings())
    assert len(units) == 2
    sizes = sorted(len(unit["findings"]) for unit in units)
    assert sizes == [1, 2]


def test_groups_by_file_when_no_component():
    findings = [
        _finding(id="CVE-1", category="SAST", component=None, file="src/a.py"),
        _finding(id="CVE-2", category="SAST", component=None, file="src/b.py"),
    ]
    units = group_findings_into_units(findings, _settings())
    assert len(units) == 2
    assert {unit["file"] for unit in units} == {"src/a.py", "src/b.py"}


def test_unit_id_is_stable_across_calls():
    findings = [_finding()]
    units_a = group_findings_into_units(findings, _settings())
    units_b = group_findings_into_units(findings, _settings())
    assert units_a[0]["unit_id"] == units_b[0]["unit_id"]
    assert len(units_a[0]["unit_id"]) == 12


def test_units_sorted_by_descending_max_risk_score():
    findings = [
        _finding(id="CVE-low", component="LowRisk", risk={"score": 10.0}),
        _finding(id="CVE-high", component="HighRisk", risk={"score": 90.0}),
    ]
    units = group_findings_into_units(findings, _settings())
    assert [unit["component"] for unit in units] == ["HighRisk", "LowRisk"]


def test_missing_risk_score_defaults_to_zero_and_sorts_last():
    findings = [
        _finding(id="CVE-no-risk", component="NoRisk", risk={}),
        _finding(id="CVE-has-risk", component="HasRisk", risk={"score": 5.0}),
    ]
    units = group_findings_into_units(findings, _settings())
    assert [unit["component"] for unit in units] == ["HasRisk", "NoRisk"]
