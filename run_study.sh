#!/usr/bin/env bash
# Scenario 02 — pricing duopoly. Runs the pre-registered study.
#
#   ./run_study.sh [runs_per_condition] [model]
#
# Resumable: counts existing traces per condition and only runs the shortfall,
# so an interrupted study is restarted by re-running this.

set -euo pipefail

RUNS="${1:-5}"
MODEL="${2:-claude-haiku-4-5}"
CONDITIONS=(pricing-blind pricing-own-outcome pricing-full-observation pricing-communication)

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "ANTHROPIC_API_KEY not set. Run: set -a; source .env; set +a" >&2
    exit 1
fi

echo "study: ${RUNS} runs x ${#CONDITIONS[@]} conditions on ${MODEL}"
echo

for condition in "${CONDITIONS[@]}"; do
    dir="runs/${condition}/${MODEL}"
    have=$(find "${dir}" -name '*.jsonl' 2>/dev/null | wc -l)
    need=$(( RUNS - have ))

    if (( need <= 0 )); then
        echo "${condition}: ${have} traces already, skipping"
        continue
    fi

    echo "${condition}: ${have} traces, running ${need} more"
    for (( i = 1; i <= need; i++ )); do
        printf '  run %d/%d ... ' "$i" "$need"
        # A failed run must not abort the study — record it and carry on.
        if uv run python -m marionette "$condition" --model "$MODEL" >/dev/null 2>&1; then
            echo "ok"
        else
            echo "FAILED (excluded per pre-registration; re-run to replace)"
        fi
    done
    echo
done

echo "done. analyse with:  python3 aggregate.py ${MODEL}"
