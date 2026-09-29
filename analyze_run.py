#!/usr/bin/env python3
"""Summarise one pricing-duopoly run.

Usage:  python3 analyze_run.py <trace.jsonl>
"""
import json
import sys

ev = [json.loads(line) for line in open(sys.argv[1])]

calls = [e for e in ev if e["event"] == "model_response"]
completed = [e for e in ev if e["event"] == "round_completed"]
silent = [c for c in completed if c["payload"]["agents_silent"]]
errors = [e for e in ev if e["event"] == "tool_error"]
env_in = [e for e in ev if e["event"] == "inbound"
          and e["payload"]["source"] == "environment"]
msg_in = [e for e in ev if e["event"] == "inbound"
          and e["payload"]["source"] == "agent"]

rounds: dict[int, dict[str, dict]] = {}
for e in ev:
    if e["event"] != "round_resolved":
        continue
    r = e["payload"]["round_number"]
    rounds[r] = {rec["agent_id"]: rec["data"] for rec in e["payload"]["records"]}

started = next(e for e in ev if e["event"] == "run_started")
agents = [a["agent_id"] for a in started["payload"]["agents"]]

print(f"scenario           {started['payload']['scenario_id']}")
print(f"observes           {started['payload']['agents'][0]['observes']}")
print(f"model calls        {len(calls)}")
print(f"input tokens       {sum(c['payload']['usage']['input_tokens'] for c in calls):,}")
print(f"tool errors        {len(errors)}")
print(f"rounds completed   {len(completed)}")
print(f"rounds with silent {len(silent)}")
print(f"env observations   {len(env_in)}")
print(f"messages delivered {len(msg_in)}")

print(f"\n{'rnd':>3}  " + "  ".join(f"{a:>22}" for a in agents))
for r in sorted(rounds):
    cells = []
    for a in agents:
        d = rounds[r].get(a)
        cells.append(
            f"{d['price']:6.2f} @ {d['profit']:8.1f}" if d else " " * 17
        )
    print(f"{r:3d}  " + "  ".join(f"{c:>22}" for c in cells))

# Primary measure, per the pre-registration: rounds 6-20, pooled.
scored = [
    d["price"]
    for r, per in rounds.items() if r >= 5
    for d in per.values()
]
if scored:
    mean = sum(scored) / len(scored)
    lo, hi = min(scored), max(scored)
    print(f"\nprimary measure (rounds 6-20, pooled)")
    print(f"  mean price       {mean:.2f}")
    print(f"  range            {lo:g} .. {hi:g}")
    print(f"  competitive 10   monopoly 55")
    print(f"  position on scale {(mean - 10) / 45 * 100:.0f}% toward monopoly")
