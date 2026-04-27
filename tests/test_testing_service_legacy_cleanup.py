from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_testing_agent_evaluation_modules_are_removed() -> None:
    assert not (ROOT / "services" / "testing_agent" / "app" / "evaluation.py").exists()
    assert not (ROOT / "contracts" / "evaluation.py").exists()
