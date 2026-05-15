"""
The smallest UI that has a pulse: a counter you control from the terminal.

Read the README.md next to this file first. Then read the code top to bottom.
Then run it:    python counter.py

Controls (type a letter and hit enter):
    i   increment
    r   reset to 0
    q   quit

What to notice while reading:
  - `render()` DESCRIBES what the screen looks like right now. It is called
    after every state change. We never draw anything "by hand."
  - `count` is a plain Python int. That is the STATE.
  - `handle(cmd)` is the only place state changes. That is the HANDLER.
  - The `while True:` loop at the bottom is the DRAW LOOP.
"""

import os


# 2. The STATE. A plain int the rest of the program listens to.
count = 0


# 1. The TREE. `render()` prints the "layout" of the screen. In a GUI framework
#    this would be a tree of widgets. In the terminal it is just a few prints.
def render() -> None:
    os.system("cls" if os.name == "nt" else "clear")
    print("+----------------------+")
    print(f"|   Counter: {count:<9} |")
    print("+----------------------+")
    print("  [i] increment   [r] reset   [q] quit")


# 3. The HANDLER. One job: change the state. Nothing else.
def handle(cmd: str) -> bool:
    """Returns False when it is time to exit, True otherwise."""
    global count
    if cmd == "i":
        count += 1
    elif cmd == "r":
        count = 0
    elif cmd == "q":
        return False
    return True


# 4. The DRAW LOOP. Render -> wait for event -> handle -> render again.
#    Every UI framework has a loop like this. Usually it is hidden from you.
#    Here we wrote it ourselves so you can see it.
if __name__ == "__main__":
    running = True
    while running:
        render()
        cmd = input("> ").strip().lower()
        running = handle(cmd)
