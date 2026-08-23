"""Shared pytest fixtures: real git-backed workspaces from tests/fixtures/*.

`Workspace.branch()`/`.diff()`/`.reset()` shell out to git, so every fixture
workspace is a real `git init`-ed temp directory (a copy of the template
under `tests/fixtures/`), never the fixtures directory itself.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from s17code.coding.workspace import Workspace

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _run_git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _make_git_workspace(tmp_path: Path, template_name: str) -> Workspace:
    dest = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR / template_name, dest)
    _run_git(["init"], dest)
    _run_git(["config", "user.email", "test@example.com"], dest)
    _run_git(["config", "user.name", "Test User"], dest)
    _run_git(["add", "-A"], dest)
    _run_git(["commit", "-m", "initial fixture commit"], dest)
    return Workspace.open(dest)


@pytest.fixture
def dotnet_workspace(tmp_path: Path) -> Workspace:
    return _make_git_workspace(tmp_path, "dotnet_sample")


@pytest.fixture
def java_workspace(tmp_path: Path) -> Workspace:
    return _make_git_workspace(tmp_path, "java_sample")


@pytest.fixture
def java_gradle_workspace(tmp_path: Path) -> Workspace:
    return _make_git_workspace(tmp_path, "java_gradle_sample")


@pytest.fixture
def dotnet_sast_workspace(tmp_path: Path) -> Workspace:
    return _make_git_workspace(tmp_path, "dotnet_sast_sample")
