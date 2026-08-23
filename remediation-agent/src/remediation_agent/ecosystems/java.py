"""Java ecosystem adapter: Maven pom.xml and Gradle build.gradle[.kts].

Maven: `component` is `groupId:artifactId` or just `artifactId`; a
`<dependency>` block's `<artifactId>` and `<version>` elements are anchored
together (a bare `<version>X</version>` is almost never unique across a
pom.xml with many dependencies).

Gradle: only a literal `component:version` string inside the build file is
matched (e.g. `implementation("group:artifact:1.2.3")`), matching generically
on `component:` followed by a version-looking token rather than hardcoding
every configuration name (`implementation`, `api`, `testImplementation`, ...).
A version-catalog-only reference (`libs.someLib`) with no literal version
string in the build file is NOT guessed at -- it yields no location, which the
caller treats as `decision="not_found"`.
"""
from __future__ import annotations

import re
from typing import Any

from s17code.coding.edit import EditLedger, apply_edit, read_code
from s17code.coding.search import glob_files, grep_code
from s17code.coding.workspace import Workspace

from .base import FixNotFoundError, split_gate_command

_DEPENDENCY_BLOCK_RE = re.compile(r"<dependency\b.*?</dependency>", re.IGNORECASE | re.DOTALL)
_VERSION_TOKEN_RE = r"[0-9][A-Za-z0-9_.\-]*"


def _artifact_id(component: str) -> str:
    """`groupId:artifactId` -> `artifactId`; a bare artifactId passes through."""
    return component.split(":")[-1] if component else component


class JavaAdapter:
    name = "java"

    def detect(self, workspace: Workspace) -> bool:
        for pattern in ("pom.xml", "build.gradle", "build.gradle.kts"):
            if glob_files(workspace, pattern, limit=1)["files"]:
                return True
        return False

    def locate_component(self, workspace: Workspace, finding: dict[str, Any]) -> list[dict[str, Any]]:
        component = finding.get("component")
        if not component:
            return []
        locations: list[dict[str, Any]] = []
        locations.extend(self._locate_maven(workspace, component))
        locations.extend(self._locate_gradle(workspace, component))
        return locations

    def _locate_maven(self, workspace: Workspace, component: str) -> list[dict[str, Any]]:
        artifact_id = _artifact_id(component)
        if not artifact_id:
            return []
        locations: list[dict[str, Any]] = []
        grep = grep_code(
            workspace,
            rf"<artifactId>\s*{re.escape(artifact_id)}\s*</artifactId>",
            path_glob="pom.xml",
            limit=100,
        )
        artifact_re = re.compile(rf"<artifactId>\s*{re.escape(artifact_id)}\s*</artifactId>")
        version_re = re.compile(r"<version>\s*([^<]+?)\s*</version>")
        for rel in sorted({m["path"] for m in grep["matches"]}):
            text = workspace.resolve(rel).read_text(encoding="utf-8")
            for block_match in _DEPENDENCY_BLOCK_RE.finditer(text):
                block_text = block_match.group(0)
                artifact_match = artifact_re.search(block_text)
                if not artifact_match:
                    continue
                version_match = version_re.search(block_text)
                if not version_match:
                    continue
                start = min(artifact_match.start(), version_match.start())
                end = max(artifact_match.end(), version_match.end())
                anchor = block_text[start:end]
                locations.append({
                    "file": rel,
                    "pattern_kind": "pom_dependency",
                    "old_version": version_match.group(1),
                    "anchor": anchor,
                })
        return locations

    def _locate_gradle(self, workspace: Workspace, component: str) -> list[dict[str, Any]]:
        locations: list[dict[str, Any]] = []
        literal_re = re.compile(rf"{re.escape(component)}:({_VERSION_TOKEN_RE})")
        for filename in ("build.gradle", "build.gradle.kts"):
            grep = grep_code(
                workspace,
                rf"{re.escape(component)}:{_VERSION_TOKEN_RE}",
                path_glob=filename,
                limit=100,
            )
            for rel in sorted({m["path"] for m in grep["matches"]}):
                text = workspace.resolve(rel).read_text(encoding="utf-8")
                for match in literal_re.finditer(text):
                    old_version = match.group(1)
                    line_start = text.rfind("\n", 0, match.start()) + 1
                    line_end = text.find("\n", match.end())
                    if line_end == -1:
                        line_end = len(text)
                    anchor = text[line_start:line_end]
                    locations.append({
                        "file": rel,
                        "pattern_kind": "gradle_dependency",
                        "old_version": old_version,
                        "anchor": anchor,
                    })
        return locations

    def apply_version_fix(
        self,
        workspace: Workspace,
        ledger: EditLedger,
        finding: dict[str, Any],
        location: dict[str, Any],
    ) -> dict[str, Any]:
        rel = location.get("file")
        if not rel:
            raise FixNotFoundError("location has no 'file'")
        read_code(workspace, ledger, rel)

        anchor = location.get("anchor")
        old_version = location.get("old_version")
        fixed_version = finding.get("fixed_version")
        if not anchor or not old_version:
            raise FixNotFoundError(f"no anchor recorded for component in {rel}")
        if not fixed_version:
            raise FixNotFoundError(f"finding has no fixed_version for {finding.get('component')!r}")

        if old_version == fixed_version:
            # Not a failure: the component is already at (or the finding was
            # re-run against) the target version -- see dotnet.py's identical
            # check for why this has to be caught before the substitution
            # below rather than folded into the "anchor didn't match" case.
            return {
                "changed_files": [],
                "old_version": old_version,
                "new_version": fixed_version,
                "already_satisfied": True,
            }

        kind = location.get("pattern_kind", "")
        if kind == "pom_dependency":
            new_anchor, count = re.subn(
                rf"(<version>\s*){re.escape(old_version)}(\s*</version>)",
                rf"\g<1>{fixed_version}\g<2>",
                anchor,
                count=1,
            )
        else:  # gradle_dependency
            new_anchor, count = re.subn(
                rf"(:){re.escape(old_version)}\b",
                rf"\g<1>{fixed_version}",
                anchor,
                count=1,
            )
        if count == 0 or new_anchor == anchor:
            raise FixNotFoundError(
                f"could not rewrite version {old_version!r} -> {fixed_version!r} in anchor for {rel}"
            )

        apply_edit(workspace, ledger, rel, old_string=anchor, new_string=new_anchor)
        return {"changed_files": [rel], "old_version": old_version, "new_version": fixed_version}

    def build_command(self, settings: dict[str, Any]) -> list[list[str]] | None:
        gate = (settings.get("gates") or {}).get("build", "")
        return split_gate_command(gate)

    def test_command(self, settings: dict[str, Any]) -> list[list[str]] | None:
        gate = (settings.get("gates") or {}).get("test", "")
        return split_gate_command(gate)

    def allowed_commands(self) -> tuple[str, ...]:
        return ("mvn", "gradle", "gradlew", "java")
