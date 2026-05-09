"""
main.py — Multi-Step LLM Agent Orchestrator
============================================
League of Legends Matchup Analyzer

This orchestrator initialises an empty state dictionary and passes it
sequentially through 5 distinct pipeline steps.  The state dict is
printed to the terminal after every step so the data-flow is fully
traceable.

Usage:
    python main.py
    python main.py "I'm playing Darius top against a Garen, enemy jungle is Lee Sin"
"""

import json
import sys
import io

# Force UTF-8 on Windows consoles (Python 3.7+)
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import agent_steps


# ──────────────────────────────────────────────
# Pretty-print helper
# ──────────────────────────────────────────────
def _print_state(state: dict, step_label: str) -> None:
    """Print a readable snapshot of the state dict to the terminal."""
    divider = "=" * 72
    print(f"\n{divider}")
    print(f"  STATE after {step_label}")
    print(divider)

    # Create a display-friendly copy (truncate very long values)
    display = {}
    for k, v in state.items():
        if isinstance(v, str) and len(v) > 500:
            display[k] = v[:500] + f"  ... (truncated, {len(v)} chars total)"
        elif isinstance(v, list) and len(v) > 5:
            display[k] = v[:3]  # show first 3 entries
            display[k].append(f"... ({len(v)} items total)")
        else:
            display[k] = v

    print(json.dumps(display, indent=2, default=str))
    print(divider + "\n")


# ──────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────
def main():
    # Collect user input
    if len(sys.argv) > 1:
        user_input = " ".join(sys.argv[1:])
    else:
        user_input = input(
            "\n Describe your matchup "
            "(e.g. 'I'm playing Darius top vs Garen, enemy jungler is Lee Sin'):\n> "
        )

    # Initialise empty state
    state: dict = {"user_input": user_input}
    _print_state(state, "Initialisation")
    # input("\n Press Enter to continue to Step 1 (Parse)...")

    # ── Step 1: Parse user input ──
    print("Step 1 / 5 — Parsing user input via LLM ...")
    state = agent_steps.parse_input(state)
    _print_state(state, "Step 1 — Parse")
    # input("\n Press Enter to continue to Step 2 (Search)...")
    # ── Step 2: Web search ──
    print("Step 2 / 5 — Searching for current-patch data ...")
    state = agent_steps.search_web(state)
    _print_state(state, "Step 2 — Search")
    # input("\n Press Enter to continue to Step 3 (Analyse)...")

    # ── Step 3: Matchup analysis ──
    print("Step 3 / 5 — Analysing matchup via LLM ...")
    state = agent_steps.analyze_matchup(state)
    _print_state(state, "Step 3 — Analyse")
    # input("\n Press Enter to continue to Step 4 (Timeline)...")

    # ── Step 4: Tactical timeline ──
    print("Step 4 / 5 — Generating minute-by-minute timeline via LLM ...")
    state = agent_steps.generate_timeline(state)
    _print_state(state, "Step 4 — Timeline")
    # input("\n Press Enter to continue to Step 5 (Format)...")

    # ── Step 5: Format report ──
    print("Step 5 / 5 — Formatting final Markdown strategy_report via LLM ...")
    state = agent_steps.format_report(state)
    _print_state(state, "Step 5 — Format")

    # Done
    print("=" * 72)
    print(f"Pipeline complete! strategy_report saved to: {state.get('strategy_report_path')}")
    print("=" * 72)


if __name__ == "__main__":
    main()
