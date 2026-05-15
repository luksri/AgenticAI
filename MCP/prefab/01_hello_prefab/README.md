# Lesson A — Hello Prefab

You just built a counter in Tkinter. Same four ideas are about to show up in Prefab, but the dialect changes in one big way: **Prefab draws in a browser, not a desktop window**. The Python you write stays Python. The thing the user sees is a web page.

In this lesson we will not worry about state or events yet. Our only goal is to learn **how Prefab lets you describe a tree in Python**. Just the shape. We will add interactivity in the next lesson.

## Install Prefab

```bash
pip install prefab-ui
```

Prefab needs Python 3.10 or newer.

## The smallest Prefab app

Open [hello.py](hello.py). Read it before you run it. Notice how the whole page is described by **nested `with` blocks** — the same context-manager idea you already use for opening files.

Mental mapping to the tree:

```
PrefabApp
└── Card
    └── CardContent
        └── Column
            ├── H3("Hello, Prefab!")
            └── Muted("This is a static page. We will add buttons next.")
```

That Python reads top-to-bottom like a sentence: *"Inside the app, put a card; inside the card, put content; inside the content, stack a heading and some muted text vertically."* That is the whole DSL.

## Running it

```bash
prefab serve hello.py --reload
```

Your browser opens to `http://127.0.0.1:5175`. You will see a card with a heading and a line of grey text. That is it — no HTML, no CSS, no JavaScript touched you.

The `--reload` flag means: edit `hello.py`, save, and the page refreshes by itself. Keep that terminal running. Keep the browser open next to your editor. This is how we will work for the rest of the session.

## Try these edits

Do these in order, saving after each one, and watch the page update:

1. Change the text inside `H3(...)` to your name. Save.
2. Add a second `Muted(...)` line below the first one with any message. Save.
3. Wrap the whole `Column` in another `Column(gap=6)` — notice the spacing change.

Every edit is one Python change. No rebuild, no reload button. That tightness is what makes Prefab feel alive.

## What you are NOT doing yet

You are not storing any state. You are not reacting to clicks. If you add a `Button("Click me")` now, it will render — but clicking it does nothing. That is intentional. Buttons without state are just shapes on the page. The next lesson is where the page comes alive.

## Check yourself before moving on

1. In `hello.py`, which line corresponds to "the root of the tree"?
2. If I wanted three headings stacked on top of each other, which component would I reach for — `Column` or `Row`?
3. What command re-runs the app, and what file would I edit to change what it shows?

If those three feel easy, move on to Lesson B, where we wire in state and events and rebuild the counter from Tkinter — this time in the browser.
