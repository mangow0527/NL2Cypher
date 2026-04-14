from __future__ import annotations

import sys
from pathlib import Path


def _rm(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python tools/reset_workflow.py <qa_id>")
        return 2

    qa_id = sys.argv[1].strip()
    if not qa_id:
        print("qa_id is empty")
        return 2

    ticket_id = f"ticket-{qa_id}"
    analysis_id = f"analysis-{ticket_id}"

    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "data/query_generator_service/questions" / f"{qa_id}.json",
        root / "data/query_generator_service/generation_runs" / f"{qa_id}.json",
        root / "data/testing_service/goldens" / f"{qa_id}.json",
        root / "data/testing_service/submissions" / f"{qa_id}.json",
        root / "data/testing_service/issue_tickets" / f"{ticket_id}.json",
        root / "data/repair_service/analyses" / f"{analysis_id}.json",
        root / "data/repair_service/outbound_apply" / f"{analysis_id}.json",
    ]

    deleted = 0
    for p in paths:
        if p.exists():
            _rm(p)
            deleted += 1

    print(f"deleted={deleted} qa_id={qa_id} ticket_id={ticket_id} analysis_id={analysis_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

