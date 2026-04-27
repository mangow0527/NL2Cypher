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

    root = Path(__file__).resolve().parents[1]
    deleted = 0
    paths = [
        root / "data/testing_service/goldens" / f"{qa_id}.json",
        root / "data/testing_service/submissions" / f"{qa_id}.json",
    ]
    paths.extend(root.glob(f"data/testing_service/submission_attempts/{qa_id}__attempt_*.json"))
    paths.extend(root.glob(f"data/testing_service/issue_tickets/ticket-{qa_id}-attempt-*.json"))
    paths.extend(root.glob(f"data/repair_service/analyses/analysis-ticket-{qa_id}-attempt-*.json"))
    paths.extend(root.glob(f"data/repair_service/analyses/analysis-ticket-{qa_id}.json"))
    paths.extend(root.glob(f"data/repair_service/outbound_apply/analysis-ticket-{qa_id}-attempt-*.json"))
    paths.extend(root.glob(f"data/repair_service/outbound_apply/analysis-ticket-{qa_id}.json"))

    for p in paths:
        if p.exists():
            _rm(p)
            deleted += 1

    print(f"deleted={deleted} qa_id={qa_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
