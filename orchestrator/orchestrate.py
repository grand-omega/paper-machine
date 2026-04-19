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
from .state import db, experiments_summary, list_by_status

console = Console()

# --------------------------------------------------------------------------
# Reset policy per role — THE key design decision
# --------------------------------------------------------------------------
# hot:  agent keeps memory indefinitely
# soft: /compact between major phases (preserve skills, drop noise)
# hard: wipe session on each invocation (fresh eyes)

RESET_POLICY: dict[str, str] = {
    "literature-reviewer": "hot",              # accumulated paper knowledge
    "experimenter":        "soft_between_rounds",
    "paper-writer":        "hot",              # needs continuity across drafts
    "reviewer":            "hard_every_draft", # fresh eyes
}


# --------------------------------------------------------------------------
# Agent registry
# --------------------------------------------------------------------------

def build_agents() -> dict[str, PersistentAgent]:
    """All four roles. Tool allowlists are additionally enforced by .claude/settings.json."""
    return {
        "literature-reviewer": PersistentAgent(
            name="literature-reviewer",
            allowed_tools=["Read", "Glob", "Grep", "Write", "Edit", "Bash"],
            model="sonnet",  # reading and summarizing — sonnet is fine
        ),
        "experimenter": PersistentAgent(
            name="experimenter",
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Skill"],
            model="opus",   # actual engineering — keep opus
        ),
        "paper-writer": PersistentAgent(
            name="paper-writer",
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Skill"],
            model="opus",
        ),
        "reviewer": PersistentAgent(
            name="reviewer",
            allowed_tools=["Read", "Glob", "Grep", "Write"],  # write only review.md
            model="opus",
        ),
    }


# --------------------------------------------------------------------------
# Event rendering
# --------------------------------------------------------------------------

def render_event(agent_name: str, event: dict) -> None:
    """Pretty-print a stream-json event from Claude Code to the console.
    All events are ALSO recorded to events.jsonl for later analysis.
    """
    t = event.get("type")
    if t == "content_block_delta":
        delta = event.get("delta") or {}
        if delta.get("type") == "text_delta":
            console.print(delta.get("text", ""), end="", markup=False, highlight=False)
    elif t == "tool_use":
        name = event.get("name", "?")
        console.print(f"\n[dim][{agent_name}: tool_use {name}][/dim]")
    elif t == "tool_result":
        # Suppress verbose tool output; events.jsonl captures it
        pass
    elif t == "message_stop":
        console.print()  # newline
    elif t == "subprocess_error":
        console.print(Panel(
            f"[red]Subprocess failed (rc={event.get('returncode')})\n"
            f"{event.get('stderr', '')[:2000]}[/red]",
            title=f"{agent_name} ERROR",
        ))

    # Always record
    emit(f"agent.{t or 'unknown'}", agent=agent_name, **{k: v for k, v in event.items() if k != "type"})


# --------------------------------------------------------------------------
# Phase runners
# --------------------------------------------------------------------------

async def run_agent_turn(
    agent: PersistentAgent,
    instruction: str,
    budget: MessageWindow,
    *,
    system_prompt: str | None = None,
) -> None:
    """Send one instruction to an agent, streaming events to console + jsonl."""
    # Wait for rate-limit window if needed
    if budget.at_limit(agent.model):
        delay = budget.wait_until_free(agent.model)
        console.print(f"[yellow]Rate cap for {agent.model}. Sleeping {delay/60:.1f} min...[/yellow]")
        emit("budget.waiting", model=agent.model, seconds=delay, summary=budget.summary())
        await asyncio.sleep(delay)

    console.rule(f"[bold cyan]{agent.name}[/bold cyan]")
    emit("agent.turn_start", agent=agent.name, model=agent.model, instruction_preview=instruction[:500])
    budget.record(agent.name, agent.model)

    async for event in agent.send(instruction, system_prompt=system_prompt):
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


async def phase_propose_experiments(agents: dict, budget: MessageWindow, round_num: int, target: int) -> None:
    console.rule(f"[bold green]Phase: Propose Experiments (round {round_num})[/bold green]")
    instruction = (
        f"Round {round_num}. Propose up to {target} NEW experiments that advance the foothold.\n\n"
        f"First, query state/experiments.sqlite to see what's already been proposed or completed — "
        f"do not duplicate. Then insert new rows with status='proposed' via "
        f"`python -m orchestrator.state --propose --round {round_num} --hypothesis '...' --method '...' --metric '...'`.\n\n"
        f"Return the list of proposed experiment IDs."
    )
    await run_agent_turn(agents["experimenter"], instruction, budget)


async def phase_run_experiments(agents: dict, budget: MessageWindow) -> None:
    pending = list_by_status("proposed")
    if not pending:
        console.print("[yellow]No proposed experiments. Skipping execution.[/yellow]")
        return

    console.rule(f"[bold green]Phase: Run Experiments ({len(pending)} pending)[/bold green]")
    # The experimenter agent handles its own loop across experiments — we just
    # nudge it. It uses the run-experiment skill for each.
    instruction = (
        "Run all experiments currently in status='proposed'. For each, use the run-experiment skill. "
        "Accumulate lessons in lessons_learned as you go. Return a summary of outcomes."
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

    await maybe_soft_reset(agents, round_num)
    await phase_literature_review(agents, budget)
    await phase_propose_experiments(agents, budget, round_num, config.experiments_per_round)
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
    foothold_path = Path("foothold.md")
    if not foothold_path.exists():
        console.print("[red]foothold.md not found. Create it (see README).[/red]")
        return 1

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
        emit("orchestrator.end", summary=experiments_summary(), budget=budget.summary())
        console.print(f"\n[dim]{budget.summary()}[/dim]")

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
