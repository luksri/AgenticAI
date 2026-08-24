#!/usr/bin/env bash
# Builds isolated, throwaway git repos for every example payload in this
# directory. Safe to re-run: each demo dir is wiped and rebuilt from the
# fixture template every time.
#
# Never point an example's source.path at tests/fixtures/ directly -- those
# directories have no .git of their own, so decide's `git branch`/`git commit`
# would resolve upward to this project's own outer git repo instead of a
# sandbox. See README.md's "Running it" section.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURES_DIR="$SCRIPT_DIR/../tests/fixtures"

make_demo() {
  local demo_dir="$1"
  local fixture_name="$2"
  rm -rf "$demo_dir"
  cp -r "$FIXTURES_DIR/$fixture_name" "$demo_dir"
  git -C "$demo_dir" init -q
  git -C "$demo_dir" config user.email "demo@example.com"
  git -C "$demo_dir" config user.name "Demo"
  git -C "$demo_dir" add -A
  git -C "$demo_dir" commit -q -m "demo baseline"
  echo "  $demo_dir  <-  $fixture_name"
}

echo "Building demo repos:"
make_demo /tmp/remediation-demo               dotnet_sample        # examples/sample_payload.json      (SCA, .NET)
make_demo /tmp/remediation-demo-sca-java       java_sample          # examples/sca_java_log4j.json      (SCA, Java/Maven)
make_demo /tmp/remediation-demo-sast-template  dotnet_sast_sample   # examples/sast_template_tier.json  (SAST, curated template)
make_demo /tmp/remediation-demo-sast-llm-guided dotnet_sast_sample  # examples/sast_llm_tier_guided.json (SAST, LLM tier + CWE guidance)
make_demo /tmp/remediation-demo-sast-llm-raw   java_sast_sample     # examples/sast_llm_tier_raw.json   (SAST, LLM tier, no guidance)
make_demo /tmp/remediation-demo-multi          dotnet_multi_sample  # examples/multi_finding.json       (SCA + SAST together)

cat <<'EOF'

Ready. Try each capability:

  remediation-agent run-once examples/sample_payload.json          # SCA, deterministic version bump
  remediation-agent run-once examples/sca_java_log4j.json          # SCA, other ecosystem (Maven)
  remediation-agent run-once examples/sast_template_tier.json      # SAST, curated rule-id template (no LLM call)
  remediation-agent run-once examples/sast_llm_tier_guided.json    # SAST, LLM-authored fix + curated CWE-502 guidance
  remediation-agent run-once examples/sast_llm_tier_raw.json       # SAST, LLM-authored fix, NO curated guidance (raw capability)
  remediation-agent run-once examples/multi_finding.json           # both categories in one run, parallel units

The two "sast_llm_tier_*" examples and the SAST half of "multi_finding" need
a real REMEDIATION_LLM_PROVIDER credential (ANTHROPIC_API_KEY by default) to
actually generate a patch, and a real `semgrep` on PATH for the
re-verification gate to do anything meaningful (`pip install semgrep`).
Without either, these still run to a clean, structured failure -- see
README.md's "Remediation categories" section for what each gate does.
EOF
