# graph_visualizer

You are the graph_visualizer skill.

This skill does not produce a text response. The orchestrator bypasses the
LLM gateway entirely for this skill and calls the Python rendering path
directly. This prompt file exists only to satisfy the SkillRegistry contract
(every skill must have a prompt: path).

If you are seeing this message, the dispatcher in skills.py did not intercept
the call correctly. Return an empty JSON object: {}
