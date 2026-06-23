"""Low-level subprocess wrapper around the cua-driver binary.

Every tool call goes through `call()`.  Nothing here knows about skills,
cascades, or the LLM — this is pure transport.

Usage:
    from computer.driver import ensure_daemon, call, activate_app

    ensure_daemon()
    pid = call("launch_app", {"app_name": "Calculator"})["pid"]
    activate_app("Calculator")
    state = call("get_window_state", {"pid": pid, "window_id": 0})
    call("press_key", {"pid": pid, "key": "4"})
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

DAEMON_START_TIMEOUT = 8  # seconds to wait for cua-driver serve to come up


def ensure_daemon() -> None:
    """Start cua-driver daemon if it is not already running. Idempotent."""
    result = subprocess.run(
        ["cua-driver", "status"],
        capture_output=True,
        timeout=5,
    )
    if result.returncode == 0:
        return

    # Not running — start it in the background.
    subprocess.Popen(
        ["cua-driver", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + DAEMON_START_TIMEOUT
    while time.time() < deadline:
        time.sleep(0.5)
        r = subprocess.run(["cua-driver", "status"], capture_output=True)
        if r.returncode == 0:
            return

    raise RuntimeError(
        "cua-driver daemon failed to start. "
        "Run `cua-driver permissions grant` first if this is a fresh install."
    )


def call(tool: str, args: dict) -> dict:
    """Call one cua-driver tool and return the parsed JSON response.

    Raises RuntimeError if the process exits non-zero or the output
    is not valid JSON.  All callers get a plain dict — they never see
    the subprocess at all.
    """
    result = subprocess.run(
        ["cua-driver", "call", tool, json.dumps(args)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"cua-driver call {tool} failed (exit {result.returncode}):\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    raw = result.stdout.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"status": raw}


def activate_app(app_name: str) -> None:
    """Bring `app_name` to the foreground on macOS.

    cua-driver's launch_app does NOT steal focus — on macOS the new
    process starts in the background.  Without this call the first
    get_window_state often returns an empty or stale AX tree because
    the window has not painted yet.
    """
    if sys.platform != "darwin":
        return
    subprocess.run(
        ["osascript", "-e", f'tell application "{app_name}" to activate'],
        capture_output=True,
    )
    time.sleep(0.5)  # let the window finish rendering before the first AX scan
