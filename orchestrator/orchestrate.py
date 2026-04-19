"""Main pipeline.

Drives persistent agents through the research-paper lifecycle:
    literature_review → propose_experiments → run_experiments → write_paper → review_loop

Run:
    uv run python -m orchestrator.orchestrate --rounds 1
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from .agent import PersistentAgent
from .budget import MessageWindow
from .events import emit
from .run_log import setup_run_log
from .state import db, experiments_summary, list_by_status, recover_stale_running

# Replaced at runtime with a tee'd console in main_async().
# Default ensures imports and module-level Panel usage still work if someone
# imports without calling main_async (e.g. interactive debugging).
console: Console = Console()

# Cumulative API-equivalent cost across the whole run. Reported at the end.
# On Max subscription this is *not* what you're billed — just a compute gauge.
_cumulative_cost_equiv: float = 0.0

# --------------------------------------------------------------------------
# Reset policy per role — THE key design decision
# --------------------------------------------------------------------------
# hot:  agent keeps memory indefinitely
# soft: /compact between major phases (preserve skills, drop noise)
# hard: wipe session on each invocation (fresh eyes)

RESET_POLICY: dict[str, str] = {
    "literature-reviewer": "hot",              # accumulated paper knowledge
    "planner":             "hard_every_round", # fresh strategy each round
    "experimenter":        "soft_between_rounds",
    "paper-writer":        "hot",              # needs continuity across drafts
    "reviewer":            "hard_every_draft", # fresh eyes each draft
}


# --------------------------------------------------------------------------
# Agent registry
# --------------------------------------------------------------------------

ROLE_NAMES = (
    "literature-reviewer",
    "planner",
    "experimenter",
    "paper-writer",
    "reviewer",
)


def build_agents() -> dict[str, PersistentAgent]:
    """All roles, loaded from `.claude/agents/<name>.md`.

    Single source of truth: the markdown file defines the role prompt, tool
    allowlist, and model. `.claude/settings.json` further restricts at the
    permission layer. To add/change a role, edit the markdown.
    """
    return {name: PersistentAgent.from_markdown(name) for name in ROLE_NAMES}


# --------------------------------------------------------------------------
# Event rendering
# --------------------------------------------------------------------------

def render_event(agent_name: str, event: dict) -> None:
    """Render a stream-json event from `claude -p` to the console.
    All events are ALSO recorded to events.jsonl for later analysis.

    Claude Code's stream-json uses its own envelope format (not raw Anthropic API deltas):
      - system/init              — session started
      - stream_event             — real-time token deltas (needs --include-partial-messages)
      - assistant                — full content block (tool_use, text)
      - user                     — tool results
      - result                   — final summary (cost, duration, turns)
    """
    t = event.get("type")

    if t == "system":
        sub = event.get("subtype")
        if sub == "init":
            session_short = (event.get("session_id") or "?")[:8]
            console.print(f"[dim]  ↳ session {session_short}…[/dim]")

    elif t == "stream_event":
        # Real-time token stream (from --include-partial-messages).
        # Text / thinking appear here as they're generated.
        inner = event.get("event") or {}
        itype = inner.get("type")

        if itype == "content_block_start":
            block = inner.get("content_block") or {}
            btype = block.get("type")
            if btype == "thinking":
                console.print("\n[dim italic]↳ thinking:[/dim italic] ", end="")
            # tool_use is shown in the assistant event (has full input)

        elif itype == "content_block_delta":
            delta = inner.get("delta") or {}
            dtype = delta.get("type")
            if dtype == "text_delta":
                console.print(delta.get("text", ""), end="", markup=False, highlight=False)
            elif dtype == "thinking_delta":
                console.print(delta.get("thinking", ""), end="", markup=False, highlight=False,
                              style="dim italic")
            # input_json_delta (tool args streaming): skip — noisy, shown in assistant event

    elif t == "assistant":
        # Full content block arrived. Text was already streamed via stream_event;
        # we only display tool_use blocks here (they're not streamed as text).
        msg = event.get("message") or {}
        for block in msg.get("content") or []:
            if block.get("type") == "tool_use":
                name = block.get("name", "?")
                inp = block.get("input") or {}
                preview = str(inp).replace("\n", " ")[:100]
                console.print(f"\n[cyan]⚒ {name}[/cyan] [dim]{preview}[/dim]")

    elif t == "user":
        # Usually tool results — brief indicator only (full content is in events.jsonl)
        msg = event.get("message") or {}
        for block in msg.get("content") or []:
            if block.get("type") == "tool_result":
                is_err = bool(block.get("is_error"))
                icon = "[red]✗[/red]" if is_err else "[green]✓[/green]"
                console.print(f"  {icon}", end="")

    elif t == "result":
        # Claude Code reports an API-equivalent cost in `total_cost_usd` even under
        # a Max subscription. On subscription this figure is NOT what you're billed —
        # the subscription covers it. We relabel to prevent sticker-shock confusion.
        # Raw value is still kept in events.jsonl for any offline cost analysis.
        cost = event.get("total_cost_usd")
        dur = event.get("duration_ms", 0)
        turns = event.get("num_turns", 0)
        if cost is not None:
            global _cumulative_cost_equiv
            _cumulative_cost_equiv += cost
        cost_str = f" · ~${cost:.3f} api-equiv" if cost is not None else ""
        console.print(f"\n[dim]  ↳ {turns} turns · {dur / 1000:.1f}s{cost_str}[/dim]")

    elif t == "subprocess_error":
        console.print(Panel(
            f"[red]Subprocess failed (rc={event.get('returncode')})\n"
            f"{event.get('stderr', '')[:2000]}[/red]",
            title=f"{agent_name} ERROR",
        ))

    # Always record to events.jsonl regardless of whether we rendered
    emit(f"agent.{t or 'unknown'}", agent=agent_name,
         **{k: v for k, v in event.items() if k != "type"})


# --------------------------------------------------------------------------
# Phase runners
# --------------------------------------------------------------------------

async def run_agent_turn(
    agent: PersistentAgent,
    instruction: str,
    budget: MessageWindow,
) -> None:
    """Send one instruction to an agent, streaming events to console + jsonl.

    The agent's role prompt (from `.claude/agents/<name>.md`) is always
    injected — no per-call system_prompt parameter needed.
    """
    # Wait for rate-limit window if needed
    if budget.at_limit(agent.model):
        delay = budget.wait_until_free(agent.model)
        console.print(f"[yellow]Rate cap for {agent.model}. Sleeping {delay/60:.1f} min...[/yellow]")
        emit("budget.waiting", model=agent.model, seconds=delay, summary=budget.summary())
        await asyncio.sleep(delay)

    console.rule(f"[bold cyan]{agent.name}[/bold cyan]")
    emit("agent.turn_start", agent=agent.name, model=agent.model, instruction_preview=instruction[:500])
    budget.record(agent.name, agent.model)

    async for event in agent.send(instruction):
        render_event(agent.name, event)

    emit("agent.turn_end", agent=agent.name)


async def phase_literature_review(agents: dict, budget: MessageWindow) -> None:
    console.rule("[bold green]Phase: Literature Review[/bold green]")
    instruction = (
        "Review the papers in related_works/ relative to the research direction in foothold.md.\n\n"
        "If this is your first invocation for this project, process all papers. If you've run before, "
        "only ingest newly-added papers and update the review.\n\n"
        "Produce: (a) state/literature_review.md, (b) paper/sections/related.tex, "
        "(c) paper/references.bib, (d) rows in the papers table."
    )
    await run_agent_turn(agents["literature-reviewer"], instruction, budget)


async def phase_plan(agents: dict, budget: MessageWindow, round_num: int, target: int) -> None:
    """Planner designs experiments; experimenter later implements them."""
    console.rule(f"[bold green]Phase: Plan experiments (round {round_num})[/bold green]")
    # Fresh eyes each round — policy says hard_every_round, but explicit is clearer.
    await agents["planner"].hard_reset()
    emit("reset", agent="planner", kind="hard_every_round", round=round_num)

    instruction = (
        f"Round {round_num}. Read foothold.md and state/literature_review.md. "
        f"Query state/experiments.sqlite for prior experiments and lessons. "
        f"Propose up to {target} NEW experiments that advance the research question. "
        f"Do not duplicate existing proposed/completed experiments. "
        f"Use `uv run python -m orchestrator.state --propose --round {round_num} ...` "
        f"for each proposal. Return the UUIDs + a one-sentence rationale per experiment."
    )
    await run_agent_turn(agents["planner"], instruction, budget)


async def phase_run_experiments(agents: dict, budget: MessageWindow) -> None:
    """Experimenter implements and runs whatever the planner proposed."""
    pending = list_by_status("proposed")
    if not pending:
        console.print("[yellow]No proposed experiments (planner skipped or cap reached). Skipping execution.[/yellow]")
        return

    console.rule(f"[bold green]Phase: Run experiments ({len(pending)} pending)[/bold green]")
    instruction = (
        "Run all experiments currently in status='proposed'. For each: implement "
        "experiments/<id>/run.py per its hypothesis+method+metric, then invoke the "
        "run-experiment skill. Append lessons to lessons_learned. "
        "Return a summary of outcomes (IDs, pass/fail, key numbers)."
    )
    await run_agent_turn(agents["experimenter"], instruction, budget)


async def phase_write_paper(agents: dict, budget: MessageWindow) -> None:
    console.rule("[bold green]Phase: Write Paper[/bold green]")
    instruction = (
        "Update the paper based on completed experiments. If this is the first time, produce a full "
        "draft. If a review.md exists, address every required change and mark which are resolved. "
        "Compile with the compile-latex skill and fix any errors before returning."
    )
    await run_agent_turn(agents["paper-writer"], instruction, budget)


async def phase_review(agents: dict, budget: MessageWindow) -> None:
    """Reviewer is hard-reset every invocation — fresh eyes."""
    console.rule("[bold green]Phase: Review[/bold green]")
    await agents["reviewer"].hard_reset()
    emit("reset", agent="reviewer", kind="hard_every_draft")
    instruction = (
        "Read the current paper (paper/main.tex and included sections), cross-check quantitative "
        "claims against state/experiments.sqlite, and write paper/review.md with verdict, strengths, "
        "weaknesses, required changes, and optional improvements."
    )
    await run_agent_turn(agents["reviewer"], instruction, budget)


async def maybe_soft_reset(agents: dict, round_num: int) -> None:
    for name, policy in RESET_POLICY.items():
        if policy == "soft_between_rounds" and round_num > 1:
            emit("reset", agent=name, kind="soft_between_rounds", round=round_num)
            async for _ in agents[name].soft_reset():
                pass


# --------------------------------------------------------------------------
# Round loop
# --------------------------------------------------------------------------

@dataclass
class Config:
    rounds: int
    experiments_per_round: int
    max_review_iterations: int
    resume: bool


async def run_round(config: Config, round_num: int, agents: dict, budget: MessageWindow) -> None:
    console.rule(f"[bold magenta]━━━ Round {round_num}/{config.rounds} ━━━[/bold magenta]")
    emit("round.start", round=round_num, summary=experiments_summary())

    # Recover any stale `running` experiments orphaned by interrupted previous runs.
    # Default threshold: 10 minutes — real in-progress experiments never sit that long
    # without updates, since the orchestrator blocks on them.
    recoveries = recover_stale_running()
    if recoveries:
        console.print(f"[yellow]↳ recovered {len(recoveries)} stale experiment(s):[/yellow]")
        for r in recoveries:
            console.print(f"  • {r['experiment_id'][:8]} → {r['action']} [dim]({r['reason']})[/dim]")
        emit("recovery.stale_running", count=len(recoveries), actions=recoveries)

    await maybe_soft_reset(agents, round_num)
    await phase_literature_review(agents, budget)
    await phase_plan(agents, budget, round_num, config.experiments_per_round)
    await phase_run_experiments(agents, budget)

    for rev in range(1, config.max_review_iterations + 1):
        await phase_write_paper(agents, budget)
        await phase_review(agents, budget)
        # Check if reviewer approved
        review_path = Path("paper/review.md")
        if review_path.exists():
            content = review_path.read_text().lower()
            if "## verdict" in content and "approve" in content.split("## verdict")[1][:80]:
                console.print(f"[green]✓ Reviewer approved at revision {rev}.[/green]")
                emit("review.approved", round=round_num, revision=rev)
                break
        emit("review.iteration", round=round_num, revision=rev)
    else:
        console.print(f"[yellow]Max review iterations ({config.max_review_iterations}) reached.[/yellow]")
        emit("review.max_iterations", round=round_num)

    emit("round.end", round=round_num, summary=experiments_summary())


async def main_async(config: Config) -> int:
    global console  # must appear before any use/assignment of `console` in this scope

    foothold_path = Path("foothold.md")
    if not foothold_path.exists():
        console.print("[red]foothold.md not found. Create it (see README).[/red]")
        return 1

    # Set up the tee'd console — everything printed is mirrored into logs/run-*.log
    console, log_path, log_file = setup_run_log()
    console.print(f"[dim]↳ logging to {log_path}[/dim]")

    agents = build_agents()
    budget = MessageWindow()

    # Abort handling — Ctrl-C once, graceful; twice, hard exit
    stop_event = asyncio.Event()

    def handle_sigint(*_):
        if stop_event.is_set():
            console.print("[red]Double Ctrl-C — exiting now.[/red]")
            sys.exit(130)
        console.print("[yellow]Ctrl-C — finishing current turn and exiting.[/yellow]")
        stop_event.set()

    signal.signal(signal.SIGINT, handle_sigint)

    emit("orchestrator.start", rounds=config.rounds, resume=config.resume)
    console.print(Panel.fit(
        "new-paper-machine\n"
        f"rounds={config.rounds} | exp/round={config.experiments_per_round} | "
        f"max_review={config.max_review_iterations}\n"
        f"resume={config.resume}",
        style="bold cyan",
    ))

    # Ensure DB exists
    with db() as _:
        pass

    try:
        for r in range(1, config.rounds + 1):
            if stop_event.is_set():
                break
            await run_round(config, r, agents, budget)
    except Exception as e:
        emit("orchestrator.error", error=repr(e))
        raise
    finally:
        emit("orchestrator.end",
             summary=experiments_summary(),
             budget=budget.summary(),
             cumulative_cost_equiv_usd=round(_cumulative_cost_equiv, 4))
        console.print(f"\n[dim]{budget.summary()}[/dim]")
        console.print(
            f"[dim]  cumulative: ~${_cumulative_cost_equiv:.3f} api-equiv"
            f" (subscription covers this)[/dim]"
        )
        console.print(f"[dim]↳ full log saved to {log_path}[/dim]")
        log_file.close()

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="new-paper-machine orchestrator")
    parser.add_argument("--rounds", type=int, default=1, help="Number of research rounds")
    parser.add_argument("--experiments-per-round", type=int, default=5)
    parser.add_argument("--max-review-iterations", type=int, default=3)
    parser.add_argument("--resume", action="store_true",
                        help="Keep existing .agent_state/ UUIDs (default). Otherwise agents resume automatically from saved sessions.")
    args = parser.parse_args(argv)

    config = Config(
        rounds=args.rounds,
        experiments_per_round=args.experiments_per_round,
        max_review_iterations=args.max_review_iterations,
        resume=args.resume,
    )
    return asyncio.run(main_async(config))


if __name__ == "__main__":
    sys.exit(main())
