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
    ROOT / "console" / "runtime_console" / "docs" / "System_Runtime_Architecture.md",
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


def test_active_repair_agent_paths_do_not_reference_legacy_name() -> None:
    offenders: list[str] = []
    for path in _iter_text_files():
        text = path.read_text(encoding="utf-8")
        if LEGACY_UPPER in text or LEGACY_LOWER in text:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_runtime_console_docs_match_current_runtime_topology() -> None:
    system_arch = (ROOT / "console" / "runtime_console" / "docs" / "System_Runtime_Architecture.md").read_text(
        encoding="utf-8"
    )
    workflow = (ROOT / "console" / "runtime_console" / "docs" / "reference" / "workflow.md").read_text(
        encoding="utf-8"
    )

    assert "- `testing-agent` `8003`" in system_arch
    assert "- 挂载位置：`runtime-results-service`" in system_arch
    assert "`GET /api/v1/questions/{id}/prompt`" not in system_arch
    assert "接收问题并落盘" not in workflow


def test_obsolete_runtime_console_planning_docs_are_removed() -> None:
    obsolete_paths = [
        ROOT / "services" / "cypher_generator_agent" / "docs" / "reference" / "PLAN.md",
        ROOT / "console" / "runtime_console" / "docs" / "superpowers" / "plans" / "2026-04-13-repair-agent-analysis-v2.md",
        ROOT / "console" / "runtime_console" / "docs" / "superpowers" / "plans" / "2026-04-13-system-integration-console-implementation.md",
        ROOT / "console" / "runtime_console" / "docs" / "superpowers" / "plans" / "2026-04-14-llm-retries-and-repair-agent-cleanup.md",
        ROOT / "console" / "runtime_console" / "docs" / "superpowers" / "specs" / "2026-04-13-system-integration-console-design.md",
    ]

    assert [str(path.relative_to(ROOT)) for path in obsolete_paths if path.exists()] == []
