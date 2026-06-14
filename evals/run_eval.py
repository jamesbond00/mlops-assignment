"""Eval runner using execution accuracy.

Reads evals/eval_set.jsonl, calls the agent at AGENT_URL on each question,
then compares the agent's SQL output to the gold SQL by *executed rows*
(canonicalized: sorted, stringified, None-coerced to empty).

Helpers (run_sql / canonicalize / matches) are provided. You implement
eval_one() and summarize().

Run:
    uv run python evals/run_eval.py --out results/eval_baseline.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVAL_FILE = ROOT / "evals" / "eval_set.jsonl"
DEFAULT_OUT_FILE = ROOT / "results" / "eval_baseline.json"
DB_DIR = ROOT / "data" / "bird"
AGENT_URL_DEFAULT = "http://localhost:8001/answer"


# ---------- Helpers (provided) -----------------------------------------

def run_sql(db_id: str, sql: str, timeout: float = 5.0) -> tuple[bool, list[tuple] | None, str | None]:
    """Run sql against db_id in read-only mode. Returns (ok, rows, error)."""
    path = DB_DIR / f"{db_id}.sqlite"
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout) as conn:
            cur = conn.execute(sql)
            rows = cur.fetchall()
            return True, rows, None
    except Exception as e:  # noqa: BLE001
        return False, None, f"{type(e).__name__}: {e}"


def canonicalize(rows: list[tuple] | None) -> list[tuple] | None:
    """Sort rows; coerce cells to str; None -> ''."""
    if rows is None:
        return None
    return sorted(tuple("" if c is None else str(c) for c in row) for row in rows)


def matches(gold_rows: list[tuple] | None, pred_rows: list[tuple] | None) -> bool:
    if gold_rows is None or pred_rows is None:
        return False
    return canonicalize(gold_rows) == canonicalize(pred_rows)


# ---------- Implement these (Phase 5) ----------------------------------

def eval_one(question: dict, agent_url: str) -> dict:
    """Score one question. Return a dict capturing per-iteration correctness."""
    db_id = question["db_id"]
    gold_ok, gold_rows, gold_error = run_sql(db_id, question["gold_sql"])

    started = time.monotonic()
    agent_error: str | None = None
    agent_response: dict = {}
    try:
        response = httpx.post(
            agent_url,
            json={
                "question": question["question"],
                "db": db_id,
                "tags": {
                    "phase": "5",
                    "run": "eval_baseline",
                    "db": db_id,
                },
            },
            timeout=180.0,
        )
        response.raise_for_status()
        agent_response = response.json()
    except Exception as e:  # noqa: BLE001
        agent_error = f"{type(e).__name__}: {e}"

    latency = time.monotonic() - started
    history = agent_response.get("history", []) if agent_response else []
    sql_attempts = [
        h.get("sql", "")
        for h in history
        if h.get("node") in {"generate_sql", "revise"} and h.get("sql")
    ]
    if not sql_attempts and agent_response.get("sql"):
        sql_attempts = [agent_response["sql"]]

    iteration_results = []
    for idx, sql in enumerate(sql_attempts, 1):
        pred_ok, pred_rows, pred_error = run_sql(db_id, sql)
        correct = gold_ok and pred_ok and matches(gold_rows, pred_rows)
        iteration_results.append({
            "iteration": idx,
            "sql": sql,
            "execution_ok": pred_ok,
            "execution_error": pred_error,
            "correct": correct,
        })

    final_correct = iteration_results[-1]["correct"] if iteration_results else False
    return {
        "question": question["question"],
        "db_id": db_id,
        "gold_sql": question["gold_sql"],
        "gold_execution_ok": gold_ok,
        "gold_execution_error": gold_error,
        "agent_ok": agent_response.get("ok", False) if agent_response else False,
        "agent_error": agent_error or agent_response.get("error"),
        "final_sql": agent_response.get("sql", "") if agent_response else "",
        "final_correct": final_correct,
        "iterations": agent_response.get("iterations", len(iteration_results)) if agent_response else 0,
        "latency_seconds": latency,
        "iteration_results": iteration_results,
        "history": history,
    }


def summarize(results: list[dict]) -> dict:
    """Aggregate per-question results.

    Per-iteration carry-forward: if the agent terminated at iteration j < k
    (verify said ok at j, or it hit MAX_ITERATIONS at j < k), treat the
    question's iteration-k result as identical to its iteration-j result.
    The agent stopped emitting; whatever it had at termination is what
    would have been served had we polled at iteration k.
    """
    total = len(results)
    if total == 0:
        return {
            "total": 0,
            "correct": 0,
            "accuracy": 0.0,
            "per_iteration": {},
            "avg_iterations": 0.0,
            "avg_latency_seconds": 0.0,
            "agent_errors": 0,
        }

    max_iter = max((len(r.get("iteration_results", [])) for r in results), default=0)
    per_iteration: dict[str, dict] = {}
    for iteration in range(1, max_iter + 1):
        correct = 0
        attempted = 0
        for result in results:
            iter_results = result.get("iteration_results", [])
            if not iter_results:
                continue
            attempted += 1
            carried = iter_results[min(iteration, len(iter_results)) - 1]
            correct += int(bool(carried.get("correct")))
        per_iteration[str(iteration)] = {
            "correct": correct,
            "attempted": attempted,
            "accuracy": correct / total,
        }

    final_correct = sum(int(bool(r.get("final_correct"))) for r in results)
    return {
        "total": total,
        "correct": final_correct,
        "accuracy": final_correct / total,
        "per_iteration": per_iteration,
        "avg_iterations": sum(float(r.get("iterations", 0)) for r in results) / total,
        "avg_latency_seconds": sum(float(r.get("latency_seconds", 0.0)) for r in results) / total,
        "agent_errors": sum(1 for r in results if r.get("agent_error")),
        "gold_execution_errors": sum(1 for r in results if not r.get("gold_execution_ok")),
    }


# ---------- Main (provided) --------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_FILE)
    parser.add_argument("--agent-url", default=AGENT_URL_DEFAULT)
    args = parser.parse_args()

    questions = [json.loads(line) for line in args.eval_set.read_text().splitlines() if line.strip()]
    print(f"Loaded {len(questions)} eval questions from {args.eval_set}")

    results: list[dict] = []
    t0 = time.monotonic()
    for i, q in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {q['db_id']}: {q['question'][:60]}...", flush=True)
        results.append(eval_one(q, args.agent_url))
    elapsed = time.monotonic() - t0

    summary = summarize(results)
    out = {
        "summary": summary,
        "wall_clock_seconds": elapsed,
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f"Wrote {args.out}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
