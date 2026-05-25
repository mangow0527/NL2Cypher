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
from services.cypher_generator_agent.app.question_framing_layer.models import (
    QuestionAtom,
    QuestionFramingRole,
    QuestionFramingTrace,
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
                mention_type="RELATION",
                surface="穿过",
                score=0.91,
                metadata={"dictionary": "synonyms", "via_synonym_group": "SYN_PathThrough"},
            )
        ]


class FakeGenericInfoVectorRetriever:
    provider = "fake_generic_info_vector"

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
        if fragment != "信息":
            return []
        return [
            MentionVectorCandidate(
                id="mention.Link.status.信息",
                text="信息 status generic info",
                canonical_id="Link.status",
                mention_type="ATTRIBUTE",
                surface="状态",
                score=0.93,
                metadata={"dictionary": "attributes"},
            )
        ]


class FakeConnectorVectorRetriever:
    provider = "fake_connector_vector"

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
        if fragment != "对应":
            return []
        return [
            MentionVectorCandidate(
                id="mention.Link.status.状态",
                text="状态 Link.status",
                canonical_id="Link.status",
                mention_type="ATTRIBUTE",
                surface="状态",
                score=0.93,
                metadata={"dictionary": "attributes"},
            )
        ]


class FakeExactValueVectorRetriever:
    provider = "fake_exact_value_vector"

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
        if fragment != "Service_002":
            return []
        return [
            MentionVectorCandidate(
                id="mention.ServiceType.QoS.服务质量业务",
                text="服务质量业务 ServiceType.QoS Service elem_type value QoS.",
                canonical_id="ServiceType.QoS",
                mention_type="VALUE",
                surface="服务质量业务",
                score=0.91,
                metadata={
                    "dictionary": "attribute_values",
                    "constrains_field": "Service.elem_type",
                    "raw_value": "QoS",
                },
            )
        ]


class FakeRelationPathStructuralVectorRetriever:
    provider = "fake_relation_path_structural_vector"

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
        if fragment == "之间":
            return [
                MentionVectorCandidate(
                    id="mention.Fiber.location.之间",
                    text="之间 location Fiber.location",
                    canonical_id="Fiber.location",
                    mention_type="ATTRIBUTE",
                    surface="位置",
                    score=0.92,
                    metadata={"dictionary": "attributes"},
                )
            ]
        if fragment == "双方的元素":
            return [
                MentionVectorCandidate(
                    id="mention.NetworkElement.software_version.双方的元素",
                    text="双方的元素 software version",
                    canonical_id="NetworkElement.software_version",
                    mention_type="ATTRIBUTE",
                    surface="软件版本",
                    score=0.93,
                    metadata={"dictionary": "attributes"},
                )
            ]
        return []


def test_lexer_uses_mention_vector_retriever_for_unmatched_fragments() -> None:
    assets = OntologyAssets.from_default_resources()
    retriever = FakeMentionVectorRetriever()
    lexer = OntologyLexer(assets, vector_retriever=retriever)

    trace = lexer.run("查询金牌服务穿越的隧道名称").to_dict()

    assert retriever.calls == [
        {"fragment": "穿越", "expected_mention_type": "RELATION", "top_k": 5}
    ]
    assert trace["unmatched_fragments"] == [
        {"surface": "穿越", "span": [6, 8], "expected_mention_type": "RELATION"}
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


def test_generic_return_content_atom_blocks_info_attribute_vector_recall() -> None:
    assets = OntologyAssets.from_default_resources()
    retriever = FakeGenericInfoVectorRetriever()
    lexer = OntologyLexer(assets, vector_retriever=retriever)
    question = "查询所有的服务信息。"
    framing = QuestionFramingTrace(
        question=question,
        raw_response="fixture",
        atoms=(
            QuestionAtom(
                atom_id="QA1",
                text="所有的服务信息",
                roles=(QuestionFramingRole.FIND_OBJECT, QuestionFramingRole.RETURN_CONTENT),
                span_start=2,
                span_end=9,
            ),
        ),
    )

    trace = lexer.run(question, question_framing=framing).to_dict()

    assert not any(call["fragment"] == "信息" for call in retriever.calls)
    assert not any(mention["canonical_id"] == "Link.status" for mention in trace["mentions"])
    assert not any(signal["text"] == "信息" for signal in trace["shape_signals"])


def test_return_content_filler_between_attributes_blocks_vector_recall() -> None:
    assets = OntologyAssets.from_default_resources()
    retriever = FakeConnectorVectorRetriever()
    lexer = OntologyLexer(assets, vector_retriever=retriever)
    question = "查询所有服务的名称及其对应的服务质量等级。"
    framing = QuestionFramingTrace(
        question=question,
        raw_response="fixture",
        atoms=(
            QuestionAtom(
                atom_id="QA1",
                text="所有服务",
                roles=(QuestionFramingRole.FIND_OBJECT,),
                span_start=2,
                span_end=6,
            ),
            QuestionAtom(
                atom_id="QA2",
                text="名称及其对应的服务质量等级",
                roles=(QuestionFramingRole.RETURN_CONTENT,),
                span_start=7,
                span_end=20,
            ),
        ),
    )

    trace = lexer.run(question, question_framing=framing).to_dict()

    assert not any(call["fragment"] == "对应" for call in retriever.calls)
    assert not any(mention["canonical_id"] == "Link.status" for mention in trace["mentions"])
    assert [mention["canonical_id"] for mention in trace["mentions"] if mention["mention_type"] == "ATTRIBUTE"] == [
        "Service.name",
        "Service.quality_of_service",
    ]
    assert "对应" in [item["surface"] for item in trace["unmatched_fragments"]]


def test_relation_path_atoms_block_structural_object_and_attribute_vector_noise() -> None:
    assets = OntologyAssets.from_default_resources()
    retriever = FakeRelationPathStructuralVectorRetriever()
    lexer = OntologyLexer(assets, vector_retriever=retriever)
    question = "查询所有服务与隧道之间的连接关系，并返回双方的元素类型。"
    framing = QuestionFramingTrace(
        question=question,
        raw_response="fixture",
        atoms=(
            QuestionAtom(
                atom_id="QA1",
                text="所有服务与隧道之间的连接关系",
                roles=(QuestionFramingRole.FIND_OBJECT, QuestionFramingRole.RELATION_PATH),
                span_start=2,
                span_end=16,
            ),
            QuestionAtom(
                atom_id="QA2",
                text="双方的元素类型",
                roles=(QuestionFramingRole.RETURN_CONTENT,),
                span_start=20,
                span_end=27,
            ),
        ),
    )

    trace = lexer.run(question, question_framing=framing).to_dict()

    called_fragments = [call["fragment"] for call in retriever.calls]
    assert "之间" not in called_fragments
    assert "双方的元素" not in called_fragments
    assert not any(mention["canonical_id"] == "Link" for mention in trace["mentions"])
    assert not any(mention["canonical_id"] == "Fiber.location" for mention in trace["mentions"])
    assert not any(mention["canonical_id"] == "NetworkElement.software_version" for mention in trace["mentions"])
    assert any(
        mention["canonical_id"] == "Service" and mention["mention_type"] == "OBJECT"
        for mention in trace["mentions"]
    )
    assert any(
        mention["canonical_id"] == "Tunnel" and mention["mention_type"] == "OBJECT"
        for mention in trace["mentions"]
    )


def test_runtime_identifier_literals_are_not_sent_to_vector_recall() -> None:
    assets = OntologyAssets.from_default_resources()
    retriever = FakeExactValueVectorRetriever()
    lexer = OntologyLexer(assets, vector_retriever=retriever)

    trace = lexer.run("查询名称为 Service_002 的服务").to_dict()

    assert not any(call["fragment"] == "Service_002" for call in retriever.calls)
    assert not any(mention["canonical_id"] == "ServiceType.QoS" for mention in trace["mentions"])
    assert any(
        mention["surface"] == "Service_002"
        and mention["canonical_id"] == "LITERAL_IDENTIFIER"
        and mention["mention_type"] == "LITERAL_VALUE"
        for mention in trace["mentions"]
    )


def test_literal_fallback_runs_after_vector_recall_for_unmatched_runtime_values() -> None:
    assets = OntologyAssets.from_default_resources()
    retriever = FakeMentionVectorRetriever()
    lexer = OntologyLexer(assets, vector_retriever=retriever)

    trace = lexer.run("查询源网元为NetworkElement_003的隧道").to_dict()

    assert not any(call["fragment"] == "NetworkElement_003" for call in retriever.calls)
    assert any(
        hit["surface"] == "NetworkElement_003"
        and hit["canonical_id"] == "LITERAL_IDENTIFIER"
        and hit["match_source"] == "literal_extract"
        for hit in trace["structured_matches"]
    )
    assert any(
        mention["surface"] == "NetworkElement_003"
        and mention["canonical_id"] == "LITERAL_IDENTIFIER"
        and mention["mention_type"] == "LITERAL_VALUE"
        for mention in trace["mentions"]
    )


def test_runtime_literal_fragments_are_extracted_before_vector_recall() -> None:
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

    called_fragments = [call["fragment"] for call in retriever.calls]
    assert "NetworkElement_003" not in called_fragments
    assert "10.1.1.1" not in called_fragments
    assert "100" not in called_fragments
    assert "2026-05-19" not in called_fragments
    assert '"VIP专线A"' not in called_fragments


def test_vector_recall_uses_raw_ac_coverage_not_preselected_hits(monkeypatch) -> None:
    assets = OntologyAssets.from_default_resources()
    retriever = FakeMentionVectorRetriever()
    lexer = OntologyLexer(assets, vector_retriever=retriever)
    raw_matches = (
        _RawMatch(
            hit_id="ac-1",
            canonical_id="Service",
            mention_type="OBJECT",
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
            mention_type="RELATION",
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
    assert service_doc.mention_type == "OBJECT"
    assert service_doc.surface == "业务"
    assert source_role_doc.metadata["via_synonym_group"] == "SYN_SourceRole"
    assert service_doc.to_rag_fragment()["type"] == "mention_candidate"
    assert service_doc.to_rag_fragment()["metadata"]["canonical_id"] == "Service"
    assert not any(item.canonical_id.startswith("SYN_") for item in documents)
    assert not any(item.mention_type == "VALUE" for item in documents)


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
                        "mention_type": "RELATION",
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

    candidates = retriever.search("穿越", expected_mention_type="RELATION", top_k=5)

    assert seen_payloads == [
        {
                "query": "穿越",
                "top_k": 5,
                "collection": "nl2cypher_mention_candidates_v1",
                "filters": {"enabled": True, "mention_type": "RELATION"},
            }
        ]
    assert candidates == [
        MentionVectorCandidate(
            id="mention.REL_PATH_THROUGH.穿过",
            text="经过 途经 穿过 path through",
            canonical_id="REL_PATH_THROUGH",
            mention_type="RELATION",
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
    assert service["metadata"]["mention_type"] == "OBJECT"
