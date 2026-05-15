"""
Lesson A — Hello Prefab.

Read the README.md next to this file first. Then read this code. Then run:

    prefab serve hello.py --reload

The browser will open to http://127.0.0.1:5175 automatically.

What to notice:
  - The whole page is one nested `with` block. That nesting IS the UI tree.
  - No state. No events. Buttons would render but do nothing. That is fine —
    Lesson B adds the interactivity.
"""

from prefab_ui.app import PrefabApp
from prefab_ui.components import Card, CardContent, Column, H3, Muted


with PrefabApp(css_class="max-w-md mx-auto") as app:
    with Card():
        with CardContent():
            with Column(gap=3):
                H3("Hello, Prefab!")
                Muted("This is a static page. We will add buttons next.")
