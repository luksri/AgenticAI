"""Curated, deterministic fix templates for a known-safe set of exact Semgrep
rule ids.

A template is the "no LLM needed" tier of `SASTStrategy`: it claims one exact
`finding["id"]` and rewrites the flagged line mechanically, the same
confidence level as SCA's version bump. Everything not covered by a template
falls through to `sast.llm_fix`. See `registry.py` for the list templates
register into, and `base.py` for the shared contract.
"""
