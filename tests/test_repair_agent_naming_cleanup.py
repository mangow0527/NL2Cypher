from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


ACTIVE_PATHS = [
    ROOT / "services" / "repair_agent" / "app",
    ROOT / "services" / "repair_agent" / "docs",
    ROOT / "contracts" / "models.py",
    ROOT / "console" / "runtime_console" / "app",
    ROOT / "console" / "runtime_console" / "ui",
    ROOT / "console" / "runtime_console" / "docs" / "reference",
]
TEXT_SUFFIXES = {".py", ".md", ".html", ".js", ".css", ".json", ".svg", ".txt"}


def _iter_text_files() -> list[Path]:
    files: list[Path] = []
    for path in ACTIVE_PATHS:
        if path.is_file():
            if path.suffix in TEXT_SUFFIXES:
                files.append(path)
            continue
        files.extend(file for file in path.rglob("*") if file.is_file() and file.suffix in TEXT_SUFFIXES)
    return files


LEGACY_UPPER = "K" + "RSS"
LEGACY_LOWER = "k" + "rss"


def test_active_repair_agent_paths_do_not_reference_obsolete_service_name() -> None:
    offenders: list[str] = []
    for path in _iter_text_files():
        text = path.read_text(encoding="utf-8")
        if LEGACY_UPPER in text or LEGACY_LOWER in text:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_obsolete_runtime_console_planning_docs_are_removed() -> None:
    obsolete_paths = [
        ROOT / "console" / "runtime_console" / "docs" / "System_Runtime_Architecture.md",
        ROOT / "console" / "runtime_console" / "docs" / "reference" / "workflow.md",
        ROOT / "console" / "runtime_console" / "docs" / "superpowers" / "plans" / "2026-04-13-repair-agent-analysis-v2.md",
        ROOT / "console" / "runtime_console" / "docs" / "superpowers" / "plans" / "2026-04-13-system-integration-console-implementation.md",
        ROOT / "console" / "runtime_console" / "docs" / "superpowers" / "plans" / "2026-04-14-llm-retries-and-repair-agent-cleanup.md",
        ROOT / "console" / "runtime_console" / "docs" / "superpowers" / "specs" / "2026-04-13-system-integration-console-design.md",
    ]

    assert [str(path.relative_to(ROOT)) for path in obsolete_paths if path.exists()] == []
