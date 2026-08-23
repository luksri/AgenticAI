""".NET ecosystem adapter: NuGet via .csproj, Directory.Packages.props, packages.config.

Handles both self-closing (``<PackageReference Include="X" Version="Y" />``)
and expanded (``<PackageReference Include="X"><Version>Y</Version></PackageReference>``)
forms, attribute-order tolerant, without a full XML parser -- regexes here are
scoped to a single well-formed tag/block, not arbitrary XML.
"""
from __future__ import annotations

import re
from typing import Any

from s17code.coding.edit import EditLedger, apply_edit, read_code
from s17code.coding.search import glob_files, grep_code
from s17code.coding.workspace import Workspace

from .base import FixNotFoundError, split_gate_command


def _iter_xml_tags(text: str, tag: str) -> list[str]:
    """Every well-formed `<tag ...>` occurrence, self-closing or expanded."""
    pattern = re.compile(rf"<{tag}\b[^>]*?(?:/>|>.*?</{tag}>)", re.IGNORECASE | re.DOTALL)
    return [m.group(0) for m in pattern.finditer(text)]


def _matches_component(tag_text: str, attr: str, component: str) -> bool:
    return re.search(rf'{attr}\s*=\s*"{re.escape(component)}"', tag_text, re.IGNORECASE) is not None


def _extract_attr_version(tag_text: str, attr: str = "Version") -> str | None:
    match = re.search(rf'{attr}\s*=\s*"([^"]+)"', tag_text, re.IGNORECASE)
    return match.group(1) if match else None


def _extract_element_version(tag_text: str, element: str = "Version") -> str | None:
    match = re.search(rf"<{element}>\s*([^<]+?)\s*</{element}>", tag_text, re.IGNORECASE)
    return match.group(1) if match else None


class DotNetAdapter:
    name = "dotnet"

    def detect(self, workspace: Workspace) -> bool:
        for pattern in ("*.csproj", "packages.config", "Directory.Packages.props"):
            if glob_files(workspace, pattern, limit=1)["files"]:
                return True
        return False

    def locate_component(self, workspace: Workspace, finding: dict[str, Any]) -> list[dict[str, Any]]:
        component = finding.get("component")
        if not component:
            return []
        locations: list[dict[str, Any]] = []
        locations.extend(self._locate_csproj(workspace, component))
        locations.extend(self._locate_directory_packages_props(workspace, component))
        locations.extend(self._locate_packages_config(workspace, component))
        return locations

    def _locate_csproj(self, workspace: Workspace, component: str) -> list[dict[str, Any]]:
        locations: list[dict[str, Any]] = []
        grep = grep_code(
            workspace,
            rf'PackageReference[^>]*Include\s*=\s*"{re.escape(component)}"',
            path_glob="*.csproj",
            ignore_case=True,
            limit=100,
        )
        for rel in sorted({m["path"] for m in grep["matches"]}):
            text = workspace.resolve(rel).read_text(encoding="utf-8")
            for tag_text in _iter_xml_tags(text, "PackageReference"):
                if not _matches_component(tag_text, "Include", component):
                    continue
                version = _extract_attr_version(tag_text, "Version")
                kind = "csproj_packagereference_selfclosing"
                if version is None:
                    version = _extract_element_version(tag_text, "Version")
                    kind = "csproj_packagereference_expanded"
                if version is None:
                    continue
                locations.append({
                    "file": rel,
                    "pattern_kind": kind,
                    "old_version": version,
                    "anchor": tag_text,
                })
        return locations

    def _locate_directory_packages_props(self, workspace: Workspace, component: str) -> list[dict[str, Any]]:
        locations: list[dict[str, Any]] = []
        grep = grep_code(
            workspace,
            rf'PackageVersion[^>]*Include\s*=\s*"{re.escape(component)}"',
            path_glob="Directory.Packages.props",
            ignore_case=True,
            limit=100,
        )
        for rel in sorted({m["path"] for m in grep["matches"]}):
            text = workspace.resolve(rel).read_text(encoding="utf-8")
            for tag_text in _iter_xml_tags(text, "PackageVersion"):
                if not _matches_component(tag_text, "Include", component):
                    continue
                version = _extract_attr_version(tag_text, "Version")
                if version is None:
                    continue
                locations.append({
                    "file": rel,
                    "pattern_kind": "directory_packages_props",
                    "old_version": version,
                    "anchor": tag_text,
                })
        return locations

    def _locate_packages_config(self, workspace: Workspace, component: str) -> list[dict[str, Any]]:
        locations: list[dict[str, Any]] = []
        grep = grep_code(
            workspace,
            rf'package[^>]*id\s*=\s*"{re.escape(component)}"',
            path_glob="packages.config",
            ignore_case=True,
            limit=100,
        )
        for rel in sorted({m["path"] for m in grep["matches"]}):
            text = workspace.resolve(rel).read_text(encoding="utf-8")
            for tag_text in _iter_xml_tags(text, "package"):
                if not _matches_component(tag_text, "id", component):
                    continue
                version = _extract_attr_version(tag_text, "version")
                if version is None:
                    continue
                locations.append({
                    "file": rel,
                    "pattern_kind": "packages_config",
                    "old_version": version,
                    "anchor": tag_text,
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
        # Read-before-edit: register this file as read for THIS ledger before
        # apply_edit is allowed to touch it (s17code.coding.edit enforces this).
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
            # re-run against) the target version. Checked before attempting
            # the regex substitution, which would otherwise produce a
            # same-text "new_anchor == anchor" result indistinguishable from
            # a genuine anchor-pattern mismatch below.
            return {
                "changed_files": [],
                "old_version": old_version,
                "new_version": fixed_version,
                "already_satisfied": True,
            }

        kind = location.get("pattern_kind", "")
        if kind == "csproj_packagereference_expanded":
            new_anchor, count = re.subn(
                rf"(<Version>\s*){re.escape(old_version)}(\s*</Version>)",
                rf"\g<1>{fixed_version}\g<2>",
                anchor,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            new_anchor, count = re.subn(
                rf'((?:Version|version)\s*=\s*"){re.escape(old_version)}(")',
                rf"\g<1>{fixed_version}\g<2>",
                anchor,
                count=1,
                flags=re.IGNORECASE,
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
        return ("dotnet",)
