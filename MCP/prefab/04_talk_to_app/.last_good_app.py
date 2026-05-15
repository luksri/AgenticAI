from prefab_ui.app import PrefabApp
from prefab_ui.components import Card, CardContent, CardHeader, CardTitle, Muted

with PrefabApp(css_class="max-w-md mx-auto p-6") as app:
    with Card():
        with CardHeader():
            CardTitle("Talk-to-App")
        with CardContent():
            Muted("Waiting for your first prompt in the terminal...")
