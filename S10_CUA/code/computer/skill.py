"""Session 10: the Computer-Use (CUA) skill.

Four-layer cascade over native desktop apps via cua-driver:

    Layer 1   — AX extract: read the result from the AX tree with no action and
                no LLM. Used as the verification step inside Layer 2a.
    Layer 2a  — Deterministic hotkeys: parse a math expression from the goal and
                press the keys directly. $0, zero vision calls. (Calculator)
    Layer 2b  — AX + text LLM: feed the current AX tree to a cheap text model
                each turn; execute the returned action. (~cents per task)
    Layer 3   — Vision: screenshot → vision LLM → act. Last resort. (~dollars)

Escalation: each layer returns None on failure; the skill moves to the next.
Layer 2a is always tried first. Layer 3 is reached only when 2a and 2b fail.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from pathlib import Path
from typing import Any, Literal

from gateway import GATEWAY_URL, ensure_gateway
from schemas import AgentResult, ComputerOutput, NodeSpec

from . import driver
from .driver import activate_app, ensure_daemon

# Reuse the async V9Client from the Browser skill — same gateway, same surface.
from browser.client import V9Client


# ── helpers (module-level, no class state) ────────────────────────────────────

_STRIP_WORDS = re.compile(
    r'(?i)\b(compute|calculate|what\s+is|evaluate|find|result\s+of|equals?)\b'
)
_MATH_RE = re.compile(r'[\d\s\+\-\*\/\.\(\)×÷%]+')
_KEY_MAP = {'+': '+', '-': '-', '*': '*', '/': '/', '(': '(', ')': ')', '.': '.', '%': '%'}

# Symbols that press_key rejects (shift+digit combos on a US keyboard).
# These are sent via hotkey instead.
_SHIFT_KEYS: dict[str, list[str]] = {
    '*': ['shift', '8'],
    '(': ['shift', '9'],
    ')': ['shift', '0'],
    '%': ['shift', '5'],
}
_DISPLAY_ROLES = frozenset({"AXStaticText", "AXTextField", "AXValueIndicator"})

# Unicode bidirectional / LTR / RTL control characters that Calculator injects
# around every digit and operator in its AX labels.  Strip before any regex.
_BIDI_RE = re.compile(r'[\u200E\u200F\u202A-\u202E\u2066-\u2069​]')



# Deterministic text-write detection (Notes, Numbers, Pages, TextEdit …)
# Maps lowercase bundle_id → (display_name, new_doc_hotkey, confirm_key, needs_save)
# needs_save=True  → cmd+S + return after writing (apps without auto-save)
# needs_save=False → auto-saved by the OS (Notes syncs to iCloud automatically)
_WRITE_APPS: dict[str, tuple[str, list[str], str, bool]] = {
    "com.apple.notes":        ("Notes",    ["cmd", "n"], "",    False),
    "com.apple.iwork.numbers":("Numbers",  ["cmd", "n"], "tab", True),
    "com.apple.iwork.pages":  ("Pages",    ["cmd", "n"], "",    True),
    "com.apple.textedit":     ("TextEdit", ["cmd", "n"], "",    True),
}
_WRITE_RE = re.compile(
    r'(?i)'
    r'\b(write|add|append|save|put)\b'
    r'|create\s+(?:\w+\s+){0,2}(?:note|doc|sheet|spreadsheet)'
    r'|\btype\s+(?:the\s+)?(?:value|text|content|result|number|following)\b'
    r'|open\s+(?:\w+\s+){0,3}(?:spreadsheet|document|note)\b'
)


def _write_app_info(app_name: str, bundle_id: str) -> tuple[str, list[str], str, bool] | None:
    """Return (display_name, new_doc_keys, confirm_key, needs_save) if this is a text-write app."""
    info = _WRITE_APPS.get(bundle_id.lower())
    if info:
        return info
    name_lower = app_name.lower()
    for bid, entry in _WRITE_APPS.items():
        if entry[0].lower() in name_lower:
            return entry
    return None


def _extract_write_content(goal: str) -> str:
    """Strip preambles like 'write to Notes:'; return the body text."""
    m = re.search(r'\n\n(.+)', goal, re.DOTALL)
    if m:
        return m.group(1).strip()
    return goal.strip()


def _parse_expression(goal: str) -> str | None:
    """Return a normalized math expression from `goal`, or None if not Calculator-like."""
    cleaned = _STRIP_WORDS.sub('', goal)
    m = _MATH_RE.search(cleaned)
    if not m:
        return None
    expr = m.group(0).strip().replace('×', '*').replace('÷', '/')
    # Must have at least one digit and one operator
    if not (re.search(r'\d', expr) and re.search(r'[\+\-\*\/]', expr)):
        return None
    return expr


def _expr_to_keys(expr: str) -> list[str]:
    """Split a math expression string into a list of cua-driver key names."""
    return [
        ch if ch.isdigit() else _KEY_MAP[ch]
        for ch in expr
        if ch != ' ' and (ch.isdigit() or ch in _KEY_MAP)
    ]


def _parse_action_json(text: str) -> dict:
    """Extract the first JSON object from LLM output (strips markdown fences)."""
    t = text.strip()
    if t.startswith('```'):
        t = t.split('\n', 1)[1] if '\n' in t else t
        t = t.rstrip('`').strip()
    s, e = t.find('{'), t.rfind('}')
    if s >= 0 and e > s:
        try:
            return json.loads(t[s:e + 1])
        except json.JSONDecodeError:
            pass
    return {"action": "done", "result": None}


# ── skill class ───────────────────────────────────────────────────────────────

_AX_MAX_ELEMENTS = 500  # cap AX walk to prevent timeout on large apps (Notes, Electron)


class ComputerSkill:
    def __init__(
        self,
        artifacts_root: str,
        session: str,
        max_steps_a11y: int = 10,
        max_steps_vision: int = 5,
    ):
        self.artifacts_root = Path(artifacts_root)
        self.session = session
        self.max_steps_a11y = max_steps_a11y
        self.max_steps_vision = max_steps_vision
        self._client = V9Client(base_url=GATEWAY_URL, agent="computer", session=session)
        self._actions: list[dict] = []
        self._layer_trace: list[dict] = []
        self._cost: float = 0.0

    # ── async driver wrapper ──────────────────────────────────────────────────

    async def _call(self, tool: str, args: dict) -> dict:
        return await asyncio.to_thread(driver.call, tool, args)

    # ── main entry point ──────────────────────────────────────────────────────

    async def run(self, node_spec: NodeSpec, planner_dag: list[str] = []) -> AgentResult:
        meta = node_spec.metadata or {}
        app = meta.get("app", "")
        bundle_id = meta.get("bundle_id", "")
        goal = meta.get("goal", "")

        if not (app or bundle_id):
            return self._pack_error("", goal, "metadata.app or metadata.bundle_id required")
        if not goal:
            return self._pack_error(app, goal, "metadata.goal required")

        started = time.time()
        ensure_daemon()
        ensure_gateway()

        # ── launch ────────────────────────────────────────────────────────────
        # Try bundle_id first (unambiguous); fall back to display name if it fails.
        launch_args: dict[str, Any] = (
            {"bundle_id": bundle_id} if bundle_id else {"name": app}
        )
        try:
            launch = await self._call("launch_app", launch_args)
        except RuntimeError as exc:
            if bundle_id and app:
                try:
                    launch = await self._call("launch_app", {"name": app})
                except RuntimeError as exc2:
                    return self._pack_error(app, goal, f"launch_app: {exc2}")
            else:
                return self._pack_error(app, goal, f"launch_app: {exc}")

        pid = launch["pid"]
        windows = launch.get("windows", [])
        window_id = windows[0]["window_id"] if windows else await self._resolve_window(pid)
        app_name = app or launch.get("name", "")

        # ── recording ─────────────────────────────────────────────────────────
        rec_dir = self.artifacts_root / "recording"
        rec_dir.mkdir(parents=True, exist_ok=True)
        try:
            await self._call("start_recording", {
                "output_dir": str(rec_dir),
                "record_video": False,
            })
        except RuntimeError:
            pass  # non-fatal; per-turn screenshots still land in rec_dir

        # macOS: launch_app does not steal focus; activate explicitly then
        # verify with a probe scan (trap 8.2 from Axiom).
        activate_app(app_name)
        try:
            probe = await self._call("get_window_state", {
                "pid": pid,
                "window_id": window_id,
                "capture_mode": "ax",
                "max_elements": _AX_MAX_ELEMENTS,
            })
            element_count = probe.get("element_count", 0)
            if element_count == 0:
                return self._pack_error(
                    app_name, goal,
                    "element_count: 0 after activation. "
                    "Check: (1) cua-driver permissions grant, "
                    "(2) app activated (osascript already tried), "
                    "(3) QT_ACCESSIBILITY=1 if Qt/Linux, "
                    "(4) use bundle_id + electron_debugging_port if Electron app."
                )
        except RuntimeError as exc:
            return self._pack_error(app_name, goal, f"probe get_window_state failed: {exc}")

        # ── layer cascade ─────────────────────────────────────────────────────
        result: str | None = None
        path: Literal["extract", "deterministic", "a11y", "vision"] = "deterministic"

        layers = [
            (self._layer2a_deterministic, (pid, window_id, goal, app_name, bundle_id), "2a_deterministic", "deterministic"),
            (self._layer2b_a11y,          (pid, window_id, goal), "2b_a11y",          "a11y"),
            (self._layer3_vision,         (pid, window_id, goal, rec_dir), "3_vision", "vision"),
        ]

        for method, args, layer_label, layer_path in layers:
            t = time.time()
            result = await method(*args)
            elapsed = round(time.time() - t, 3)
            self._layer_trace.append({
                "layer": layer_label,
                "outcome": "hit" if result is not None else "miss",
                "elapsed_s": elapsed,
            })
            if result is not None and result.strip():
                path = layer_path
                break

        # ── teardown ──────────────────────────────────────────────────────────
        try:
            await self._call("stop_recording", {})
        except RuntimeError:
            pass

        if not result or not result.strip():
            return self._pack_error(app_name, goal, "all cascade layers exhausted")

        return self._pack(
            app=app_name, goal=goal, path=path,
            content=result, elapsed_s=time.time() - started,
        )

    # ── Layer 2a — deterministic hotkeys (Calculator) ─────────────────────────

    async def _layer2a_deterministic(
        self, pid: int, window_id: int, goal: str,
        app_name: str = "", bundle_id: str = ""
    ) -> str | None:
        """Math expressions via hotkeys (Calculator) or Notes write via cmd+N."""
        # Branch 1: math expression (Calculator and friends)
        expr = _parse_expression(goal)
        if expr is not None:
            return await self._layer2a_math(pid, window_id, expr)

        # Branch 2: text-write apps (Notes, Numbers, Pages, TextEdit)
        # Bypass the broken AX menu-bar traversal — use cmd+N + type_text instead.
        app_info = _write_app_info(app_name, bundle_id)
        if app_info and _WRITE_RE.search(goal):
            content = _extract_write_content(goal)
            if content:
                _, new_doc_keys, confirm_key, needs_save = app_info
                return await self._layer2a_write_app(pid, content, new_doc_keys, confirm_key, needs_save)

        return None

    async def _layer2a_math(self, pid: int, window_id: int, expr: str) -> str | None:
        """Press Calculator keys for `expr` and read the AX result."""
        keys = _expr_to_keys(expr)
        if not keys:
            return None

        # Reset Calculator state, then send the expression, then press Enter.
        # Symbols like * need hotkey(shift+8) — press_key rejects non-letter/digit keys.
        for key in ["escape", "escape"] + keys + ["return"]:
            if key in _SHIFT_KEYS:
                self._actions.append({"action": "hotkey", "keys": _SHIFT_KEYS[key], "layer": "2a"})
                await self._call("hotkey", {"pid": pid, "keys": _SHIFT_KEYS[key]})
            else:
                self._actions.append({"action": "press_key", "key": key, "layer": "2a"})
                await self._call("press_key", {"pid": pid, "key": key})

        await asyncio.sleep(0.2)  # give Calculator time to compute
        return await self._layer1_ax_extract(pid, window_id)

    async def _wait_for_new_window(self, pid: int, baseline: int, timeout: float = 20.0) -> None:
        """Poll list_windows until pid has more windows than baseline, then settle.

        Falls back to a long fixed wait when the app reuses an existing window
        (e.g. Numbers: template chooser transitions to blank sheet without opening
        a second window — the count never increases).
        """
        await asyncio.sleep(1.0)  # minimum gap before first poll
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                resp = await self._call("list_windows", {"pid": pid})
                if len(resp.get("windows", [])) > baseline:
                    await asyncio.sleep(2.0)  # window appeared; wait for cell A1 focus
                    return
            except RuntimeError:
                pass
            await asyncio.sleep(0.5)
        # Timeout: window count never changed (single-window transition).
        # Give the app a generous fixed wait before typing.
        await asyncio.sleep(5.0)

    async def _layer2a_write_app(
        self, pid: int, content: str,
        new_doc_keys: list[str], confirm_key: str, needs_save: bool = False
    ) -> str | None:
        """Open a new document/note/sheet and type content — zero AX navigation."""
        # Snapshot window count before cmd+N so the poll knows what "new" means.
        try:
            resp = await self._call("list_windows", {"pid": pid})
            baseline = len(resp.get("windows", []))
        except RuntimeError:
            baseline = 0

        self._actions.append({"action": "hotkey", "keys": new_doc_keys, "layer": "2a"})
        await self._call("hotkey", {"pid": pid, "keys": new_doc_keys})

        # Wait until the new document window actually appears (poll-based, up to 8s).
        await self._wait_for_new_window(pid, baseline)

        body = content[:4000]
        self._actions.append({"action": "type_text", "text": body, "layer": "2a"})
        await self._call("type_text", {"pid": pid, "text": body})
        await asyncio.sleep(0.3)

        if confirm_key:
            self._actions.append({"action": "press_key", "key": confirm_key, "layer": "2a"})
            await self._call("press_key", {"pid": pid, "key": confirm_key})

        if needs_save:
            # cmd+S triggers the Save sheet; Return confirms the default name/location.
            self._actions.append({"action": "hotkey", "keys": ["cmd", "s"], "layer": "2a"})
            await self._call("hotkey", {"pid": pid, "keys": ["cmd", "s"]})
            await asyncio.sleep(0.8)  # wait for Save sheet to appear
            self._actions.append({"action": "press_key", "key": "return", "layer": "2a"})
            await self._call("press_key", {"pid": pid, "key": "return"})
            await asyncio.sleep(0.5)  # wait for save to complete

        preview = content[:120].replace("\n", " ")
        return f"Written and saved: {preview}{'...' if len(content) > 120 else ''}"

    # ── Layer 1 — AX extract (read-only; used as verification in Layer 2a) ────

    async def _layer1_ax_extract(self, pid: int, window_id: int) -> str | None:
        """Read the displayed value from the AX tree. No actions, no LLM."""
        try:
            state = await self._call("get_window_state", {
                "pid": pid,
                "window_id": window_id,
                "capture_mode": "ax",
                "max_elements": _AX_MAX_ELEMENTS,
            })
        except RuntimeError:
            return None

        # Preferred path: structured elements array (top-level "elements" key —
        # cua-driver moved away from structuredContent.elements, see _note).
        for el in state.get("elements", []):
            if el.get("role") in _DISPLAY_ROLES:
                # Strip Unicode bidi marks Calculator injects around every digit
                label = _BIDI_RE.sub('', el.get("label", "")).strip()
                if label and re.match(r'^-?[\d,. ]+$', label):
                    return label

        # Fallback: scan the markdown — lines look like: AXStaticText = "\u200E38"
        for line in state.get("tree_markdown", "").splitlines():
            clean = _BIDI_RE.sub('', line)
            m = re.search(r'"(-?[\d,. ]+)"', clean)
            if m:
                candidate = m.group(1).strip()
                if candidate and candidate not in ("0", ""):
                    return candidate

        return None

    # ── Layer 2b — AX tree + text LLM ────────────────────────────────────────

    async def _layer2b_a11y(self, pid: int, window_id: int, goal: str) -> str | None:
        """Scan-act-verify loop driven by a text LLM reading the AX tree."""
        prompt_sys = (Path(__file__).parent.parent / "prompts" / "computer.md").read_text()

        for turn in range(self.max_steps_a11y):
            try:
                state = await self._call("get_window_state", {
                    "pid": pid,
                    "window_id": window_id,
                    "capture_mode": "ax",
                    "max_elements": _AX_MAX_ELEMENTS,
                })
            except RuntimeError:
                return None

            # Trap guard: empty AX tree means the probe passed but the window
            # reflowed or a modal appeared — don't send blank context to the LLM.
            if state.get("element_count", 0) == 0:
                return None

            ax_tree = state.get("tree_markdown", "(empty)")
            prompt = (
                f"GOAL: {goal}\n\n"
                f"TURN: {turn + 1}/{self.max_steps_a11y}\n\n"
                f"AX TREE:\n{ax_tree[:8_000]}\n\n"
                f"HISTORY (last 5 actions):\n{json.dumps(self._actions[-5:], indent=2)}\n\n"
                "Reply with the next action JSON:"
            )

            reply = await self._client.chat(
                prompt=prompt,
                system=prompt_sys,
                max_tokens=256,
                session=self.session,
            )
            action = _parse_action_json(reply.text)

            if action.get("action") == "done":
                return action.get("result") or reply.text

            ok = await self._execute_action(pid, window_id, action, layer="2b")
            if not ok:
                # Invariant 2: scan once more before giving up so the layer_trace
                # records the post-failure state rather than returning on stale state.
                await self._layer1_ax_extract(pid, window_id)
                break

        return None

    # ── Layer 3 — vision + vision LLM ────────────────────────────────────────

    async def _layer3_vision(
        self, pid: int, window_id: int, goal: str, rec_dir: Path
    ) -> str | None:
        """Screenshot → vision LLM → act loop."""
        for turn in range(self.max_steps_vision):
            try:
                # capture_mode="vision" skips the AX walk → faster screenshot
                state = await self._call("get_window_state", {
                    "pid": pid,
                    "window_id": window_id,
                    "capture_mode": "vision",
                })
            except RuntimeError:
                return None

            raw_b64 = state.get("screenshot")
            if not raw_b64:
                return None

            image_data_url = f"data:image/png;base64,{raw_b64}"
            prompt = (
                f"Goal: {goal}\n\n"
                f"Turn {turn + 1}/{self.max_steps_vision}.\n"
                "Look at the screenshot. What is the single best next action?\n\n"
                'Reply with JSON only:\n'
                '{"action": "press_key"|"click_xy"|"type_text"|"done", '
                '"key": "...", "x": 0, "y": 0, "text": "...", '
                '"result": "...", "reason": "..."}'
            )

            try:
                reply = await self._client.vision(
                    image_data_url=image_data_url,
                    prompt=prompt,
                    max_tokens=256,
                    session=self.session,
                )
            except Exception:
                return None

            action = _parse_action_json(reply.text)

            if action.get("action") == "done":
                return action.get("result") or reply.text

            # Vision replies may use pixel coordinates instead of element_index
            if action.get("action") == "click_xy":
                x, y = int(action.get("x", 0)), int(action.get("y", 0))
                self._actions.append({"action": "click_xy", "x": x, "y": y, "layer": "3"})
                try:
                    await self._call("click", {
                        "pid": pid,
                        "window_id": window_id,
                        "x": x,
                        "y": y,
                    })
                except RuntimeError:
                    pass
            else:
                await self._execute_action(pid, window_id, action, layer="3")

        return None

    # ── action executor (shared by 2b and 3) ──────────────────────────────────

    async def _execute_action(
        self, pid: int, window_id: int, action: dict, layer: str = "?"
    ) -> bool:
        """Dispatch one LLM-produced action. Returns False if unknown or failed."""
        kind = action.get("action", "")
        entry = {"action": kind, "layer": layer}
        try:
            if kind == "press_key":
                key = action.get("key", "")
                entry["key"] = key
                await self._call("press_key", {"pid": pid, "key": key})
            elif kind == "click":
                ei = action.get("element_index")
                entry["element_index"] = ei
                await self._call("click", {
                    "pid": pid,
                    "window_id": window_id,
                    "element_index": ei,
                })
            elif kind == "type_text":
                text = action.get("text", "")
                entry["text"] = text
                await self._call("type_text", {"pid": pid, "text": text})
            elif kind == "hotkey":
                keys = action.get("keys", [])
                entry["keys"] = keys
                await self._call("hotkey", {"pid": pid, "keys": keys})
            elif kind == "scroll":
                direction = action.get("direction", "down")
                amount = int(action.get("amount", 3))
                entry["direction"] = direction
                entry["amount"] = amount
                await self._call("scroll", {"pid": pid, "direction": direction, "amount": amount})
            else:
                return False
            self._actions.append(entry)
            return True
        except RuntimeError as exc:
            self._actions.append({**entry, "error": str(exc)})
            return False

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _resolve_window(self, pid: int) -> int:
        """Pick the best window for `pid`: largest on-screen window by area."""
        await asyncio.sleep(0.5)  # let the app finish creating its window
        try:
            resp = await self._call("list_windows", {"pid": pid})
            windows = resp.get("windows", [])
            # Prefer on-screen; among those take the largest by pixel area
            candidates = [w for w in windows if w.get("is_on_screen")] or windows
            if candidates:
                best = max(
                    candidates,
                    key=lambda w: w["bounds"]["width"] * w["bounds"]["height"],
                )
                return best["window_id"]
        except RuntimeError:
            pass
        return 0

    def _pack(
        self, *, app: str, goal: str, path: str, content: str, elapsed_s: float
    ) -> AgentResult:
        out = ComputerOutput(
            app=app,
            goal=goal,
            path=path,
            turns=len(self._actions),
            content=content,
            actions=self._actions,
            layer_trace=self._layer_trace,
            cost_summary={"total_usd": round(self._cost, 6)},
        )
        return AgentResult(
            success=True,
            agent_name="computer",
            output=out.model_dump(),
            elapsed_s=elapsed_s,
            cost=self._cost,
        )

    def _pack_error(self, app: str, goal: str, error: str) -> AgentResult:
        return AgentResult(
            success=False,
            agent_name="computer",
            error=error,
            output={"app": app, "goal": goal, "error": error},
        )
