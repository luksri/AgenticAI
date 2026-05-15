"""
Lesson B — the Tkinter counter, rebuilt in Prefab.

Read the README.md next to this file first. Then run:

    prefab serve counter.py --reload

What to notice:
  - `Rx("count").default(0)` is the state. Same role as tk.IntVar, different dialect.
  - `H1(f"{count}")` binds the heading to the state. No manual refresh anywhere.
  - `SetState("count", "{{ count + 1 }}")` IS the click handler. No def, no callback.
  - Prefab owns the render loop. You describe; it draws.
"""

from prefab_ui.app import PrefabApp
from prefab_ui.components import Button, Card, CardContent, CardHeader, CardTitle, Column, H1
from prefab_ui.actions import SetState
from prefab_ui.rx import Rx


count = Rx("count")


with PrefabApp(state={"count": 0}, css_class="max-w-md mx-auto") as app:
    with Card():
        with CardHeader():
            CardTitle("Counter")
        with CardContent():
            with Column(gap=4):
                H1(f"{count}")
                Button(
                    "Increment",
                    on_click=SetState("count", "{{ count + 1 }}"),
                )
