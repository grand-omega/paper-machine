"""SQLite-backed experiment state.

Single source of truth for experiment rows, paper metadata, and lessons.
Invoked both from Python orchestrator AND via `python -m orchestrator.state ...`
from inside the run-experiment skill.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid as uuid_mod
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

DB_PATH = Path("state/experiments.sqlite")

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id                TEXT PRIMARY KEY,
    round             INTEGER NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('proposed','running','completed','failed')),
    hypothesis        TEXT NOT NULL,
    method            TEXT NOT NULL,
    metric            TEXT,
    baseline_value    REAL,
    treatment_value   REAL,
    effect_size       REAL,
    confidence        TEXT,
    notes             TEXT,
    error_excerpt     TEXT,
    raw_results_path  TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS papers (
    citation_key           TEXT PRIMARY KEY,
    title                  TEXT NOT NULL,
    year                   INTEGER,
    venue                  TEXT,
    summary_1line          TEXT,
    relevance_to_foothold  TEXT,
    cited_in_paper         INTEGER DEFAULT 0,
    ingested_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lessons_learned (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id   TEXT,
    agent           TEXT NOT NULL,
    text            TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id)
);

CREATE INDEX IF NOT EXISTS idx_experiments_status ON experiments(status);
CREATE INDEX IF NOT EXISTS idx_experiments_round ON experiments(round);
"""


@contextmanager
def db(path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# -------- Experiments --------


def propose_experiment(
    *, round_num: int, hypothesis: str, method: str, metric: str | None = None
) -> str:
    eid = str(uuid_mod.uuid4())
    now = _now()
    with db() as conn:
        conn.execute(
            """INSERT INTO experiments
               (id, round, status, hypothesis, method, metric, created_at, updated_at)
               VALUES (?, ?, 'proposed', ?, ?, ?, ?, ?)""",
            (eid, round_num, hypothesis, method, metric, now, now),
        )
    return eid


def set_status(eid: str, status: str) -> None:
    assert status in {"proposed", "running", "completed", "failed"}
    with db() as conn:
        conn.execute(
            "UPDATE experiments SET status=?, updated_at=? WHERE id=?",
            (status, _now(), eid),
        )


def complete_experiment(eid: str, results: dict[str, Any], raw_path: str | None = None) -> None:
    with db() as conn:
        conn.execute(
            """UPDATE experiments
               SET status='completed',
                   metric          = COALESCE(?, metric),
                   baseline_value  = ?,
                   treatment_value = ?,
                   effect_size     = ?,
                   confidence      = ?,
                   notes           = ?,
                   raw_results_path= ?,
                   updated_at      = ?
               WHERE id=?""",
            (
                results.get("metric"),
                results.get("baseline_value"),
                results.get("treatment_value"),
                results.get("effect_size"),
                results.get("confidence"),
                results.get("notes"),
                raw_path,
                _now(),
                eid,
            ),
        )


def fail_experiment(eid: str, error_excerpt: str, raw_path: str | None = None) -> None:
    with db() as conn:
        conn.execute(
            """UPDATE experiments
               SET status='failed', error_excerpt=?, raw_results_path=?, updated_at=?
               WHERE id=?""",
            (error_excerpt, raw_path, _now(), eid),
        )


def get_experiment(eid: str) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()
        return dict(row) if row else None


def list_by_status(status: str) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM experiments WHERE status=? ORDER BY round, created_at", (status,)
        ).fetchall()
    return [dict(r) for r in rows]


def experiments_summary() -> dict[str, int]:
    with db() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM experiments GROUP BY status"
        ).fetchall()
    return {r["status"]: r["n"] for r in rows}


def recover_stale_running(stale_after_seconds: int = 600) -> list[dict[str, Any]]:
    """Recover `running` experiments orphaned by an interrupted previous run.

    For each `running` row whose updated_at is older than `stale_after_seconds`:
      - If `agent_results/<id>/results.json` exists and parses → auto-complete it
      - Otherwise → mark as `failed` with an orphaning note

    Returns a list of {experiment_id, action, reason} dicts describing what was done.
    Safe to call on every orchestrator start — no-op if no stale rows exist.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    with db() as conn:
        stale = conn.execute(
            "SELECT id, hypothesis, updated_at FROM experiments "
            "WHERE status='running' AND updated_at < ?",
            (cutoff_str,),
        ).fetchall()

    actions: list[dict[str, Any]] = []
    for row in stale:
        eid = row["id"]
        results_path = Path(f"agent_results/{eid}/results.json")
        raw_log = Path(f"agent_results/{eid}/run.log")

        if results_path.exists():
            try:
                results = json.loads(results_path.read_text())
                complete_experiment(
                    eid,
                    results,
                    raw_path=str(raw_log) if raw_log.exists() else None,
                )
                add_lesson(
                    agent="orchestrator",
                    experiment_id=eid,
                    text="Recovered after interrupted run: results.json was on disk, auto-completed.",
                )
                actions.append({
                    "experiment_id": eid,
                    "action": "auto_completed",
                    "reason": "results.json found on disk",
                })
            except (json.JSONDecodeError, OSError) as e:
                fail_experiment(
                    eid,
                    error_excerpt=f"Recovery failed parsing results.json: {e}",
                    raw_path=str(raw_log) if raw_log.exists() else None,
                )
                actions.append({
                    "experiment_id": eid,
                    "action": "marked_failed",
                    "reason": f"results.json unreadable: {e}",
                })
        else:
            fail_experiment(
                eid,
                error_excerpt="Orphaned — interrupted mid-run; no results.json on disk.",
                raw_path=str(raw_log) if raw_log.exists() else None,
            )
            add_lesson(
                agent="orchestrator",
                experiment_id=eid,
                text="Marked as failed: left in `running` by an interrupted run; no results.json produced.",
            )
            actions.append({
                "experiment_id": eid,
                "action": "marked_failed",
                "reason": "orphaned without results",
            })

    return actions


# -------- Lessons --------


def add_lesson(*, agent: str, text: str, experiment_id: str | None = None) -> None:
    with db() as conn:
        conn.execute(
            """INSERT INTO lessons_learned (experiment_id, agent, text, created_at)
               VALUES (?, ?, ?, ?)""",
            (experiment_id, agent, text, _now()),
        )


def recent_lessons(limit: int = 20) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM lessons_learned ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# -------- CLI (invoked by run-experiment skill) --------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment state helpers")

    parser.add_argument("--get", metavar="ID", help="Print experiment row as JSON")
    parser.add_argument("--set-status", nargs=2, metavar=("ID", "STATUS"))
    parser.add_argument("--complete", metavar="ID")
    parser.add_argument("--results", metavar="JSON_PATH", help="results.json for --complete")
    parser.add_argument("--raw-path", metavar="PATH", help="raw log path")
    parser.add_argument("--fail", metavar="ID")
    parser.add_argument("--error-excerpt", metavar="TEXT")
    parser.add_argument("--add-lesson", action="store_true")
    parser.add_argument("--experiment", metavar="ID", help="for --add-lesson")
    parser.add_argument("--agent", metavar="NAME", default="unknown", help="for --add-lesson")
    parser.add_argument("--text", metavar="TEXT", help="for --add-lesson")
    parser.add_argument("--propose", action="store_true")
    parser.add_argument("--round", type=int, default=1)
    parser.add_argument("--hypothesis", metavar="TEXT")
    parser.add_argument("--method", metavar="TEXT")
    parser.add_argument("--metric", metavar="TEXT")
    parser.add_argument("--dump", action="store_true", help="dump all experiments")

    args = parser.parse_args(argv)

    if args.get:
        row = get_experiment(args.get)
        print(json.dumps(row, indent=2) if row else "null")
        return 0

    if args.set_status:
        eid, status = args.set_status
        set_status(eid, status)
        return 0

    if args.complete:
        if not args.results:
            print("--complete requires --results", file=sys.stderr)
            return 2
        results = json.loads(Path(args.results).read_text())
        complete_experiment(args.complete, results, raw_path=args.raw_path)
        return 0

    if args.fail:
        fail_experiment(args.fail, args.error_excerpt or "", raw_path=args.raw_path)
        return 0

    if args.add_lesson:
        if not args.text:
            print("--add-lesson requires --text", file=sys.stderr)
            return 2
        add_lesson(agent=args.agent, text=args.text, experiment_id=args.experiment)
        return 0

    if args.propose:
        if not args.hypothesis or not args.method:
            print("--propose requires --hypothesis and --method", file=sys.stderr)
            return 2
        eid = propose_experiment(
            round_num=args.round,
            hypothesis=args.hypothesis,
            method=args.method,
            metric=args.metric,
        )
        print(eid)
        return 0

    if args.dump:
        with db() as conn:
            for row in conn.execute("SELECT * FROM experiments ORDER BY round, created_at"):
                print(json.dumps(dict(row), indent=2))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
