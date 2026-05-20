from __future__ import annotations

import json
import subprocess
import sys

import httpx

from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.lexical_layer.lexer import OntologyLexer
from services.cypher_generator_agent.app.lexical_layer.lexer import _RawMatch
from services.cypher_generator_agent.app.lexical_layer.mention_vector_recall import (
    MentionVectorCandidate,
    RagMentionVectorRetriever,
    build_mention_vector_documents,
)


class FakeMentionVectorRetriever:
    provider = "fake_mention_vector"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def search(
        self,
        fragment: str,
        *,
        expected_mention_type: str | None,
        top_k: int,
    ) -> list[MentionVectorCandidate]:
        self.calls.append(
            {
                "fragment": fragment,
                "expected_mention_type": expected_mention_type,
                "top_k": top_k,
            }
        )
        if fragment != "穿越":
            return []
        return [
            MentionVectorCandidate(
                id="mention.REL_PATH_THROUGH.穿过",
                text="经过 途经 穿过 path through",
                canonical_id="REL_PATH_THROUGH",
                mention_type="relation_predicate",
                surface="穿过",
                score=0.91,
                metadata={"dictionary": "synonyms", "via_synonym_group": "SYN_PathThrough"},
            )
        ]


def test_lexer_uses_mention_vector_retriever_for_unmatched_fragments() -> None:
    assets = OntologyAssets.from_default_resources()
    retriever = FakeMentionVectorRetriever()
    lexer = OntologyLexer(assets, vector_retriever=retriever)

    trace = lexer.run("查询金牌服务穿越的隧道名称").to_dict()

    assert retriever.calls == [
        {"fragment": "穿越", "expected_mention_type": "relation_predicate", "top_k": 5}
    ]
    assert trace["unmatched_fragments"] == [
        {"surface": "穿越", "span": [6, 8], "expected_mention_type": "relation_predicate"}
    ]
    assert trace["vector_recalls"][0]["provider"] == "fake_mention_vector"
    assert trace["vector_recalls"][0]["candidates"][0]["canonical_id"] == "REL_PATH_THROUGH"
    assert (
        "REL_PATH_THROUGH",
        "穿越",
        "RELATION",
    ) in [
        (mention["canonical_id"], mention["surface"], mention["mention_type"])
        for mention in trace["mentions"]
    ]


def test_vector_recall_skips_runtime_literal_fragments() -> None:
    assets = OntologyAssets.from_default_resources()
    retriever = FakeMentionVectorRetriever()
    lexer = OntologyLexer(assets, vector_retriever=retriever)

    for question in (
        "查询源网元为NetworkElement_003的隧道",
        "查询IP为10.1.1.1的网元",
        "查询带宽大于100的服务",
        "查询2026-05-19的服务",
        "查询名称为\"VIP专线A\"的服务",
    ):
        lexer.run(question)

    assert retriever.calls == []


def test_vector_recall_uses_raw_ac_coverage_not_preselected_hits(monkeypatch) -> None:
    assets = OntologyAssets.from_default_resources()
    retriever = FakeMentionVectorRetriever()
    lexer = OntologyLexer(assets, vector_retriever=retriever)
    raw_matches = (
        _RawMatch(
            hit_id="ac-1",
            canonical_id="Service",
            mention_type="business_object",
            surface="服务AB",
            span_start=0,
            span_end=4,
            match_source="ac_exact",
            metadata={},
            score=1.0,
        ),
        _RawMatch(
            hit_id="ac-2",
            canonical_id="REL_PATH_THROUGH",
            mention_type="relation_predicate",
            surface="服务",
            span_start=0,
            span_end=2,
            match_source="ac_exact",
            metadata={},
            score=1.0,
        ),
    )
    monkeypatch.setattr(lexer, "_scan", lambda question: raw_matches)

    lexer.run("服务AB")

    assert retriever.calls == []


def test_lexer_without_vector_retriever_does_not_run_local_ngram_recall() -> None:
    assets = OntologyAssets.from_default_resources()
    lexer = OntologyLexer(assets, vector_retriever=None)

    trace = lexer.run("查询金牌服务穿越的隧道名称").to_dict()

    assert trace["vector_recalls"] == []
    assert not any(
        mention["canonical_id"] == "REL_PATH_THROUGH" and mention["surface"] == "穿越"
        for mention in trace["mentions"]
    )


def test_mention_vector_documents_are_generated_from_lexer_dictionaries() -> None:
    assets = OntologyAssets.from_default_resources()

    documents = build_mention_vector_documents(assets)

    service_doc = next(item for item in documents if item.id == "mention.Service.业务")
    source_role_doc = next(item for item in documents if item.id == "mention.REL_TUNNEL_SRC.入口")
    assert service_doc.canonical_id == "Service"
    assert service_doc.mention_type == "business_object"
    assert service_doc.surface == "业务"
    assert source_role_doc.metadata["via_synonym_group"] == "SYN_SourceRole"
    assert service_doc.to_rag_fragment()["type"] == "mention_candidate"
    assert service_doc.to_rag_fragment()["metadata"]["canonical_id"] == "Service"
    assert not any(item.canonical_id.startswith("SYN_") for item in documents)


def test_rag_mention_vector_retriever_uses_mention_search_contract() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "collection": "nl2cypher_mention_candidates_v1",
                "hits": [
                    {
                        "id": "mention.REL_PATH_THROUGH.穿过",
                        "text": "经过 途经 穿过 path through",
                        "canonical_id": "REL_PATH_THROUGH",
                        "mention_type": "relation_predicate",
                        "surface": "穿过",
                        "score": 0.89,
                        "metadata": {"dictionary": "synonyms"},
                    }
                ],
            },
        )

    retriever = RagMentionVectorRetriever(
        base_url="http://rag-service",
        collection="nl2cypher_mention_candidates_v1",
        transport=httpx.MockTransport(handler),
    )

    candidates = retriever.search("穿越", expected_mention_type="relation_predicate", top_k=5)

    assert seen_payloads == [
        {
            "query": "穿越",
            "top_k": 5,
            "collection": "nl2cypher_mention_candidates_v1",
            "filters": {"enabled": True, "mention_type": "relation_predicate"},
        }
    ]
    assert candidates == [
        MentionVectorCandidate(
            id="mention.REL_PATH_THROUGH.穿过",
            text="经过 途经 穿过 path through",
            canonical_id="REL_PATH_THROUGH",
            mention_type="relation_predicate",
            surface="穿过",
            score=0.89,
            metadata={"dictionary": "synonyms"},
        )
    ]


def test_rag_mention_vector_retriever_reads_dedicated_environment(monkeypatch) -> None:
    monkeypatch.setenv("NL2CYPHER_MENTION_EMBEDDING_STORE", "rag_vector")
    monkeypatch.setenv("NL2CYPHER_MENTION_RAG_SERVICE_URL", "http://rag-service")
    monkeypatch.setenv("NL2CYPHER_MENTION_RAG_COLLECTION", "mention_collection")
    monkeypatch.setenv("NL2CYPHER_MENTION_RAG_ENDPOINT", "/api/v1/mention/search")
    monkeypatch.setenv("NL2CYPHER_MENTION_RAG_TIMEOUT_SECONDS", "3")

    retriever = RagMentionVectorRetriever.from_environment()

    assert retriever is not None
    assert retriever.base_url == "http://rag-service"
    assert retriever.collection == "mention_collection"
    assert retriever.endpoint_path == "/api/v1/mention/search"
    assert retriever.timeout_seconds == 3.0


def test_rag_mention_vector_retriever_reads_dotenv_when_process_env_missing(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("NL2CYPHER_MENTION_EMBEDDING_STORE", raising=False)
    monkeypatch.delenv("NL2CYPHER_MENTION_RAG_SERVICE_URL", raising=False)
    monkeypatch.delenv("NL2CYPHER_MENTION_RAG_COLLECTION", raising=False)
    monkeypatch.delenv("NL2CYPHER_MENTION_RAG_ENDPOINT", raising=False)
    monkeypatch.delenv("NL2CYPHER_MENTION_RAG_TIMEOUT_SECONDS", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "NL2CYPHER_MENTION_EMBEDDING_STORE=rag_vector",
                "NL2CYPHER_MENTION_RAG_SERVICE_URL=http://rag-service",
                "NL2CYPHER_MENTION_RAG_COLLECTION=mention_collection",
                "NL2CYPHER_MENTION_RAG_ENDPOINT=/api/v1/mention/search",
                "NL2CYPHER_MENTION_RAG_TIMEOUT_SECONDS=3",
            ]
        ),
        encoding="utf-8",
    )

    retriever = RagMentionVectorRetriever.from_environment()

    assert retriever is not None
    assert retriever.base_url == "http://rag-service"
    assert retriever.collection == "mention_collection"
    assert retriever.endpoint_path == "/api/v1/mention/search"
    assert retriever.timeout_seconds == 3.0


def test_build_mention_vector_corpus_script_writes_rag_fragments(tmp_path) -> None:
    output_path = tmp_path / "mention_candidates.jsonl"

    subprocess.run(
        [
            sys.executable,
            "tools/build_mention_vector_corpus.py",
            "--output",
            str(output_path),
        ],
        check=True,
    )

    records = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert records
    service = next(item for item in records if item["metadata"]["canonical_id"] == "Service")
    assert service["type"] == "mention_candidate"
    assert service["metadata"]["mention_type"] == "business_object"
