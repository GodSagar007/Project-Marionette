"""Command-line entry point for Marionette.

Lets you run a scenario with `uv run python -m marionette <scenario> --model <id>`.

For thread one, scenarios are looked up from a small in-process registry.
When scenario tooling matures (loading from scenarios/NN-name/ directories,
parsing SCENARIO.md, verifying frozen hashes), that registry replaces this dict.
"""

import argparse
import sys
from pathlib import Path

from marionette.runner import Scenario, run
from marionette.scenarios.echo_smoke import ECHO_SMOKE

# All scenarios available to the CLI, keyed by their public id.
SCENARIOS: dict[str, Scenario] = {
    ECHO_SMOKE.id: ECHO_SMOKE,
}


def main() -> int:
    """Parse arguments, run the named scenario, print a summary.

    Returns:
        0 on a successful run, 1 on an aborted run or invalid scenario id.
    """
    parser = argparse.ArgumentParser(
        prog="marionette",
        description="Run a Marionette scenario end-to-end against a real model.",
    )
    parser.add_argument(
        "scenario",
        help=f"Scenario id to run. Available: {', '.join(sorted(SCENARIOS))}",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Model identifier (e.g. claude-3-7-sonnet-20250219).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("runs"),
        help="Directory under which traces are written. Default: ./runs/",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Seed value recorded in run_started for reproducibility. Default: 0",
    )

    args = parser.parse_args()

    scenario = SCENARIOS.get(args.scenario)
    if scenario is None:
        print(
            f"error: unknown scenario {args.scenario!r}. "
            f"Available: {', '.join(sorted(SCENARIOS))}",
            file=sys.stderr,
        )
        return 1

    result = run(
        scenario=scenario,
        model=args.model,
        output_root=args.output_root,
        seed=args.seed,
    )

    # Summary line — humans read this; programs parse the RunResult or the trace.
    print(
        f"{result.status}: {result.run_id} "
        f"({result.event_count} events, {result.duration_ms}ms) "
        f"→ {result.trace_path}",
        file=sys.stderr,
    )
    if result.abort_reason is not None:
        print(f"  abort_reason: {result.abort_reason}", file=sys.stderr)

    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
