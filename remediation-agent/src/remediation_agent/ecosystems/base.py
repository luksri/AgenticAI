"""The `EcosystemAdapter` contract, plus the shared gate-command parsing rule.

An ecosystem adapter is the one place that knows how a particular language's
dependency manifests are shaped (.csproj, pom.xml, build.gradle, ...). Every
adapter method below is deliberately narrow: locating a component and applying
a version fix never runs a shell, and building a build/test command never
executes one -- it only returns the argv steps another layer (the
`validate_build_test` graph node, built separately) will run via
`s17code.coding.exec.run_command`.
"""
from __future__ import annotations

import shlex
from typing import Any, Protocol, runtime_checkable

from s17code.coding.edit import EditLedger
from s17code.coding.workspace import Workspace


class FixNotFoundError(ValueError):
    """The adapter could not build a safe, unique anchor to apply a version fix.

    Raised by `apply_version_fix` when a location was found by
    `locate_component` but no version string could be safely identified and
    rewritten inside it (e.g. the recorded anchor no longer contains the
    expected old_version, or required fields are missing). Distinct from
    `s17code.coding.edit.EditError`, which signals the anchor was ambiguous
    (not unique) or otherwise malformed once handed to `apply_edit`. Both are
    expected to propagate out of `apply_version_fix` -- turning them into a
    `decision="fix_failed"` is the calling strategy/graph code's job, not this
    module's.
    """


class GateCommandUnsafeError(ValueError):
    """A `gates.build`/`gates.test` string cannot be safely decomposed.

    Raised when the gate string contains a shell metacharacter other than the
    literal token ``&&`` (e.g. ``;``, ``|``, backtick, ``$(``, ``>``, ``<``, a
    newline). Since `s17code.coding.exec.run_command` never invokes a shell,
    there is no safe way to honor those characters' shell meaning, so the
    adapter refuses outright rather than guessing. Callers (e.g. the
    `validate_build_test` node) should catch this and route to
    `decision="gate_command_unsafe"`.
    """


@runtime_checkable
class EcosystemAdapter(Protocol):
    """One language/package-manager's worth of remediation know-how.

    `build_command`/`test_command` return ``list[list[str]] | None``: ``None``
    means "this gate is empty, skip it"; otherwise each inner list is one
    argv step to run in order via `s17code.coding.exec.run_command` (the gate
    string is split only on literal ``&&`` -- see `split_gate_command`).
    """

    name: str

    def detect(self, workspace: Workspace) -> bool:
        """True if this workspace looks like it belongs to this ecosystem."""
        ...

    def locate_component(self, workspace: Workspace, finding: dict[str, Any]) -> list[dict[str, Any]]:
        """Find every manifest location referencing `finding["component"]`.

        Each returned dict has at least ``{"file": str, "pattern_kind": str}``
        describing where and how the component was found, plus whatever
        adapter-private fields (e.g. ``old_version``, ``anchor``) it needs to
        build an edit anchor later in `apply_version_fix`. Returns ``[]`` (not
        an exception) when nothing is found -- the caller treats that as
        ``decision="not_found"``.
        """
        ...

    def apply_version_fix(
        self,
        workspace: Workspace,
        ledger: EditLedger,
        finding: dict[str, Any],
        location: dict[str, Any],
    ) -> dict[str, Any]:
        """Rewrite one located manifest entry to `finding["fixed_version"]`.

        Returns ``{"changed_files": [...], "old_version": str, "new_version": str}``.
        Raises `FixNotFoundError` if no safe anchor can be built, or lets
        `s17code.coding.edit.EditError` (e.g. anchor not unique) propagate --
        both are the caller's responsibility to convert into a decision.
        """
        ...

    def build_command(self, settings: dict[str, Any]) -> list[list[str]] | None:
        """Argv steps for `settings["gates"]["build"]`, or None to skip."""
        ...

    def test_command(self, settings: dict[str, Any]) -> list[list[str]] | None:
        """Argv steps for `settings["gates"]["test"]`, or None to skip."""
        ...

    def allowed_commands(self) -> tuple[str, ...]:
        """Program basenames this adapter needs on the exec allowlist."""
        ...


# Shell metacharacters other than the literal `&&` step separator that make a
# gate string unsafe to decompose into argv steps without a shell we
# deliberately never invoke. Mirrors (a subset relevant to a whole gate
# string, not a single token of) s17code.coding.exec.SHELL_METACHARACTERS.
_UNSAFE_METACHARACTERS = (";", "|", "`", "$(", ">", "<", "\n", "\r")


def split_gate_command(gate: str | None) -> list[list[str]] | None:
    """Split a `gates.build`/`gates.test` string into sequential argv steps.

    Splits ONLY on the literal token ``&&``. An empty/blank/None gate string
    means "skip this gate" and returns ``None``. Any other shell
    metacharacter makes the string unsafe to run without a shell, so this
    raises `GateCommandUnsafeError` instead of silently executing or
    crashing. Each ``&&``-delimited segment is `shlex.split` into one argv
    list; a shell is never invoked to run any of it.
    """
    if not gate:
        return None
    gate = gate.strip()
    if not gate:
        return None
    for meta in _UNSAFE_METACHARACTERS:
        if meta in gate:
            raise GateCommandUnsafeError(
                f"gate command contains unsupported shell metacharacter {meta!r}: {gate!r}"
            )
    segments = [segment.strip() for segment in gate.split("&&")]
    if any(not segment for segment in segments):
        raise GateCommandUnsafeError(f"gate command has an empty step around '&&': {gate!r}")
    return [shlex.split(segment) for segment in segments]
