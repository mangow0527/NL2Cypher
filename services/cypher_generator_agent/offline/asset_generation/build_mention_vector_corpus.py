from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.lexical_layer.mention_vector_recall import (
    build_mention_vector_documents,
)
from services.cypher_generator_agent.app.infrastructure.resource_paths import lexer_mention_vector_corpus_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build mention candidate RAG fragments from lexer dictionaries.")
    parser.add_argument(
        "--output",
        type=Path,
        default=lexer_mention_vector_corpus_path(),
        help="Output JSONL path containing RAG fragment payloads.",
    )
    args = parser.parse_args()

    assets = OntologyAssets.from_default_resources()
    documents = build_mention_vector_documents(assets)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(document.to_rag_fragment(), ensure_ascii=False, separators=(",", ":"))
        for document in documents
    ]
    args.output.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "count": len(lines)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
