from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.cypher_generator_agent.app.intent_recognition import (
    IntentEmbeddingSample,
    build_text_embedder,
    write_embedding_index,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local JSONL embedding index for intent corpus.")
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("services/cypher_generator_agent/config/intent_embedding_corpus.jsonl"),
        help="Intent embedding corpus JSONL.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("services/cypher_generator_agent/config/intent_embedding_index.jsonl"),
        help="Output JSONL index path.",
    )
    parser.add_argument("--embedder-provider", default="local_hash", help="local_hash or sentence_transformer.")
    parser.add_argument("--embedding-model", help="Model name for provider=sentence_transformer.")
    parser.add_argument("--local-embedding-dimensions", type=int, default=128)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary.")
    args = parser.parse_args()

    samples = _load_samples(args.corpus)
    embedder = build_text_embedder(
        provider=args.embedder_provider,
        model_name=args.embedding_model,
        dimensions=args.local_embedding_dimensions,
    )
    written_count = write_embedding_index(
        samples=samples,
        embedder=embedder,
        output_path=args.output,
        provider=args.embedder_provider,
        model_name=args.embedding_model,
    )
    summary = {
        "corpus": str(args.corpus),
        "output": str(args.output),
        "embedder_provider": args.embedder_provider,
        "embedding_model": args.embedding_model,
        "written_count": written_count,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    print(f"written_count={written_count}")
    print(f"output={args.output}")


def _load_samples(path: Path) -> list[IntentEmbeddingSample]:
    samples: list[IntentEmbeddingSample] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = yaml.safe_load(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number} must contain a JSON object")
        samples.append(IntentEmbeddingSample.from_mapping(payload))
    return samples


if __name__ == "__main__":
    main()
