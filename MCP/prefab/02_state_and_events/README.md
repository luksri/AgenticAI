# Lesson B — State and Events, the Prefab Way

This is the same counter you built in the terminal, now in the browser, now in Prefab. Read that sentence again. We are not learning something new. We are learning the same four ideas in a new dialect. If you feel lost, flip back to the pre-lesson.

## The Prefab dialect, in two words

Prefab has two small concepts that replace everything Tkinter gave us around state and events. Learn these two and you are done.

### `Rx` — reactive state

```python
from prefab_ui.rx import Rx

count = Rx("count")
```

`Rx("count")` is a **named handle to a value that lives in the page's state**. The string `"count"` is the key.

That is the Prefab equivalent of the pre-lesson's plain `count = 0`. Same idea: a number the UI knows how to listen to. The difference is that an `Rx` is *watched* — anything bound to it redraws automatically when it changes, so we never have to call `render()` ourselves.

We also have to tell Prefab the **initial value** of the state, and we do that on the `PrefabApp` itself:

```python
with PrefabApp(state={"count": 0}, ...) as app:
    ...
```

That seeds the page's state store with `count = 0` before anything renders. Without it, the expression `{{ count + 1 }}` on the first click would read `undefined + 1 = NaN` — a common first-day Prefab stumble.

The magic: wherever you drop `count` inside an f-string, **Prefab remembers the binding**. When `count` changes, every place that used it redraws. You do not redraw. You never redraw. You change `count` and Prefab does the rest.

### `SetState` — the action that changes state

```python
from prefab_ui.actions import SetState

Button("Increment", on_click=SetState("count", "{{ count + 1 }}"))
```

`SetState(key, new_value)` is an **action**. It says "when this fires, set the state key `count` to whatever `{{ count + 1 }}` evaluates to." The `{{ ... }}` is a small expression language — read `count` inside it as *"the current value of count"*.

That one line is the Prefab equivalent of the pre-lesson's

```python
def handle(cmd):
    global count
    if cmd == "i":
        count += 1
```

Several lines collapsed to one, because Prefab lets you describe the action declaratively instead of writing a handler function by hand. You may miss the handler. That is fair. We will bring handlers back in Lesson C, where we need to talk to an MCP server.

## The counter, side by side

Here is how the mental model maps.

| Terminal counter                              | Prefab                                                     |
|-----------------------------------------------|------------------------------------------------------------|
| `count = 0`                                   | `count = Rx("count").default(0)`                           |
| `print(f"Counter: {count}")` inside `render`  | `H1(f"{count}")`                                           |
| `if cmd == "i": count += 1`                   | `SetState("count", "{{ count + 1 }}")`                     |
| the `while True` loop with `input()`          | `Button("...", on_click=SetState(...))`                    |
| `render()` called on every iteration          | Prefab re-renders automatically when `count` changes        |

Same four ideas, different dialect. That is the whole lesson.

## Read the code, then run it

Open [counter.py](counter.py). You will see one `Rx`, one `H1` bound to it, and one `Button` with an `on_click` action. That is the entire app.

```bash
prefab serve counter.py --reload
```

Browser opens. Click the button. The number goes up. You did not write a loop. You did not manually refresh. You described a tree and wired one action. Prefab did the rest.

## Small experiments

Keep the browser open, keep `--reload` running, and try these in order. Save after each, watch the page update.

1. **Change the step size.** Make the button add 5 instead of 1. *Hint: only the expression inside `{{ }}` changes.*
2. **Add a decrement button.** Put a second `Button` next to the first. Think about how its `SetState` should look.
3. **Start at 100.** Find the one line that controls the initial value.
4. **Add a reset.** A third button that sets `count` back to 0. Note that the new value does not have to be an expression — a literal `0` works too (`SetState("count", 0)`).

If you nailed all four, you understand Prefab state and events. Honestly, you do.

## What changed from Tkinter, in one sentence

Tkinter made you write the "change state" function yourself. Prefab lets you *describe* the state change as data (`SetState`), so the framework can do more for you — and, crucially, so an LLM can emit it later without running Python. Keep that last bit in the back of your head. It is why we are doing this.

## Ready check

1. What is the Prefab name for "a reactive number the UI watches"?
2. What is the Prefab name for "the action that updates state on click"?
3. If I wanted the button label itself to include the current count — for example, `Incremented 3 times` — which existing piece would I change, and what would it look like?

If those three are easy, move to Lesson C, where we put Prefab inside an MCP server and return a real UI from a tool call.
