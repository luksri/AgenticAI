# Pre-lesson — How a UI Actually Thinks

Before we touch Prefab, I want you to get comfortable with four ideas. These four ideas are what every UI framework in the world is built on — React, SwiftUI, Flutter, Jetpack Compose, Tkinter, and yes, Prefab. Once these click, Prefab becomes boring in the best way: you already know how it thinks.

We will learn these four ideas by building the smallest possible UI that has a pulse: **a counter you control from the terminal**. Type `i`, the number goes up. That is it. Pure Python, no installs, no browser. We stay in the terminal so you can see every moving part of a UI loop without a framework hiding it from you.

## The four ideas

### 1. A UI is a tree, not a script

When you write a command-line program, you are thinking in time — first this runs, then that runs, then it ends. A UI is not like that. A UI is a **description of what should be on the screen right now**, which gets re-drawn whenever something changes.

In our counter, that description is small:

```
+----------------------+
|   Counter: 0         |
+----------------------+
  [i] increment   [r] reset   [q] quit
```

Your Python code's job is to **describe that screen once** — in a function called `render()` — and then call it whenever something changes. The function does not keep track of what the screen used to look like. It just writes down what the screen should look like now, given the current state.

This is the first mental flip. You are not writing a program that runs top to bottom. You are writing a program that sets up a scene, and a rule for how to re-draw that scene whenever something changes.

### 2. State is the data behind the scene

The scene has a number in it — let's call it `count`. That number is **state**. State is just "the data that the UI is showing right now."

The rule, and this is the rule that governs every UI framework: **the UI is a function of state**.

Read that again. It means: *if you know the value of `count`, you know exactly what the screen looks like.* The screen does not have a mind of its own. The screen is `count` rendered visually.

So the question "how do I change what's on the screen?" has exactly one answer: **change the state, and re-render.**

### 3. Events change state

You do not change the screen directly. You change **state**, and then re-render.

So what changes state? **Events.** A click, a keypress, a command typed into a terminal — these are all events. Every event is wired to a small Python function (we call it a **handler** or **callback**). The handler's job is one thing: update the state.

The full loop looks like this:

```
User types ──► event fires ──► handler runs ──► state changes ──► UI re-renders
```

Every single UI you have ever used works this way. Gmail, Instagram, your banking app, Excel. All of them. Once you see this loop, you will see it everywhere.

### 4. The framework owns the draw loop, you don't

In most UI frameworks, you never write the "re-draw" loop yourself — the framework does it for you. In our tiny terminal program, we write the loop out in the open, so you can see it. That loop is four lines at the bottom of `counter.py`:

```python
while running:
    render()
    cmd = input("> ").strip().lower()
    running = handle(cmd)
```

Read that out loud: *render the screen, wait for an event, hand it to the handler, repeat.* That is the beating heart of every UI. In Prefab you will never see this loop — it is hidden inside `prefab serve`. But it is running, in exactly this shape, every time.

## How this maps to Prefab

Every one of these four ideas shows up in Prefab, just under Python-flavoured names. Here is the preview so you know where we are heading:

| Idea | In our terminal counter (today) | In Prefab (next lesson) |
|---|---|---|
| A UI is a tree | the `render()` function | `with Page(): Text(...)` |
| State | the `count` variable | a reactive `Rx("count")` object |
| Events | a keystroke typed at the prompt | `Button(on_click=...)` |
| Draw loop | our `while True:` loop | Prefab runs the server |

The names change. The ideas do not.

## What we are going to build now

A counter with:
- a screen that shows a number, starting at 0
- three keystrokes: `i` to increment, `r` to reset, `q` to quit
- a re-render after every keystroke so the number updates

Open [counter.py](counter.py) and read it top to bottom before you run it. Notice:

1. We **describe** the screen inside `render()` — that is the tree.
2. We hold the count in a plain `count` variable — that is the state.
3. We write one tiny function `handle()` — that is the handler.
4. We write a small `while` loop at the bottom — that is the draw loop.

Then run it:

```bash
python counter.py
```

Type `i`, enter. Type `i`, enter. Watch the number go up. Type `r`, enter to reset. Type `q`, enter to quit. Every keystroke, travelling through `handle`, changing `count`, triggering a fresh `render()` — that is the entire UI world in one gesture.

## When you are done

Close the program and answer these out loud or in a note:

1. If I wanted the counter to go up by 5 instead of 1, what is the *only* line I would change?
2. If I wanted the number to start at 100, what is the *only* line I would change?
3. If I deleted the `render()` call from inside the `while` loop, what do you think would happen?

If those three answers feel obvious, you are ready for Prefab. The whole next lesson is the same four ideas — just written in a different dialect.
