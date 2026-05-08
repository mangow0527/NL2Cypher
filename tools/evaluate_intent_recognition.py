from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.cypher_generator_agent.app.intent_evaluation import (
    evaluate_intent_recognizer,
    load_intent_eval_items,
    load_intent_pressure_items,
    summarize_intent_pressure,
)
from services.cypher_generator_agent.app.intent_recognition import (
    EmbeddingIntentRecognizer,
    HybridIntentRecognizer,
    RuleBasedIntentRecognizer,
    build_text_embedder,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate NL2Cypher intent recognition assets.")
    parser.add_argument("--dataset", type=Path, help="JSONL with text/question and expected intents.")
    parser.add_argument(
        "--dataset-preset",
        choices=("eval", "corpus", "none"),
        default="eval",
        help="Use the independent eval set, corpus self-test, or no labeled dataset when --dataset is omitted.",
    )
    parser.add_argument("--pressure-dataset", type=Path, help="Unlabeled qa-agent JSONL for decision/source pressure test.")
    parser.add_argument("--mode", choices=("rule", "embedding", "hybrid"), default="hybrid")
    parser.add_argument("--embedder-provider", default="local_hash", help="local_hash or sentence_transformer.")
    parser.add_argument("--embedding-model", help="Model name for provider=sentence_transformer.")
    parser.add_argument("--embedding-index", type=Path, help="Prebuilt local JSONL embedding index.")
    parser.add_argument("--local-embedding-dimensions", type=int, default=128)
    parser.add_argument("--accept-threshold", type=float, default=0.35)
    parser.add_argument("--margin-threshold", type=float, default=0.02)
    parser.add_argument("--consensus-top-k", type=int, default=3)
    parser.add_argument("--consensus-min-count", type=int, default=2)
    parser.add_argument("--include-diagnostics", action="store_true", help="Include embedding top-k diagnostics.")
    parser.add_argument("--diagnostic-top-k", type=int, default=5)
    parser.add_argument("--sweep", action="store_true", help="Run threshold/margin sweep instead of one evaluation.")
    parser.add_argument("--accept-thresholds", default="0.35,0.45,0.55,0.65")
    parser.add_argument("--margin-thresholds", default="0.02,0.05,0.08,0.10")
    parser.add_argument("--consensus-top-k-values", default="3")
    parser.add_argument("--consensus-min-count-values", default="2")
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path("services/cypher_generator_agent/config"),
        help="Directory containing intent taxonomy, rules, and embedding corpus.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary.")
    args = parser.parse_args()

    labeled_dataset = _resolve_labeled_dataset(args.dataset, args.dataset_preset, args.config_dir)
    if labeled_dataset is None and args.pressure_dataset is None:
        raise SystemExit("provide --dataset, use --dataset-preset eval/corpus, or provide --pressure-dataset")

    labeled_items = load_intent_eval_items(labeled_dataset) if labeled_dataset is not None else None
    pressure_items = load_intent_pressure_items(args.pressure_dataset) if args.pressure_dataset is not None else None
    if args.sweep:
        sweep_rows = _run_threshold_sweep(args, labeled_items, pressure_items)
        if args.json:
            print(json.dumps({"threshold_sweep": sweep_rows}, ensure_ascii=False, indent=2))
            return
        _print_threshold_sweep(sweep_rows)
        return

    recognizer = _build_recognizer(
        args.mode,
        args.config_dir,
        embedder_provider=args.embedder_provider,
        embedding_model=args.embedding_model,
        embedding_index=args.embedding_index,
        local_embedding_dimensions=args.local_embedding_dimensions,
        accept_threshold=args.accept_threshold,
        margin_threshold=args.margin_threshold,
        consensus_top_k=args.consensus_top_k,
        consensus_min_count=args.consensus_min_count,
    )
    labeled_summary = (
        evaluate_intent_recognizer(labeled_items, recognizer)
        if labeled_items is not None
        else None
    )
    pressure_summary = (
        summarize_intent_pressure(pressure_items, recognizer)
        if pressure_items is not None
        else None
    )
    diagnostics = _embedding_diagnostics_for_items(labeled_items, recognizer, args.diagnostic_top_k) if (
        args.include_diagnostics and labeled_items is not None
    ) else []
    pressure_diagnostics = _embedding_diagnostics_for_items(pressure_items, recognizer, args.diagnostic_top_k) if (
        args.include_diagnostics and pressure_items is not None
    ) else []

    if args.json:
        payload = {}
        if labeled_summary is not None:
            payload["labeled_eval"] = _labeled_summary_to_dict(labeled_summary)
        if pressure_summary is not None:
            payload["pressure_test"] = _pressure_summary_to_dict(pressure_summary)
        if diagnostics:
            payload["embedding_diagnostics"] = diagnostics
        if pressure_diagnostics:
            payload["pressure_embedding_diagnostics"] = pressure_diagnostics
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if labeled_summary is not None:
        _print_labeled_summary(labeled_summary)
    if pressure_summary is not None:
        if labeled_summary is not None:
            print()
        _print_pressure_summary(pressure_summary)
    if diagnostics:
        print()
        _print_embedding_diagnostics(diagnostics)
    if pressure_diagnostics:
        print()
        _print_embedding_diagnostics(pressure_diagnostics, title="pressure_embedding_diagnostics")


def _build_recognizer(
    mode: str,
    config_dir: Path,
    *,
    embedder_provider: str = "local_hash",
    embedding_model: str | None = None,
    embedding_index: Path | None = None,
    local_embedding_dimensions: int = 128,
    accept_threshold: float = 0.35,
    margin_threshold: float = 0.02,
    consensus_top_k: int = 3,
    consensus_min_count: int = 2,
):
    taxonomy_path = config_dir / "intent_taxonomy.yaml"
    rule_recognizer = RuleBasedIntentRecognizer.from_files(
        taxonomy_path=taxonomy_path,
        rules_path=config_dir / "intent_rules.yaml",
    )
    if mode == "rule":
        return rule_recognizer

    embedder = build_text_embedder(
        provider=embedder_provider,
        model_name=embedding_model,
        dimensions=local_embedding_dimensions,
    )
    if embedding_index is not None:
        embedding_recognizer = EmbeddingIntentRecognizer.from_index_file(
            taxonomy_path=taxonomy_path,
            index_path=embedding_index,
            embedder=embedder,
            accept_threshold=accept_threshold,
            margin_threshold=margin_threshold,
            consensus_top_k=consensus_top_k,
            consensus_min_count=consensus_min_count,
        )
    else:
        embedding_recognizer = EmbeddingIntentRecognizer.from_files(
            taxonomy_path=taxonomy_path,
            corpus_path=config_dir / "intent_embedding_corpus.jsonl",
            embedder=embedder,
            accept_threshold=accept_threshold,
            margin_threshold=margin_threshold,
            consensus_top_k=consensus_top_k,
            consensus_min_count=consensus_min_count,
        )
    if mode == "embedding":
        return embedding_recognizer
    return HybridIntentRecognizer(
        rule_recognizer=rule_recognizer,
        embedding_recognizer=embedding_recognizer,
    )


def _resolve_labeled_dataset(dataset: Path | None, dataset_preset: str, config_dir: Path) -> Path | None:
    if dataset is not None:
        return dataset
    if dataset_preset == "eval":
        return config_dir / "intent_eval_set.jsonl"
    if dataset_preset == "corpus":
        return config_dir / "intent_embedding_corpus.jsonl"
    return None


def _run_threshold_sweep(args, labeled_items, pressure_items) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for accept_threshold in _parse_float_values(args.accept_thresholds):
        for margin_threshold in _parse_float_values(args.margin_thresholds):
            for consensus_top_k in _parse_int_values(args.consensus_top_k_values):
                for consensus_min_count in _parse_int_values(args.consensus_min_count_values):
                    recognizer = _build_recognizer(
                        args.mode,
                        args.config_dir,
                        embedder_provider=args.embedder_provider,
                        embedding_model=args.embedding_model,
                        embedding_index=args.embedding_index,
                        local_embedding_dimensions=args.local_embedding_dimensions,
                        accept_threshold=accept_threshold,
                        margin_threshold=margin_threshold,
                        consensus_top_k=consensus_top_k,
                        consensus_min_count=consensus_min_count,
                    )
                    row: dict[str, object] = {
                        "accept_threshold": accept_threshold,
                        "margin_threshold": margin_threshold,
                        "consensus_top_k": consensus_top_k,
                        "consensus_min_count": consensus_min_count,
                    }
                    if labeled_items is not None:
                        labeled_summary = evaluate_intent_recognizer(labeled_items, recognizer)
                        row.update(
                            {
                                "labeled_total": labeled_summary.total,
                                "labeled_correct": labeled_summary.correct,
                                "labeled_accuracy": labeled_summary.accuracy,
                                "labeled_decision_counts": labeled_summary.decision_counts,
                            }
                        )
                    if pressure_items is not None:
                        pressure_summary = summarize_intent_pressure(pressure_items, recognizer)
                        row.update(
                            {
                                "pressure_total": pressure_summary.total,
                                "pressure_decision_counts": pressure_summary.decision_counts,
                            }
                        )
                    rows.append(row)
    return rows


def _embedding_diagnostics_for_items(items, recognizer, top_k: int) -> list[dict[str, object]]:
    embedding_recognizer = _extract_embedding_recognizer(recognizer)
    if embedding_recognizer is None:
        return []
    diagnostics: list[dict[str, object]] = []
    for item in items:
        diagnostic = embedding_recognizer.diagnose(item.text, top_k=top_k).to_dict()
        diagnostic["id"] = item.id
        diagnostics.append(diagnostic)
    return diagnostics


def _extract_embedding_recognizer(recognizer) -> EmbeddingIntentRecognizer | None:
    if isinstance(recognizer, EmbeddingIntentRecognizer):
        return recognizer
    if isinstance(recognizer, HybridIntentRecognizer):
        return recognizer.embedding_recognizer
    return None


def _parse_float_values(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def _parse_int_values(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _labeled_summary_to_dict(summary) -> dict[str, object]:
    return {
        "total": summary.total,
        "correct": summary.correct,
        "accuracy": summary.accuracy,
        "source_counts": summary.source_counts,
        "decision_counts": summary.decision_counts,
        "confusion_pairs": summary.confusion_pairs,
        "failures": [failure.to_dict() for failure in summary.failures],
    }


def _pressure_summary_to_dict(summary) -> dict[str, object]:
    return {
        "total": summary.total,
        "source_counts": summary.source_counts,
        "decision_counts": summary.decision_counts,
        "accepted_intent_counts": summary.accepted_intent_counts,
        "results": [result.to_dict() for result in summary.results],
    }


def _print_labeled_summary(summary) -> None:
    print("labeled_eval=")
    print(f"  total={summary.total}")
    print(f"  correct={summary.correct}")
    print(f"  accuracy={summary.accuracy:.4f}")
    print(f"  source_counts={summary.source_counts}")
    print(f"  decision_counts={summary.decision_counts}")
    if summary.confusion_pairs:
        print("  confusion_pairs=")
        for pair in summary.confusion_pairs:
            print(f"    {pair['expected']} -> {pair['predicted']}: {pair['count']}")
    if summary.failures:
        print("  failures=")
        for failure in summary.failures:
            print(
                "    "
                f"{failure.id} expected={failure.expected_primary_intent}.{failure.expected_secondary_intent} "
                f"predicted={failure.predicted_primary_intent}.{failure.predicted_secondary_intent} "
                f"source={failure.source} decision={failure.decision} "
                f"confidence={failure.confidence} text={failure.text}"
            )


def _print_pressure_summary(summary) -> None:
    print("pressure_test=")
    print(f"  total={summary.total}")
    print(f"  source_counts={summary.source_counts}")
    print(f"  decision_counts={summary.decision_counts}")
    print(f"  accepted_intent_counts={summary.accepted_intent_counts}")


def _print_embedding_diagnostics(diagnostics: list[dict[str, object]], *, title: str = "embedding_diagnostics") -> None:
    print(f"{title}=")
    for diagnostic in diagnostics:
        candidates = diagnostic["candidates"]
        top_candidate = candidates[0] if isinstance(candidates, list) and candidates else {}
        print(
            "  "
            f"{diagnostic['id']} reason={diagnostic['reason']} decision={diagnostic['decision']} "
            f"top_score={diagnostic['top_score']} margin={diagnostic['margin']} "
            f"top_sample={top_candidate.get('sample_id') if isinstance(top_candidate, dict) else None}"
        )


def _print_threshold_sweep(rows: list[dict[str, object]]) -> None:
    print("threshold_sweep=")
    for row in rows:
        print(
            "  "
            f"accept={row['accept_threshold']} margin={row['margin_threshold']} "
            f"consensus={row['consensus_min_count']}/{row['consensus_top_k']} "
            f"accuracy={row.get('labeled_accuracy')} "
            f"decisions={row.get('labeled_decision_counts') or row.get('pressure_decision_counts')}"
        )


if __name__ == "__main__":
    main()
