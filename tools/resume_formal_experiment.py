from __future__ import annotations

import csv
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

EXP_ROOT = Path("/root/multi-agent/experiment_runs/2026-04-27-cgs-baseline-freeze-v1")
SAMPLES = EXP_ROOT / "samples" / "final_sample_set.jsonl"
ROUNDS = EXP_ROOT / "rounds"
INDEX_JSONL = EXP_ROOT / "indexes" / "qa_index.jsonl"
INDEX_CSV = EXP_ROOT / "indexes" / "qa_index.csv"
SUMMARY_MD = EXP_ROOT / "summaries" / "experiment_summary.md"
APPLY_CAPTURES = EXP_ROOT / "environment" / "repair_apply_captures"
TESTING_DATA = Path("/root/multi-agent/nl2cypher/data/testing_service")
REPAIR_DATA = Path("/root/multi-agent/nl2cypher/data/repair_service/analyses")
LOG_PATHS = {
    "cypher-generator-agent": Path("/tmp/cgs_8000.log"),
    "runtime-results-service": Path("/tmp/runtime_8001.log"),
    "testing-agent": Path("/tmp/testing_8003.log"),
    "repair-agent": Path("/tmp/repair_agent_8002.log"),
    "qa-agent": Path("/tmp/qa_8020.log"),
}
BASES = {
    "cgs": "http://127.0.0.1:8000",
    "testing": "http://127.0.0.1:8003",
}
LEVELS = ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"]
ROUND_IDS = {level: f"round-{i:03d}-{level}" for i, level in enumerate(LEVELS, start=1)}
TERMINAL_STATES = {
    "passed",
    "issue_ticket_created",
    "repair_submission_failed",
    "semantic_review_invalid",
    "tugraph_execution_failed",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso_to_dt(value: str | None):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def ms_between(start: str | None, end: str | None) -> int | None:
    s = iso_to_dt(start)
    e = iso_to_dt(end)
    if not s or not e:
        return None
    return int((e - s).total_seconds() * 1000)


def safe_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def write_json(path: Path, payload: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def list_attempt_files(qa_id: str):
    return sorted(TESTING_DATA.joinpath("submission_attempts").glob(f"{qa_id}__attempt_*.json"))


def latest_attempt(qa_id: str):
    files = list_attempt_files(qa_id)
    if not files:
        return None, None
    path = max(files, key=lambda p: int(p.stem.split("__attempt_")[-1]))
    return path, safe_json(path)


def poll_terminal(qa_id: str, timeout_s: int = 240):
    start = time.time()
    while time.time() - start < timeout_s:
        path, data = latest_attempt(qa_id)
        if data:
            state = data.get("state")
            if state in TERMINAL_STATES:
                return path, data
        time.sleep(2)
    return latest_attempt(qa_id)


def grep_logs(qa_id: str):
    out = {}
    for name, path in LOG_PATHS.items():
        if not path.exists():
            out[name] = []
            continue
        try:
            lines = [line.rstrip("\n") for line in path.read_text(errors="ignore").splitlines() if qa_id in line]
            out[name] = lines[-20:]
        except Exception as exc:
            out[name] = [f"log_read_error: {exc}"]
    return out


def find_repair_analysis(ticket_id: str | None):
    if not ticket_id:
        return None, None
    exact = REPAIR_DATA / f"analysis-{ticket_id}.json"
    if exact.exists():
        return exact, safe_json(exact)
    cands = sorted(REPAIR_DATA.glob(f"analysis-{ticket_id}*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if cands:
        return cands[0], safe_json(cands[0])
    return None, None


def find_apply_capture(qa_id: str):
    p = APPLY_CAPTURES / f"{qa_id}.json"
    if p.exists():
        return p, safe_json(p)
    return None, None


def round_health(round_dir: Path):
    out = {}
    for name, url in {
        "8000": "http://127.0.0.1:8000/health",
        "8001": "http://127.0.0.1:8001/health",
        "8002": "http://127.0.0.1:8002/health",
        "8003": "http://127.0.0.1:8003/health",
        "8010": "http://127.0.0.1:8010/health",
        "8020": "http://127.0.0.1:8020/health",
    }.items():
        try:
            r = requests.get(url, timeout=10)
            try:
                body = r.json()
            except Exception:
                body = r.text
            out[name] = {"status_code": r.status_code, "body": body}
        except Exception as exc:
            out[name] = {"error": str(exc)}
    write_json(round_dir / "health.resume.json", out)


def failure_stage(submission: dict[str, Any] | None) -> str:
    if not submission:
        return "generator_request_failed"
    state = submission.get("state")
    if state == "passed":
        return "passed"
    if state == "semantic_review_invalid":
        return "semantic_review_invalid"
    if state == "issue_ticket_created":
        return "issue_ticket_created"
    if state == "repair_submission_failed":
        return "repair_submission_failed"
    if state == "tugraph_execution_failed":
        return "tugraph_execution_failed"
    execution = submission.get("execution") or {}
    if execution.get("success") is False:
        return "tugraph_execution_failed"
    return state or "unknown"


def existing_result_stage(qa_dir: Path) -> str | None:
    data = safe_json(qa_dir / "testing_result.json")
    if not data:
        return None
    stage = data.get("failure_stage")
    if stage:
        return stage
    submission = data.get("submission")
    return failure_stage(submission)


def build_timing(
    qa_id: str,
    round_id: str,
    start_iso: str,
    end_iso: str,
    submission: dict[str, Any] | None,
    issue_ticket_path: Path | None,
    repair_analysis_path: Path | None,
    apply_capture_path: Path | None,
):
    received_at = submission.get("received_at") if submission else None
    updated_at = submission.get("updated_at") if submission else None
    execution = submission.get("execution") or {} if submission else {}
    issue_time = (
        datetime.fromtimestamp(issue_ticket_path.stat().st_mtime, tz=timezone.utc).isoformat()
        if issue_ticket_path and issue_ticket_path.exists()
        else None
    )
    repair_time = None
    if repair_analysis_path and repair_analysis_path.exists():
        repair_data = safe_json(repair_analysis_path) or {}
        repair_time = repair_data.get("created_at") or datetime.fromtimestamp(
            repair_analysis_path.stat().st_mtime, tz=timezone.utc
        ).isoformat()
    apply_time = (
        datetime.fromtimestamp(apply_capture_path.stat().st_mtime, tz=timezone.utc).isoformat()
        if apply_capture_path and apply_capture_path.exists()
        else None
    )
    repair_finished = apply_time or repair_time or issue_time
    return {
        "qa_id": qa_id,
        "round_id": round_id,
        "timing_status": "partial",
        "qa_agent_started_at": start_iso,
        "qa_agent_finished_at": end_iso,
        "cypher_generator_started_at": start_iso,
        "cypher_generator_finished_at": received_at,
        "testing_agent_started_at": received_at,
        "testing_agent_finished_at": updated_at,
        "repair_agent_started_at": issue_time or repair_time,
        "repair_agent_finished_at": repair_finished,
        "qa_dispatch_started_at": start_iso,
        "qa_dispatch_finished_at": end_iso,
        "generator_started_at": start_iso,
        "generator_finished_at": received_at,
        "testing_submission_received_at": received_at,
        "tugraph_execution_started_at": received_at,
        "tugraph_execution_finished_at": received_at,
        "semantic_review_started_at": received_at,
        "semantic_review_finished_at": updated_at,
        "repair_started_at": issue_time or repair_time,
        "repair_finished_at": repair_finished,
        "total_elapsed_ms": ms_between(start_iso, repair_finished or updated_at or end_iso),
        "qa_agent_elapsed_ms": ms_between(start_iso, end_iso),
        "cypher_generator_elapsed_ms": ms_between(start_iso, received_at),
        "testing_agent_elapsed_ms": ms_between(received_at, updated_at),
        "repair_agent_elapsed_ms": ms_between(issue_time or repair_time, repair_finished),
        "generator_elapsed_ms": ms_between(start_iso, received_at),
        "tugraph_execution_elapsed_ms": execution.get("elapsed_ms"),
        "semantic_review_elapsed_ms": None,
        "repair_elapsed_ms": ms_between(issue_time or repair_time, repair_finished),
        "notes": {
            "testing_agent_elapsed_basis": "submission.received_at to submission.updated_at",
            "repair_agent_elapsed_basis": "issue_ticket/analysis time to apply capture or analysis time",
            "cypher_generator_elapsed_basis": "formal runner dispatch start to testing submission received",
            "dispatch_mode": "resume_runner_skip_completed",
        },
    }


def append_index(row: dict[str, Any]):
    INDEX_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with INDEX_JSONL.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def rebuild_csv():
    rows = [json.loads(line) for line in INDEX_JSONL.open() if line.strip()] if INDEX_JSONL.exists() else []
    if not rows:
        return
    fieldnames = sorted({k for row in rows for k in row.keys()})
    with INDEX_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def rebuild_unique_index():
    rows = [json.loads(line) for line in INDEX_JSONL.open() if line.strip()] if INDEX_JSONL.exists() else []
    unique = {}
    for row in rows:
        unique[(row.get("round_id"), row.get("qa_id"))] = row
    with INDEX_JSONL.open("w") as f:
        for row in unique.values():
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    rebuild_csv()


def collect_existing_round_stats(round_dir: Path):
    stats = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "issue_tickets": 0,
        "repair_suggestions": 0,
        "apply_blocked": 0,
        "failure_stage": Counter(),
        "timing_coverage": 0,
    }
    qroot = round_dir / "qa"
    if not qroot.exists():
        return stats
    for qa_dir in sorted(qroot.iterdir()):
        result = safe_json(qa_dir / "testing_result.json")
        if not result:
            continue
        submission = result.get("submission") or {}
        stage = result.get("failure_stage") or failure_stage(submission)
        stats["total"] += 1
        stats["failure_stage"][stage] += 1
        if stage == "passed":
            stats["passed"] += 1
        else:
            stats["failed"] += 1
        if result.get("issue_ticket_id"):
            stats["issue_tickets"] += 1
        if (qa_dir / "repair_analysis.json").exists():
            stats["repair_suggestions"] += 1
        if (qa_dir / "repair_apply_attempt.json").exists():
            stats["apply_blocked"] += 1
        if (qa_dir / "timing.json").exists():
            stats["timing_coverage"] += 1
    return stats


def record_generator_failure(
    qa_dir: Path,
    run_id: str,
    orig_id: str,
    sample: dict[str, Any],
    dispatch_start: str,
    dispatch_end: str,
    golden_payload: dict[str, Any],
    question_payload: dict[str, Any],
    golden_response: dict[str, Any],
    question_response: dict[str, Any],
    error_text: str,
):
    write_json(
        qa_dir / "qa_dispatch.json",
        {
            "qa_id": run_id,
            "golden_payload": golden_payload,
            "question_payload": question_payload,
            "qa_dispatch_started_at": dispatch_start,
            "qa_dispatch_finished_at": dispatch_end,
            "golden_response": golden_response,
            "question_response": question_response,
            "error_text": error_text,
        },
    )
    write_json(qa_dir / "cgs_request.json", question_payload)
    write_json(qa_dir / "testing_submission.json", {"golden_payload": golden_payload})
    write_json(
        qa_dir / "cgs_result.json",
        {
            "qa_id": run_id,
            "generation_run_id": None,
            "generated_cypher": None,
            "generator_prompt_snapshot": None,
            "generation_status": "generator_request_failed",
            "error_text": error_text,
        },
    )
    testing_result = {
        "qa_id": run_id,
        "submission": {},
        "failure_stage": "generator_request_failed",
        "failure_reason": error_text,
        "issue_ticket_id": None,
    }
    write_json(qa_dir / "testing_result.json", testing_result)
    write_json(qa_dir / "logs.json", grep_logs(run_id))
    timing = {
        "qa_id": run_id,
        "round_id": ROUND_IDS[sample["difficulty"]],
        "timing_status": "partial",
        "qa_agent_started_at": dispatch_start,
        "qa_agent_finished_at": dispatch_end,
        "qa_dispatch_started_at": dispatch_start,
        "qa_dispatch_finished_at": dispatch_end,
        "generator_started_at": dispatch_start,
        "generator_finished_at": dispatch_end,
        "total_elapsed_ms": ms_between(dispatch_start, dispatch_end),
        "qa_agent_elapsed_ms": ms_between(dispatch_start, dispatch_end),
        "cypher_generator_elapsed_ms": ms_between(dispatch_start, dispatch_end),
        "testing_agent_elapsed_ms": None,
        "repair_agent_elapsed_ms": None,
        "generator_elapsed_ms": ms_between(dispatch_start, dispatch_end),
        "tugraph_execution_elapsed_ms": None,
        "semantic_review_elapsed_ms": None,
        "repair_elapsed_ms": None,
        "notes": {"dispatch_mode": "resume_runner_generator_failure"},
    }
    write_json(qa_dir / "timing.json", timing)
    append_index(
        {
            "experiment_id": EXP_ROOT.name,
            "round_id": ROUND_IDS[sample["difficulty"]],
            "qa_id": run_id,
            "original_candidate_qa_id": orig_id,
            "difficulty": sample["difficulty"],
            "query_type": sample["query_type"],
            "structure_family": sample["structure_family"],
            "question": sample["question"],
            "generated_cypher": None,
            "pass_fail": "fail",
            "failure_stage": "generator_request_failed",
            "failure_reason": error_text,
            "issue_ticket_id": None,
            "repair_generated": False,
            "repair_apply_attempted": False,
            "repair_apply_blocked": False,
            "artifact_dir": str(qa_dir),
            "total_elapsed_ms": timing.get("total_elapsed_ms"),
            "qa_agent_elapsed_ms": timing.get("qa_agent_elapsed_ms"),
            "cypher_generator_elapsed_ms": timing.get("cypher_generator_elapsed_ms"),
            "testing_agent_elapsed_ms": None,
            "repair_agent_elapsed_ms": None,
            "tugraph_execution_elapsed_ms": None,
            "semantic_review_elapsed_ms": None,
        }
    )


def run():
    all_samples = [json.loads(line) for line in SAMPLES.open() if line.strip()]
    by_level = defaultdict(list)
    for row in all_samples:
        by_level[row["difficulty"]].append(row)

    all_round_summaries = []
    for level in LEVELS:
        round_id = ROUND_IDS[level]
        round_dir = ROUNDS / round_id
        qa_root = round_dir / "qa"
        qa_root.mkdir(parents=True, exist_ok=True)
        round_health(round_dir)
        round_rows = by_level[level]

        for pos, sample in enumerate(round_rows, start=1):
            orig_id = sample["qa_id"]
            run_id = f"exp_20260428_{level}_{pos:02d}_{orig_id[-6:]}"
            qa_dir = qa_root / run_id
            qa_dir.mkdir(parents=True, exist_ok=True)

            stage = existing_result_stage(qa_dir)
            if stage in TERMINAL_STATES or stage == "generator_request_failed":
                continue

            input_payload = dict(sample)
            input_payload["original_candidate_qa_id"] = orig_id
            input_payload["run_qa_id"] = run_id
            write_json(qa_dir / "input.json", input_payload)

            golden_payload = {
                "id": run_id,
                "cypher": sample["reference_cypher"],
                "answer": sample["reference_answer"],
                "difficulty": sample["difficulty"],
            }
            question_payload = {"id": run_id, "question": sample["question"]}
            dispatch_start = now_iso()
            golden_response = {"status_code": None, "body": None}
            question_response = {"status_code": None, "body": None}
            try:
                g_resp = requests.post(BASES["testing"] + "/api/v1/qa/goldens", json=golden_payload, timeout=30)
                golden_response = {"status_code": g_resp.status_code, "body": g_resp.json() if g_resp.text else None}
                q_resp = requests.post(BASES["cgs"] + "/api/v1/qa/questions", json=question_payload, timeout=180)
                question_response = {"status_code": q_resp.status_code, "body": q_resp.text}
                dispatch_end = now_iso()
            except Exception as exc:
                dispatch_end = now_iso()
                record_generator_failure(
                    qa_dir,
                    run_id,
                    orig_id,
                    sample,
                    dispatch_start,
                    dispatch_end,
                    golden_payload,
                    question_payload,
                    golden_response,
                    question_response,
                    repr(exc),
                )
                rebuild_unique_index()
                continue

            write_json(
                qa_dir / "qa_dispatch.json",
                {
                    "qa_id": run_id,
                    "golden_payload": golden_payload,
                    "question_payload": question_payload,
                    "qa_dispatch_started_at": dispatch_start,
                    "qa_dispatch_finished_at": dispatch_end,
                    "golden_response": golden_response,
                    "question_response": question_response,
                },
            )
            write_json(qa_dir / "cgs_request.json", question_payload)
            write_json(qa_dir / "testing_submission.json", {"golden_payload": golden_payload})

            attempt_path, submission = poll_terminal(run_id)
            if submission is None:
                record_generator_failure(
                    qa_dir,
                    run_id,
                    orig_id,
                    sample,
                    dispatch_start,
                    dispatch_end,
                    golden_payload,
                    question_payload,
                    golden_response,
                    question_response,
                    "no testing submission attempt after cgs dispatch",
                )
                rebuild_unique_index()
                continue

            issue_ticket_path = (
                TESTING_DATA / "issue_tickets" / f"{submission.get('issue_ticket_id')}.json"
                if submission.get("issue_ticket_id")
                else None
            )
            issue_ticket = safe_json(issue_ticket_path) if issue_ticket_path else None
            repair_analysis_path, repair_analysis = find_repair_analysis(submission.get("issue_ticket_id"))
            apply_capture_path, apply_capture = find_apply_capture(run_id)
            logs = grep_logs(run_id)
            timing = build_timing(run_id, round_id, dispatch_start, dispatch_end, submission, issue_ticket_path, repair_analysis_path, apply_capture_path)

            cgs_result = {
                "qa_id": run_id,
                "generation_run_id": submission.get("generation_run_id"),
                "generated_cypher": submission.get("generated_cypher"),
                "generator_prompt_snapshot": submission.get("input_prompt_snapshot"),
                "generation_status": submission.get("state"),
            }
            testing_result = {
                "qa_id": run_id,
                "submission": submission,
                "failure_stage": failure_stage(submission),
                "failure_reason": ((submission.get("evaluation") or {}).get("primary_metrics") or {}).get(
                    "execution_accuracy", {}
                ).get("reason"),
                "issue_ticket_id": submission.get("issue_ticket_id"),
            }
            write_json(qa_dir / "cgs_result.json", cgs_result)
            write_json(qa_dir / "testing_result.json", testing_result)
            if issue_ticket:
                write_json(qa_dir / "issue_ticket.json", issue_ticket)
            if repair_analysis:
                write_json(qa_dir / "repair_analysis.json", repair_analysis)
            if apply_capture:
                ac = dict(apply_capture)
                ac.setdefault("apply_effective", False)
                write_json(qa_dir / "repair_apply_attempt.json", ac)
            write_json(qa_dir / "logs.json", logs)
            write_json(qa_dir / "timing.json", timing)

            append_index(
                {
                    "experiment_id": EXP_ROOT.name,
                    "round_id": round_id,
                    "qa_id": run_id,
                    "original_candidate_qa_id": orig_id,
                    "difficulty": sample["difficulty"],
                    "query_type": sample["query_type"],
                    "structure_family": sample["structure_family"],
                    "question": sample["question"],
                    "generated_cypher": submission.get("generated_cypher"),
                    "pass_fail": "pass" if testing_result["failure_stage"] == "passed" else "fail",
                    "failure_stage": testing_result["failure_stage"],
                    "failure_reason": testing_result["failure_reason"],
                    "issue_ticket_id": submission.get("issue_ticket_id"),
                    "repair_generated": bool(repair_analysis),
                    "repair_apply_attempted": bool(apply_capture),
                    "repair_apply_blocked": bool(apply_capture),
                    "artifact_dir": str(qa_dir),
                    "total_elapsed_ms": timing.get("total_elapsed_ms"),
                    "qa_agent_elapsed_ms": timing.get("qa_agent_elapsed_ms"),
                    "cypher_generator_elapsed_ms": timing.get("cypher_generator_elapsed_ms"),
                    "testing_agent_elapsed_ms": timing.get("testing_agent_elapsed_ms"),
                    "repair_agent_elapsed_ms": timing.get("repair_agent_elapsed_ms"),
                    "tugraph_execution_elapsed_ms": timing.get("tugraph_execution_elapsed_ms"),
                    "semantic_review_elapsed_ms": timing.get("semantic_review_elapsed_ms"),
                }
            )
            rebuild_unique_index()

        round_stats = collect_existing_round_stats(round_dir)
        round_summary = {
            "round_id": round_id,
            "difficulty": level,
            "total": round_stats["total"],
            "passed": round_stats["passed"],
            "failed": round_stats["failed"],
            "pass_rate": round_stats["passed"] / round_stats["total"] if round_stats["total"] else 0,
            "issue_ticket_count": round_stats["issue_tickets"],
            "repair_suggestion_count": round_stats["repair_suggestions"],
            "apply_blocked_count": round_stats["apply_blocked"],
            "failure_stage_distribution": dict(round_stats["failure_stage"]),
            "timing_coverage_rate": round_stats["timing_coverage"] / round_stats["total"] if round_stats["total"] else 0,
        }
        write_json(round_dir / "summary.json", round_summary)
        all_round_summaries.append(round_summary)
        rebuild_unique_index()

    lines = ["# Experiment Summary", "", f"Experiment: {EXP_ROOT.name}", ""]
    for item in all_round_summaries:
        lines.append(
            f"- {item['round_id']}: total={item['total']}, passed={item['passed']}, failed={item['failed']}, pass_rate={item['pass_rate']:.2%}"
        )
    SUMMARY_MD.write_text("\n".join(lines) + "\n")
    print(json.dumps({"status": "completed", "rounds": all_round_summaries}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
