# remediation-agent

A LangGraph agent that takes a deterministic Orchestrator's vulnerability
payload (already built elsewhere, not part of this project) and fixes the
findings in-place: locates each finding, applies a category-specific fix,
validates it against the repo's own `build`/`test` gates (and, for code-level
findings, a re-run of the scanner that flagged it), and commits the result to
a local branch. It does not open pull requests and does not touch git
remotes -- that is handled by a separate stage. It also does not track
cost/budget.

Two finding categories are implemented: **SCA** (Trivy-style dependency
version bumps) and **SAST** (Semgrep-style vulnerable-code fixes). Both are
pluggable -- see [Remediation categories](#remediation-categories) below.

## Graph shape

Parent graph (`src/remediation_agent/graph/build.py`), one orchestrator
payload end to end:

```
START -> ingest --route--> plan_findings --fanout--> remediate_unit* -> aggregate -> END
             \--(ingest_error)--------------------------------------------> END
```

`remediate_unit` is a `Send` fan-out target: one invocation per
`RemediationUnit` produced by `plan_findings`, each running the per-unit
subgraph below. Results are concatenated back into parent state via
LangGraph's `operator.add` reducer on `unit_results`. Units for the same
repo share one on-disk checkout, so `remediate_unit` serializes them through
a per-`workspace_root` lock (`execution/locks.py`) even though the fan-out
itself is logically parallel -- real concurrency at scale comes from many
different repos running at once (`execution/pool.py`), not from
parallelizing units within one repo.

Per-unit subgraph (`src/remediation_agent/graph/unit_subgraph.py`), compiled
once as `UNIT_GRAPH`:

```
classify_ecosystem -> locate -> generate_fix -> guard_check -> validate_build_test -> decide -> END
        \___________________\___________________\_______________\______________________/
                         (any node can set a terminal `decision` and skip straight to `decide`)
```

Every node from `classify_ecosystem` through `validate_build_test` is
followed by a conditional edge: if that node already set a terminal
`decision` (e.g. `unsupported_ecosystem`, `fix_failed_validation`), control
jumps straight to `decide` instead of continuing the chain. This is a
graph-level guarantee that every unit reaches a structured result
(`schemas/state.py`'s `UnitDecision`) without any node needing to raise --
including from failures a node can't enumerate in advance (e.g. an LLM
API error on the SAST path): `generate_fix.py` catches broadly around a
strategy's `remediate` call for exactly this reason, resetting the shared
workspace before reporting `fix_failed` rather than letting an unexpected
exception abort the whole run.

`locate` and `generate_fix` branch on what a finding actually carries, not on
its category name: a finding with a `component` (SCA) is located via the
ecosystem adapter's manifest search; a finding with a `line` instead (SAST)
is located generically by reading that line off disk
(`sast/locate.py:locate_by_line`), no ecosystem knowledge required.
`classify_ecosystem` still runs first either way, since build/test gates are
ecosystem-specific regardless of which category is being fixed.

## Remediation categories

`strategies/registry.py` dispatches on `finding["category"]`, falling back to
a clean "not yet supported" result for anything unregistered -- so a future
category (e.g. Trivy misconfiguration/IaC or secrets findings) degrades
gracefully today, and later just needs one new strategy module plus one
registry line.

**SCA** (`strategies/sca.py`) -- deterministic, no LLM call. A `component`
(package) is grouped and version-bumped via the ecosystem adapter's
`apply_version_fix` (anchor-based text replace). `ecosystems/dotnet.py` and
`ecosystems/java.py` are the two shipped `EcosystemAdapter`s (`.csproj` /
`packages.config` / `Directory.Packages.props` for .NET; Maven `pom.xml` /
Gradle `build.gradle[.kts]` for Java); a third language is one new adapter
module plus one registry line in `ecosystems/registry.py`, no graph changes.

**SAST** (`strategies/sast.py`) -- a finding with `line`/`snippet` instead of
`component` (Semgrep's shape: `id` is the rule id, `cwe_ids` classifies the
vulnerability). Two-tier dispatch, in order:

1. **Curated rule-id template** (`sast/templates/`) -- deterministic,
   exact-match on `finding["id"]`. Ships one worked example,
   `dotnet_insecure_deserialization.py`, which rewrites an unguarded
   `JsonConvert.DeserializeObject` call to pass an explicit
   `TypeNameHandling.None`. A template that finds its rule id matched but the
   code doesn't actually look like what it knows how to rewrite raises
   `TemplateNotApplicableError` rather than guessing, falling through to tier 2.
2. **LLM-authored patch** (`sast/llm_fix.py`) -- for anything with no
   template. Guided by curated, CWE-keyed cheat sheets
   (`sast/guidance.py` + `sast/skills/<cwe>/SKILL.md`, one per vulnerability
   class) built on session-17's markdown-skill mechanism (see below); ships
   one worked skill, `cwe-502-insecure-deserialization`. A malformed/
   unparseable model response raises `LLMFixError` rather than proceeding
   with a guessed patch. Adding a new CWE's guidance is one dict entry in
   `CWE_TO_SKILL` plus one new `SKILL.md` folder.

Either tier's result carries `fix_tier: "template" | "llm"`, which
`validate_build_test.py` uses to decide how hard a SAST fix's gates are:

- **Every** SAST unit, either tier: build/test gates (if configured), then a
  **re-run of the specific Semgrep rule** that flagged it
  (`sast/semgrep_verify.py`) against the patched file, confirming it no
  longer fires. This fails closed on every ambiguous outcome, not just an
  outright error: a missing binary, a timeout, unparseable output, *and* an
  empty `results` list with nothing in `paths.scanned` (verified against a
  real `semgrep` binary -- `--config r/<rule-id>` for a rule id that doesn't
  resolve to any real public-registry rule loads zero rules and exits 0 with
  empty results, which is indistinguishable from "genuinely fixed" unless you
  also check that something was actually scanned) are all treated the same as
  "still vulnerable," never silently accepted as a pass.
- **LLM-tier only**: the adversarial validator (`llm/adversarial_validator.py`)
  runs **unconditionally**, not gated by `REMEDIATION_ADVERSARIAL_VALIDATION`
  the way it is for every other case. An LLM-authored security patch is never
  accepted on build/test + semgrep alone.

`SASTStrategy.remediate` is `async def` (it awaits a chat-model call on the
LLM-fallback path); `SCAStrategy.remediate` stays a plain sync method.
`generate_fix.py` awaits the result only when it's awaitable, so a strategy
never has to fake a synchronous signature by bridging its own async work onto
a separate thread/event loop -- doing that would block the single shared
event loop every other concurrently-running unit and job depend on, which
defeats the concurrency model `execution/pool.py` exists to provide.

## Harness: investigation and retries for the LLM-fallback tier

Two things specifically make the SAST LLM-fallback path more than a single
blind guess:

**Tool access before answering.** `sast/llm_fix.py:ask_llm_for_patch` doesn't
just read a fixed window around the flagged line and propose a patch in one
shot -- it gets bounded, read-only tool access (`read_file`, `grep`, `glob`,
`run`, mirroring `llm/adversarial_validator.py`'s established tool-loop
pattern) to investigate other call sites, related files, or run a command
before committing to an answer. Every `read_file` call goes through the same
`EditLedger` as the initial window, so whatever region the model ends up
anchoring on -- even one it only saw via a tool call -- has genuinely been
read before `apply_edit` is asked to touch it. The proposed edit is still
constrained to the flagged file even though the model can explore elsewhere.

**Bounded retry with feedback.** A downstream gate rejecting an LLM-authored
fix (`guard_check.py`'s scope check, or `validate_build_test.py`'s build/test/
semgrep/adversarial gates) doesn't have to be terminal. `graph/nodes/unit/
_retry.py` decides whether it's worth trying again: only for `fix_tier ==
"llm"` (a deterministic template given the same input produces the same,
already-known-bad output, so retrying it would burn the budget without
changing anything -- see the module's docstring), and only while
`Settings.sast_max_attempts` (`REMEDIATION_SAST_MAX_ATTEMPTS`, default 3)
isn't exhausted. `unit_subgraph.py`'s `_route_with_retry` loops back to
`generate_fix` with a `validation_feedback` string describing exactly what
was wrong (build output, test output, which rule still fired, or the
adversarial reviewer's summary), which `sast/llm_fix.py` includes verbatim
in the next attempt's prompt so the model doesn't repeat the same mistake. A
template-tier failure is never retried this way; `generate_fix.py`'s own
exception path (a failure before `fix_tier` is even known) isn't either, for
the same reason -- see that node's docstring for why the ambiguity there
can't be resolved safely.

## Reusing session-17

This project imports session-17's sandboxed coding primitives by path
dependency (`eagv3-s17code` in `pyproject.toml`, pointed at
`../session-17/S17Code`) -- never copied, never edited:

- [`s17code/coding/workspace.py`](../session-17/S17Code/s17code/coding/workspace.py)
  -- `Workspace`: a git checkout the agent is confined to (`.open`,
  `.resolve`, `.diff`, `.changed_files`, `.reset`, `.branch`).
- [`s17code/coding/edit.py`](../session-17/S17Code/s17code/coding/edit.py)
  -- `EditLedger`, `read_code`, `apply_edit`, `create_file`: anchor-based,
  read-before-edit-enforced file editing.
- [`s17code/coding/exec.py`](../session-17/S17Code/s17code/coding/exec.py)
  -- `run_command`: no-shell, allowlisted, timeout-bounded command
  execution. `config.py` extends the allowlist (via the `S17_ALLOWED_COMMANDS`
  env var, never by editing session-17) with every registered ecosystem
  adapter's commands, plus `semgrep` (registered by `sast/__init__.py`).
- [`s17code/coding/guard.py`](../session-17/S17Code/s17code/coding/guard.py)
  -- `guard_path` / `GuardError`: protected-path refusal, invoked
  automatically inside `apply_edit`/`create_file`.
- [`s17code/coding/search.py`](../session-17/S17Code/s17code/coding/search.py)
  -- `glob_files`, `grep_code`: bounded file/content search.
- [`s17code/coding/validate.py`](../session-17/S17Code/s17code/coding/validate.py)
  -- not imported (it's coupled to session-17's own LLM gateway), but its
  *pattern* -- a fresh-context, hostile-brief, read-only validator run -- is
  reimplemented standalone in `src/remediation_agent/llm/adversarial_validator.py`
  for the (optional for SCA, mandatory for LLM-authored SAST fixes)
  adversarial pre-acceptance check.
- [`s17code/skills/`](../session-17/S17Code/s17code/skills) -- `SkillManager`,
  `GenericSkill`: markdown-file-only "skill" cheat sheets with zero access to
  any capability/authority system (a skill changes *how* the agent works, never
  *what* it's allowed to do). Reused by `sast/guidance.py` to hand the LLM
  fallback path curated, per-CWE fix guidance -- the one category so far that
  actually has an LLM doing open-ended reasoning for a skill to steer. The
  deterministic SCA path and the SAST template tier have no such reasoning
  step, which is why they don't use this mechanism.

session-17's own planner (`runtime.py`), LLM gateway client (`gateway.py`),
and capability registry (`capabilities.py`/`workers/`) are deliberately
**not** reused -- LangGraph replaces the planner role here, and this
project uses a standard pluggable chat-model interface
(`llm/provider.py`) instead of a dependency on session-17's own running
gateway service.

## Running it

Every example payload points `source.path` at a `/tmp/remediation-demo*`
directory that doesn't exist until you create it. **Do not point
`source.path` at `tests/fixtures/` directly** -- those directories have no
`.git` of their own, so `decide`'s `git branch`/`git commit` would resolve
upward to *this project's own outer git repo* and create a real branch/commit
there instead of in a sandbox. Build every isolated, throwaway checkout in
one go:

```bash
examples/setup_demos.sh
```

Then try each capability the agent has, end to end:

```bash
# SCA: deterministic version bump, no LLM call, two ecosystems
remediation-agent run-once examples/sample_payload.json         # .NET / NuGet -- Newtonsoft.Json
remediation-agent run-once examples/sca_java_log4j.json         # Java / Maven -- log4j-core (Log4Shell)

# SAST: curated rule-id template, still no LLM call
remediation-agent run-once examples/sast_template_tier.json     # exact rule id the template claims

# SAST: LLM-authored fix, curated CWE-502 guidance available
remediation-agent run-once examples/sast_llm_tier_guided.json   # same vulnerability, a rule id with no template

# SAST: LLM-authored fix, NO curated guidance -- the real capability test
remediation-agent run-once examples/sast_llm_tier_raw.json      # Java SQL injection, a class this agent has no cheat sheet for

# both categories in one run, exercising the parallel Send fan-out
remediation-agent run-once examples/multi_finding.json

# long-running: bounded-concurrency worker pool watching a directory for
# *.json payload files, writing results to <dir>/results/
remediation-agent worker --dir ./jobs --concurrency 5
```

The three SAST examples set `settings.sast.semgrep_config` to a real local
rule file under `examples/semgrep_rules/` (validated against both the
vulnerable and the fixed code before being shipped here) rather than the
default public-registry lookup, so the re-verification gate is a genuine
check, not the "zero rules loaded" no-op described above. The two
`sast_llm_tier_*` examples (and the SAST half of `multi_finding`) also need
a real `ANTHROPIC_API_KEY` (or whichever `REMEDIATION_LLM_PROVIDER` you've
configured) to actually generate a patch -- without one they still run to a
clean `fix_failed` with the auth error as the message, never a crash.

Both subcommands call `apply_command_allowlist()` first, which unions
session-17's default command allowlist with every registered ecosystem
adapter's `allowed_commands()` plus `semgrep`. This has to happen *after*
`remediation_agent.ecosystems.registry` and `remediation_agent.sast` are both
imported (`cli.py` imports both up front, for exactly this reason) --
registration is a side effect of import, so anything imported only later
(e.g. lazily inside a node) is too late to make it into the allowlist
snapshot `apply_command_allowlist()` takes.

A real deployment **should** point SAST's semgrep re-verification at the same
local ruleset the orchestrator's own Semgrep run used
(`settings.sast.semgrep_config` in the payload, a path to a local rules
file/dir) rather than the default `r/<rule-id>` public-registry lookup, which
assumes network access to `semgrep.dev` and trusts the registry to still have
a byte-identical rule under that id -- this isn't a theoretical caveat: the
project's own sample rule id doesn't resolve to any real public-registry
rule, and `semgrep_verify.py` fails closed on that case rather than
mistaking "zero rules loaded" for "genuinely fixed" (see the `paths.scanned`
check in that module).

Key environment variables (see `src/remediation_agent/config.py` for the
full list and defaults): `REMEDIATION_CONCURRENCY`, `REMEDIATION_JOB_TIMEOUT`,
`REMEDIATION_MAX_RETRIES`, `REMEDIATION_CHECKPOINT_DB`, `REMEDIATION_DEDUP_DB`,
`REMEDIATION_LLM_PROVIDER`, `REMEDIATION_LLM_MODEL`,
`REMEDIATION_SCA_LLM_FALLBACK`, `REMEDIATION_ADVERSARIAL_VALIDATION`
(opt-in for SCA; SAST's LLM-tier ignores this and always runs it),
`REMEDIATION_SAST_MAX_ATTEMPTS` (default 3; total attempts, including
retries, for an LLM-authored SAST fix a gate rejects),
`REMEDIATION_GIT_AUTHOR`, `REMEDIATION_GIT_EMAIL`.

## Explicitly out of scope

- **No PR creation.** The `decide` node's job ends at a local commit on a
  local branch (`remediation/<unit_id>`). Opening a pull request and
  pushing to a remote are handled by a separate stage outside this project;
  session-17's `run_command` allowlist for `git` deliberately has no
  `push`/`remote` subcommands.
- **No cost/budget tracking.** This project does not meter or cap LLM spend
  anywhere, including the optional/mandatory adversarial validator or the
  SAST LLM-fallback path.
- **Trivy misconfiguration/IaC and secrets findings are not yet implemented.**
  They fall through `strategies/registry.py`'s "unsupported" default cleanly
  (reported, never crash) until a dedicated strategy is written for them.
