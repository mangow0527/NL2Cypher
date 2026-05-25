from __future__ import annotations

import re

import pytest

from services.cypher_generator_agent.app.runtime_pipeline import OntologyGenerationPipeline
from services.cypher_generator_agent.app.intent_layer.layer import IntentLayer
from services.cypher_generator_agent.app.intent_layer.models import Intent, IntentOutput, InitialShapeField
from services.cypher_generator_agent.app.lexical_layer.lexer import OntologyLexer
from services.cypher_generator_agent.app.lexical_layer.mention_vector_recall import MentionVectorCandidate
from services.cypher_generator_agent.app.clarification_layer.errors import ClarificationNeeded
from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_layer.object_role_selection import OntologyObjectRoleSelectionService
from services.cypher_generator_agent.app.ontology_layer.binding import OntologyBindingService
from services.cypher_generator_agent.app.ontology_layer.coreference import OntologyCoreferenceService
from services.cypher_generator_agent.app.ontology_layer.logical_planning import OntologyLogicalPlanningService
from services.cypher_generator_agent.app.ontology_layer.ontology_path_selection import (
    OntologyPathSelectionService,
    OntologyPathSelectionTrace,
    SelectedPath,
)
from services.cypher_generator_agent.app.ontology_layer.models import ContextSignal
from services.cypher_generator_agent.app.question_framing_layer.service import QuestionFramingService


class _FixtureIntentClassifier:
    def run(self, *, core_question: str, shape_signals: tuple[ContextSignal, ...]) -> IntentOutput:
        if "详细" in core_question or "详情" in core_question:
            return IntentOutput(
                intent=Intent(
                    primary="record_retrieval_query",
                    secondary="entity_detail_query",
                    source="fixture",
                    decision="accept",
                    confidence=0.9,
                ),
                planning_prompt_text="用户想查看某个对象的详细信息。",
                initial_shape={
                    "answer_type": InitialShapeField(
                        value="record_table",
                        source="taxonomy.secondary.default_answer_type",
                        decision="accept",
                        confidence=1.0,
                    ),
                    "projection_expected": InitialShapeField(
                        value=True,
                        source="taxonomy.secondary.shape_profile",
                        decision="accept",
                        confidence=1.0,
                    ),
                    "relation_resolution_expected": InitialShapeField(
                        value=False,
                        source="taxonomy.secondary.shape_profile",
                        decision="accept",
                        confidence=1.0,
                    ),
                    "path_answer_required": InitialShapeField(
                        value=False,
                        source="taxonomy.secondary.shape_profile",
                        decision="accept",
                        confidence=1.0,
                    ),
                },
                candidates=({"id": "C1", "primary": "record_retrieval_query", "secondary": "entity_detail_query"},),
                rule_signals_used=tuple(signal.text for signal in shape_signals),
                diagnostics={},
            )
        return IntentOutput(
            intent=Intent(
                primary="record_retrieval_query",
                secondary="related_record_query",
                source="fixture",
                decision="accept",
                confidence=0.9,
            ),
            planning_prompt_text="用户想查询相关记录，并返回某些字段。这个问题里既有过滤条件，也有对象之间的关系。",
            initial_shape={
                "answer_type": InitialShapeField(
                    value="attribute_table",
                    source="taxonomy.secondary.default_answer_type",
                    decision="accept",
                    confidence=1.0,
                ),
                "projection_expected": InitialShapeField(
                    value=True,
                    source="taxonomy.secondary.shape_profile",
                    decision="accept",
                    confidence=1.0,
                ),
                "relation_resolution_expected": InitialShapeField(
                    value=True,
                    source="taxonomy.secondary.shape_profile",
                    decision="pending",
                    confidence=0.8,
                    pending_until="step_3_3",
                ),
                "path_answer_required": InitialShapeField(
                    value=False,
                    source="taxonomy.secondary.shape_profile",
                    decision="accept",
                    confidence=1.0,
                ),
            },
            candidates=({"id": "C1", "primary": "record_retrieval_query", "secondary": "related_record_query"},),
            rule_signals_used=tuple(signal.text for signal in shape_signals),
            diagnostics={},
        )


class _FixtureObjectRoleSelectionSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        class Selection:
            raw_response = "\n".join(
                f"选择 {candidate_id}：path_subject。理由：fixture"
                for candidate_id in variables.get("allowed_candidate_ids", [])
            )

        assert prompt_name == "object_role_selection"
        assert "object_candidate_list" in variables
        assert "allowed_object_roles" in variables
        return Selection()


class _ProjectionSubjectObjectRoleSelectionSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        class Selection:
            raw_response = "\n".join(
                f"选择 {candidate_id}：projection_subject。理由：fixture"
                for candidate_id in variables.get("allowed_candidate_ids", [])
            )

        assert prompt_name == "object_role_selection"
        return Selection()


class _ReturnSubjectObjectRoleSelectionSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        class Selection:
            raw_response = "\n".join(
                f"选择 {candidate_id}：filter_subject、return_subject。理由：fixture"
                for candidate_id in variables.get("allowed_candidate_ids", [])
            )

        assert prompt_name == "object_role_selection"
        return Selection()


class _ServiceElemTypeQuestionFramingClient:
    def complete(self, prompt: str) -> str:
        return (
            "原子问题：\n"
            "1. 所有服务 ｜ 找什么对象\n"
            "2. 元素类型 ｜ 最后返回什么\n"
        )


class _ServiceInfoQuestionFramingClient:
    def complete(self, prompt: str) -> str:
        return "原子问题：\n1. 所有的服务信息 ｜ 找什么对象 + 最后返回什么\n"


class _ServiceTunnelBothSidesQuestionFramingClient:
    def complete(self, prompt: str) -> str:
        return (
            "原子问题：\n"
            "1. 所有服务与隧道之间的连接关系 ｜ 找什么对象 + 通过什么关系继续找\n"
            "2. 双方的元素类型 ｜ 最后返回什么\n"
        )


class _GenericInfoVectorRetriever:
    provider = "fake_generic_info_vector"

    def search(
        self,
        fragment: str,
        *,
        expected_mention_type: str | None,
        top_k: int,
    ) -> list[MentionVectorCandidate]:
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


class _RelationPathStructuralVectorRetriever:
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


class _NodeSuffixVectorRetriever:
    provider = "fake_node_suffix_vector"

    def search(
        self,
        fragment: str,
        *,
        expected_mention_type: str | None,
        top_k: int,
    ) -> list[MentionVectorCandidate]:
        if fragment != "节点":
            return []
        return [
            MentionVectorCandidate(
                id="mention.REL_TUNNEL_SRC.节点",
                text="节点 tunnel source endpoint",
                canonical_id="REL_TUNNEL_SRC",
                mention_type="RELATION",
                surface="源网元",
                score=0.94,
                metadata={"dictionary": "relation_predicates"},
            )
        ]


class _TunnelNodeObjectRoleSelectionSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        question = str(variables.get("question") or "")
        candidate_lines = str(variables.get("object_candidate_list") or "")
        rows: list[str] = []
        for line in candidate_lines.splitlines():
            match = re.match(r"- (SM\d+)：\"(.+?)\"", line)
            if match is None:
                continue
            candidate_id, surface = match.groups()
            if surface in {"服务", "业务"}:
                roles = "path_subject"
            elif surface == "使用的隧道":
                if "网络设备" in question:
                    roles = "path_subject"
                elif "名称" in question or "ID" in question:
                    roles = "path_subject、projection_subject"
                else:
                    roles = "path_subject、return_subject"
            elif surface == "网络设备":
                roles = "path_subject、return_subject"
            elif surface in {"目的网元", "源网元"}:
                roles = "path_subject、return_subject"
            else:
                roles = "path_subject"
            rows.append(f"选择 {candidate_id}：{roles}。理由：fixture")

        class Selection:
            raw_response = "\n".join(rows)

        assert prompt_name == "object_role_selection"
        return Selection()


class _ConservativeTunnelNodeObjectRoleSelectionSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        candidate_lines = str(variables.get("object_candidate_list") or "")
        rows: list[str] = []
        for line in candidate_lines.splitlines():
            match = re.match(r"- (SM\d+)：\"(.+?)\"", line)
            if match is None:
                continue
            candidate_id, _surface = match.groups()
            rows.append(f"选择 {candidate_id}：path_subject。理由：fixture")

        class Selection:
            raw_response = "\n".join(rows)

        assert prompt_name == "object_role_selection"
        return Selection()


class _ConflictingTunnelNodeObjectRoleSelectionSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        candidate_lines = str(variables.get("object_candidate_list") or "")
        rows: list[str] = []
        for line in candidate_lines.splitlines():
            match = re.match(r"- (SM\d+)：\"(.+?)\"", line)
            if match is None:
                continue
            candidate_id, surface = match.groups()
            roles = "path_subject、return_subject" if surface in {"服务", "业务"} else "path_subject、projection_subject"
            rows.append(f"选择 {candidate_id}：{roles}。理由：fixture")

        class Selection:
            raw_response = "\n".join(rows)

        assert prompt_name == "object_role_selection"
        return Selection()


class _ProjectionAttributeIntentClassifier:
    def run(self, *, core_question: str, shape_signals: tuple[ContextSignal, ...]) -> IntentOutput:
        return IntentOutput(
            intent=Intent(
                primary="record_retrieval_query",
                secondary="attribute_projection_query",
                source="fixture",
                decision="accept",
                confidence=0.9,
            ),
            planning_prompt_text="用户想返回对象的指定字段。",
            initial_shape={
                "answer_type": InitialShapeField(
                    value="attribute_table",
                    source="taxonomy.secondary.default_answer_type",
                    decision="accept",
                    confidence=1.0,
                ),
                "projection_expected": InitialShapeField(
                    value=True,
                    source="taxonomy.secondary.shape_profile",
                    decision="accept",
                    confidence=1.0,
                ),
                "relation_resolution_expected": InitialShapeField(
                    value=False,
                    source="taxonomy.secondary.shape_profile",
                    decision="accept",
                    confidence=1.0,
                ),
                "path_answer_required": InitialShapeField(
                    value=False,
                    source="taxonomy.secondary.shape_profile",
                    decision="accept",
                    confidence=1.0,
                ),
            },
            candidates=(),
            rule_signals_used=tuple(signal.text for signal in shape_signals),
            diagnostics={},
        )


class _SameInstanceCoreferenceSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        class Selection:
            raw_response = "选择 C1。理由：fixture"

        assert prompt_name == "coreference_selection"
        return Selection()


class _FixtureBindingSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        class Selection:
            raw_response = (
                f"选择 {_binding_candidate_id(str(variables.get('question') or ''), str(variables.get('binding_candidate_list_with_ids') or ''), str(variables.get('signal_list_with_ids') or ''))}。"
                "理由：fixture"
            )

        assert prompt_name == "binding_selection"
        return Selection()


class _RecordingExplicitLogicalPlanningService:
    def __init__(self) -> None:
        self.delegate = OntologyLogicalPlanningService(
            assets=OntologyAssets.from_default_resources(),
            coreference_service=OntologyCoreferenceService(llm_selector=_SameInstanceCoreferenceSelector()),
            binding_service=OntologyBindingService(llm_selector=_FixtureBindingSelector()),
        )
        self.calls: list[str] = []

    def resolve_coreference(self, *args, **kwargs):
        self.calls.append("step_3_4_coreference")
        return self.delegate.resolve_coreference(*args, **kwargs)

    def bind(self, *args, **kwargs):
        self.calls.append("step_3_5_binding")
        return self.delegate.bind(*args, **kwargs)

    def finalize_shape(self, *args, **kwargs):
        self.calls.append("step_3_6_shape_finalization")
        return self.delegate.finalize_shape(*args, **kwargs)


def _binding_candidate_id(question: str, candidate_lines: str, signal_lines: str) -> str:
    if "隧道" in question and "ID" in question:
        candidate_id = _candidate_for_attribute(candidate_lines, "Tunnel.id")
        if candidate_id is not None:
            return candidate_id
    for keyword, attribute in (
        ("源网元", "NetworkElement.ip_address"),
        ("IP", "NetworkElement.ip_address"),
        ("IETF", "Tunnel.ietf_standard"),
        ("元素类型", "Service.elem_type"),
        ("隧道", "Tunnel.name"),
        ("端口", "Port.name"),
        ("带宽", "Service.bandwidth"),
    ):
        if keyword in question:
            candidate_id = _candidate_for_attribute(candidate_lines, attribute)
            if candidate_id is not None:
                return candidate_id
    signal_match = re.search(r"supports=([^\\s]+)", signal_lines)
    if signal_match is not None:
        return signal_match.group(1).split(",", 1)[0]
    for preferred in ("Tunnel.name", "Tunnel.ietf_standard", "NetworkElement.ip_address", "Service.bandwidth"):
        candidate_id = _candidate_for_attribute(candidate_lines, preferred)
        if candidate_id is not None:
            return candidate_id
    match = re.search(r"(bc_[A-Za-z0-9_]+):", candidate_lines)
    if match:
        return match.group(1)
    raise AssertionError("binding fixture did not receive candidates")


def _candidate_for_attribute(candidate_lines: str, attribute: str) -> str | None:
    for line in candidate_lines.splitlines():
        if f"attribute={attribute}" not in line:
            continue
        match = re.match(r"(bc_[A-Za-z0-9_]+):", line)
        if match:
            return match.group(1)
    return None


class _RecordingPathSelectionService:
    def __init__(self, trace: OntologyPathSelectionTrace) -> None:
        self.trace = trace
        self.calls: list[dict[str, object]] = []

    def fill(
        self,
        *,
        ontology_mapping: dict[str, object],
        question: str,
        lexer_trace: object | None = None,
    ) -> OntologyPathSelectionTrace:
        self.calls.append(
            {
                "ontology_mapping": ontology_mapping,
                "question": question,
                "lexer_trace": lexer_trace,
            }
        )
        return self.trace


def _path_selection_trace(
    relation_chain: tuple[str, ...] = ("SERVICE_USES_TUNNEL",),
    *,
    clarification: dict[str, object] | None = None,
) -> OntologyPathSelectionTrace:
    selected_paths = ()
    shape_updates: dict[str, InitialShapeField] = {
        "relation_resolution_expected": InitialShapeField(
            value=True,
            source="ontology_path_selection",
            decision="clarify" if clarification is not None else "accept",
            confidence=1.0,
            pending_until="user_clarification" if clarification is not None else None,
        )
    }
    if clarification is None:
        selected_paths = (
            SelectedPath(
                request_id="PR1",
                path_id="P1",
                relation_chain=relation_chain,
                evidence_ids=("PE1",),
                selected_by="fixture",
                reason="pipeline fixture",
            ),
        )
        shape_updates = {
            "hop_count": InitialShapeField(
                value=len(relation_chain),
                source="ontology_path_selection",
                decision="accept",
                confidence=1.0,
            ),
            "relation_chain_type": InitialShapeField(
                value="fixed_chain",
                source="ontology_path_selection",
                decision="accept",
                confidence=1.0,
            ),
        }
    return OntologyPathSelectionTrace(
        path_requests=(),
        candidate_paths=(),
        llm_raw_output="",
        selected_paths=selected_paths,
        shape_updates=shape_updates,
        clarification=clarification,
    )


def _pipeline() -> OntologyGenerationPipeline:
    assets = OntologyAssets.from_default_resources()
    return OntologyGenerationPipeline(
        assets=assets,
        intent_layer=_FixtureIntentClassifier(),  # type: ignore[arg-type]
        object_role_selection_service=OntologyObjectRoleSelectionService(llm_selector=_FixtureObjectRoleSelectionSelector()),
        logical_planning_service=OntologyLogicalPlanningService(
            assets=assets,
            coreference_service=OntologyCoreferenceService(llm_selector=_SameInstanceCoreferenceSelector()),
            binding_service=OntologyBindingService(llm_selector=_FixtureBindingSelector()),
        ),
    )


def _projection_attribute_pipeline() -> OntologyGenerationPipeline:
    assets = OntologyAssets.from_default_resources()
    return OntologyGenerationPipeline(
        assets=assets,
        intent_layer=_ProjectionAttributeIntentClassifier(),  # type: ignore[arg-type]
        object_role_selection_service=OntologyObjectRoleSelectionService(
            llm_selector=_ProjectionSubjectObjectRoleSelectionSelector()
        ),
        logical_planning_service=OntologyLogicalPlanningService(
            assets=assets,
            coreference_service=OntologyCoreferenceService(llm_selector=_SameInstanceCoreferenceSelector()),
            binding_service=OntologyBindingService(llm_selector=_FixtureBindingSelector()),
        ),
    )


def _entity_list_pipeline() -> OntologyGenerationPipeline:
    assets = OntologyAssets.from_default_resources()
    return OntologyGenerationPipeline(
        assets=assets,
        object_role_selection_service=OntologyObjectRoleSelectionService(
            llm_selector=_ReturnSubjectObjectRoleSelectionSelector()
        ),
        logical_planning_service=OntologyLogicalPlanningService(
            assets=assets,
            coreference_service=OntologyCoreferenceService(llm_selector=_SameInstanceCoreferenceSelector()),
            binding_service=OntologyBindingService(llm_selector=_FixtureBindingSelector()),
        ),
    )


def _question_framing_projection_pipeline() -> OntologyGenerationPipeline:
    assets = OntologyAssets.from_default_resources()
    return OntologyGenerationPipeline(
        assets=assets,
        question_framing_service=QuestionFramingService(client=_ServiceElemTypeQuestionFramingClient()),
        intent_layer=IntentLayer(),
        object_role_selection_service=OntologyObjectRoleSelectionService(
            llm_selector=_ProjectionSubjectObjectRoleSelectionSelector()
        ),
        logical_planning_service=OntologyLogicalPlanningService(
            assets=assets,
            coreference_service=OntologyCoreferenceService(llm_selector=_SameInstanceCoreferenceSelector()),
            binding_service=OntologyBindingService(llm_selector=_FixtureBindingSelector()),
        ),
    )


def _question_framing_service_info_pipeline() -> OntologyGenerationPipeline:
    assets = OntologyAssets.from_default_resources()
    return OntologyGenerationPipeline(
        assets=assets,
        lexer=OntologyLexer(assets, vector_retriever=_GenericInfoVectorRetriever()),
        question_framing_service=QuestionFramingService(client=_ServiceInfoQuestionFramingClient()),
        intent_layer=IntentLayer(),
        object_role_selection_service=OntologyObjectRoleSelectionService(
            llm_selector=_ReturnSubjectObjectRoleSelectionSelector()
        ),
        logical_planning_service=OntologyLogicalPlanningService(
            assets=assets,
            coreference_service=OntologyCoreferenceService(llm_selector=_SameInstanceCoreferenceSelector()),
            binding_service=OntologyBindingService(llm_selector=_FixtureBindingSelector()),
        ),
    )


def _service_tunnel_both_sides_pipeline(
    retriever: _RelationPathStructuralVectorRetriever,
) -> OntologyGenerationPipeline:
    assets = OntologyAssets.from_default_resources()
    return OntologyGenerationPipeline(
        assets=assets,
        lexer=OntologyLexer(assets, vector_retriever=retriever),
        question_framing_service=QuestionFramingService(client=_ServiceTunnelBothSidesQuestionFramingClient()),
        intent_layer=_FixtureIntentClassifier(),  # type: ignore[arg-type]
        object_role_selection_service=OntologyObjectRoleSelectionService(
            llm_selector=_FixtureObjectRoleSelectionSelector()
        ),
        logical_planning_service=OntologyLogicalPlanningService(
            assets=assets,
            coreference_service=OntologyCoreferenceService(llm_selector=_SameInstanceCoreferenceSelector()),
            binding_service=OntologyBindingService(llm_selector=_FixtureBindingSelector()),
        ),
    )


def _tunnel_node_pipeline() -> OntologyGenerationPipeline:
    assets = OntologyAssets.from_default_resources()
    return OntologyGenerationPipeline(
        assets=assets,
        lexer=OntologyLexer(assets, vector_retriever=_NodeSuffixVectorRetriever()),
        intent_layer=IntentLayer(),
        object_role_selection_service=OntologyObjectRoleSelectionService(
            llm_selector=_TunnelNodeObjectRoleSelectionSelector()
        ),
        logical_planning_service=OntologyLogicalPlanningService(
            assets=assets,
            coreference_service=OntologyCoreferenceService(llm_selector=_SameInstanceCoreferenceSelector()),
            binding_service=OntologyBindingService(llm_selector=_FixtureBindingSelector()),
        ),
    )


def _tunnel_node_pipeline_with_selector(selector: object) -> OntologyGenerationPipeline:
    assets = OntologyAssets.from_default_resources()
    return OntologyGenerationPipeline(
        assets=assets,
        lexer=OntologyLexer(assets, vector_retriever=_NodeSuffixVectorRetriever()),
        intent_layer=IntentLayer(),
        object_role_selection_service=OntologyObjectRoleSelectionService(llm_selector=selector),
        logical_planning_service=OntologyLogicalPlanningService(
            assets=assets,
            coreference_service=OntologyCoreferenceService(llm_selector=_SameInstanceCoreferenceSelector()),
            binding_service=OntologyBindingService(llm_selector=_FixtureBindingSelector()),
        ),
    )


def test_ontology_generation_pipeline_generates_golden_service_tunnel_source_ne_query() -> None:
    pipeline = _pipeline()

    result = pipeline.generate(
        "查询金牌服务经过的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址",
        trace_id="trace-golden",
    )

    assert result.status == "generated"
    assert result.cypher == (
        "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)-[:TUNNEL_SRC]->(ne:NetworkElement)\n"
        "WHERE s.quality_of_service = 'Gold'\n"
        "RETURN t.ietf_standard AS tunnel_ietf_standard, ne.ip_address AS source_ne_ip_address"
    )
    assert result.trace.trace_id == "trace-golden"
    mention_ids = [mention.canonical_id for mention in result.trace.lexer.mentions]
    assert mention_ids == [
        "OP_QUERY",
        "ServiceQuality.Gold",
        "Service",
        "REL_PATH_THROUGH",
        "Tunnel",
        "REL_TUNNEL_SRC",
        "OP_RETURN_FIELD",
        "Tunnel",
        "Tunnel.ietf_standard",
        "REL_TUNNEL_SRC",
        "NetworkElement.ip_address",
    ]
    ietf_mention = result.trace.lexer.mentions[8]
    assert set(ietf_mention.metadata["candidate_refs"]) == {"Protocol.standard", "Tunnel.ietf_standard"}
    assert result.trace.intent.intent.primary == "record_retrieval_query"
    assert result.trace.intent.intent.secondary == "related_record_query"
    assert result.trace.intent.initial_shape["answer_type"].value == "attribute_table"
    assert result.trace.intent.initial_shape["relation_resolution_expected"].value is True
    assert result.trace.intent.initial_shape["relation_resolution_expected"].pending_until == "step_3_3"
    assert result.trace.intent.initial_shape["path_answer_required"].value is False
    assert [edge.relation for edge in result.logical_plan.edges] == [
        "SERVICE_USES_TUNNEL",
        "TUNNEL_SRC",
    ]
    assert [projection.alias for projection in result.logical_plan.projections] == [
        "tunnel_ietf_standard",
        "source_ne_ip_address",
    ]


def test_ontology_generation_pipeline_projects_bare_id_under_service_context() -> None:
    pipeline = _pipeline()

    result = pipeline.generate("查询所有服务的名称、带宽和ID。", trace_id="trace-service-id")

    assert result.status == "generated"
    assert result.cypher == (
        "MATCH (s:Service)\n"
        "RETURN s.name AS service_name, s.bandwidth AS service_bandwidth, s.id AS service_id"
    )
    id_mentions = [mention for mention in result.trace.lexer.mentions if mention.surface == "ID"]
    assert len(id_mentions) == 1
    assert "Service.id" in id_mentions[0].metadata["candidate_refs"]


def test_ontology_generation_pipeline_projects_service_latency_and_type() -> None:
    pipeline = _pipeline()

    result = pipeline.generate("查询所有服务的名称、类型和时延。", trace_id="trace-service-latency-type")

    assert result.status == "generated"
    assert result.cypher == (
        "MATCH (s:Service)\n"
        "RETURN s.name AS service_name, s.elem_type AS service_elem_type, s.latency AS service_latency"
    )


def test_ontology_generation_pipeline_projects_service_internal_id_name_and_device_type() -> None:
    pipeline = _pipeline()

    result = pipeline.generate("查询所有服务的内部ID、名称和设备类型。", trace_id="trace-service-internal-id-type")

    assert result.status == "generated"
    assert result.cypher == "MATCH (s:Service)\nRETURN id(s) AS id, s.name AS name, s.elem_type AS type"
    assert [node.type for node in result.logical_plan.nodes] == ["Service"]
    assert [(item.attribute, item.alias) for item in result.logical_plan.projections] == [
        ("__internal_id", "id"),
        ("name", "name"),
        ("elem_type", "type"),
    ]
    internal_id_mentions = [mention for mention in result.trace.lexer.mentions if mention.surface == "内部ID"]
    assert len(internal_id_mentions) == 1
    assert "Service.id" in internal_id_mentions[0].metadata["candidate_refs"]
    type_mentions = [mention for mention in result.trace.lexer.mentions if mention.surface == "设备类型"]
    assert len(type_mentions) == 1
    assert "Service.elem_type" in type_mentions[0].metadata["candidate_refs"]


def test_ontology_generation_pipeline_projects_service_netype_under_service_subject() -> None:
    pipeline = _projection_attribute_pipeline()

    result = pipeline.generate("查询所有服务的ID、名称和网元类型。", trace_id="trace-service-netype")

    assert result.status == "generated"
    assert result.cypher == (
        "MATCH (s:Service)\n"
        "RETURN s.id AS service_id, s.name AS service_name, s.elem_type AS service_elem_type"
    )
    assert [node.type for node in result.logical_plan.nodes] == ["Service"]
    assert [edge.relation for edge in result.logical_plan.edges] == []
    assert [(item.attribute, item.alias) for item in result.logical_plan.projections] == [
        ("id", "service_id"),
        ("name", "service_name"),
        ("elem_type", "service_elem_type"),
    ]


def test_ontology_generation_pipeline_composes_literal_comparison_filter() -> None:
    pipeline = _projection_attribute_pipeline()

    result = pipeline.generate("查询延迟小于20ms的所有金牌服务的ID", trace_id="trace-literal-predicate")

    assert result.status == "generated"
    assert result.cypher == (
        "MATCH (s:Service)\n"
        "WHERE s.latency < 20 AND s.quality_of_service = 'Gold'\n"
        "RETURN s.id AS service_id"
    )
    assert [(item.attr, item.operator, item.value) for item in result.logical_plan.nodes[0].filters] == [
        ("latency", "<", 20),
        ("quality_of_service", "=", "Gold"),
    ]
    assert [item.surface for item in result.trace.lexer.mentions if item.mention_type == "QUANTIFIER"] == ["所有"]
    assert result.trace.binding.shape_updates["filter_level"].value == "multi_predicate"
    assert result.trace.intent.intent.secondary == "attribute_projection_query"


def test_question_framing_return_content_atom_drives_service_elem_type_projection() -> None:
    pipeline = _question_framing_projection_pipeline()

    result = pipeline.generate("查询所有服务的元素类型。", trace_id="trace-service-elem-type")

    assert result.status == "generated"
    assert result.cypher == "MATCH (s:Service)\nRETURN s.elem_type AS service_elem_type"
    assert result.trace.intent.intent.secondary == "attribute_projection_query"
    assert any("RETURN_CONTENT" in signal.supports for signal in result.trace.lexer.context_signals)
    assert result.logical_plan.node_returns == ()
    assert [(item.attribute, item.alias) for item in result.logical_plan.projections] == [
        ("elem_type", "service_elem_type")
    ]
    selected_roles = result.trace.ontology_mapping.to_dict()["ontology_objects"][0]["selected_roles"]
    assert selected_roles == ["projection_subject"]


def test_ontology_generation_pipeline_composes_identifier_filter_and_dedupes_projection_attribute() -> None:
    pipeline = _projection_attribute_pipeline()

    result = pipeline.generate(
        "查询名称为 Service_002 的服务的 ID、名称和服务质量。",
        trace_id="trace-service-name-identifier-filter",
    )

    assert result.status == "generated"
    assert result.cypher == (
        "MATCH (s:Service)\n"
        "WHERE s.name = 'Service_002'\n"
        "RETURN s.id AS service_id, s.name AS service_name, "
        "s.quality_of_service AS service_quality_of_service"
    )
    assert [(item.attr, item.operator, item.value) for item in result.logical_plan.nodes[0].filters] == [
        ("name", "=", "Service_002")
    ]
    assert [(item.attribute, item.alias) for item in result.logical_plan.projections] == [
        ("id", "service_id"),
        ("name", "service_name"),
        ("quality_of_service", "service_quality_of_service"),
    ]
    assert any(
        mention.surface == "Service_002" and mention.mention_type == "LITERAL_VALUE"
        for mention in result.trace.lexer.mentions
    )


def test_ontology_generation_pipeline_keeps_detail_node_with_explicit_projection_fields() -> None:
    pipeline = _pipeline()

    result = pipeline.generate(
        "查询名称为 Service_003 的服务的 ID、服务质量等级及详细信息。",
        trace_id="trace-service-name-fields-and-detail",
    )

    assert result.status == "generated"
    assert result.cypher == (
        "MATCH (s:Service)\n"
        "WHERE s.name = 'Service_003'\n"
        "RETURN s.id AS service_id, s.quality_of_service AS service_quality_of_service, s"
    )
    assert [(item.attribute, item.alias) for item in result.logical_plan.projections] == [
        ("id", "service_id"),
        ("quality_of_service", "service_quality_of_service"),
    ]
    assert [(item.node, item.alias) for item in result.logical_plan.node_returns] == [("s1", "s")]


def test_pipeline_returns_tunnel_node_for_service_used_tunnel_node_info() -> None:
    pipeline = _tunnel_node_pipeline()

    result = pipeline.generate("查询所有业务使用的隧道节点信息。", trace_id="trace-service-used-tunnel-node-info")

    assert result.status == "generated"
    assert result.cypher == "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)\nRETURN t"
    assert [(item.type, item.alias) for item in result.logical_plan.nodes] == [("Service", "s"), ("Tunnel", "t")]
    assert [edge.relation for edge in result.logical_plan.edges] == ["SERVICE_USES_TUNNEL"]
    assert [(item.node, item.alias) for item in result.logical_plan.node_returns] == [("t1", "t")]


def test_pipeline_returns_tunnel_node_for_service_used_tunnel_node_without_endpoint_noise() -> None:
    pipeline = _tunnel_node_pipeline()

    result = pipeline.generate("查询所有业务使用的隧道节点。", trace_id="trace-service-used-tunnel-node")

    assert result.status == "generated"
    assert result.cypher == "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)\nRETURN t"
    assert not any(mention.canonical_id == "REL_TUNNEL_SRC" for mention in result.trace.lexer.mentions)
    assert [edge.relation for edge in result.logical_plan.edges] == ["SERVICE_USES_TUNNEL"]
    assert [(item.node, item.alias) for item in result.logical_plan.node_returns] == [("t1", "t")]


def test_pipeline_keeps_tunnel_detail_node_with_tunnel_projection_fields() -> None:
    pipeline = _tunnel_node_pipeline()

    result = pipeline.generate(
        "查询所有服务使用的隧道的名称、ID及详细信息。",
        trace_id="trace-service-used-tunnel-fields-and-detail",
    )

    assert result.status == "generated"
    assert result.cypher == (
        "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)\n"
        "RETURN t.name AS tunnel_name, t.id AS tunnel_id, t"
    )
    assert [(item.attribute, item.alias) for item in result.logical_plan.projections] == [
        ("name", "tunnel_name"),
        ("id", "tunnel_id"),
    ]
    assert [(item.node, item.alias) for item in result.logical_plan.node_returns] == [("t1", "t")]


def test_pipeline_returns_path_through_network_devices_without_source_endpoint_noise() -> None:
    pipeline = _tunnel_node_pipeline()

    result = pipeline.generate(
        "查询所有服务使用的隧道所经过的网络设备节点。",
        trace_id="trace-service-used-tunnel-path-through-devices",
    )

    assert result.status == "generated"
    assert result.cypher == (
        "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)-[:PATH_THROUGH]->(ne:NetworkElement)\n"
        "RETURN ne"
    )
    assert not any(mention.canonical_id == "REL_TUNNEL_SRC" for mention in result.trace.lexer.mentions)
    assert [edge.relation for edge in result.logical_plan.edges] == ["SERVICE_USES_TUNNEL", "PATH_THROUGH"]
    assert [(item.node, item.alias) for item in result.logical_plan.node_returns] == [("n1", "ne")]


def test_pipeline_defaults_node_detail_return_to_terminal_tunnel_when_roles_are_conservative() -> None:
    pipeline = _tunnel_node_pipeline_with_selector(_ConservativeTunnelNodeObjectRoleSelectionSelector())

    result = pipeline.generate("查询所有业务使用的隧道节点信息。", trace_id="trace-conservative-tunnel-node-info")

    assert result.status == "generated"
    assert result.cypher == "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)\nRETURN t"
    assert [(item.node, item.alias) for item in result.logical_plan.node_returns] == [("t1", "t")]


def test_pipeline_defaults_bare_node_return_to_terminal_tunnel_when_roles_are_conservative() -> None:
    pipeline = _tunnel_node_pipeline_with_selector(_ConservativeTunnelNodeObjectRoleSelectionSelector())

    result = pipeline.generate("查询所有业务使用的隧道节点。", trace_id="trace-conservative-tunnel-node")

    assert result.status == "generated"
    assert result.cypher == "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)\nRETURN t"
    assert [(item.node, item.alias) for item in result.logical_plan.node_returns] == [("t1", "t")]


def test_pipeline_defaults_node_return_to_terminal_network_device_when_roles_are_conservative() -> None:
    pipeline = _tunnel_node_pipeline_with_selector(_ConservativeTunnelNodeObjectRoleSelectionSelector())

    result = pipeline.generate(
        "查询所有服务使用的隧道所经过的网络设备节点。",
        trace_id="trace-conservative-path-through-devices",
    )

    assert result.status == "generated"
    assert result.cypher == (
        "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)-[:PATH_THROUGH]->(ne:NetworkElement)\n"
        "RETURN ne"
    )
    assert [(item.node, item.alias) for item in result.logical_plan.node_returns] == [("n1", "ne")]


def test_pipeline_prefers_projection_subject_target_over_anchor_return_subject_for_node_detail() -> None:
    pipeline = _tunnel_node_pipeline_with_selector(_ConflictingTunnelNodeObjectRoleSelectionSelector())

    result = pipeline.generate("查询所有服务使用的隧道节点信息。", trace_id="trace-conflicting-tunnel-node-info")

    assert result.status == "generated"
    assert result.cypher == "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)\nRETURN t"
    assert [(item.node, item.alias) for item in result.logical_plan.node_returns] == [("t1", "t")]


def test_ontology_generation_pipeline_uses_physical_raw_value_for_service_type_filter() -> None:
    pipeline = _projection_attribute_pipeline()

    result = pipeline.generate(
        "查询类型为MPLS-VPN的服务的ID、名称和带宽。",
        trace_id="trace-service-type-raw-filter",
    )

    assert result.status == "generated"
    assert result.cypher == (
        "MATCH (s:Service)\n"
        "WHERE s.elem_type = 'MPLS-VPN'\n"
        "RETURN s.id AS service_id, s.name AS service_name, s.bandwidth AS service_bandwidth"
    )
    assert [(item.attr, item.operator, item.value) for item in result.logical_plan.nodes[0].filters] == [
        ("elem_type", "=", "MPLS-VPN")
    ]
    assert result.trace.binding.filters[0].result["value_id"] == "ServiceType.MPLS-VPN"
    assert result.trace.binding.filters[0].result["value_kind"] == "enum"


def test_ontology_generation_pipeline_returns_service_node_for_enum_filter_entity_list() -> None:
    pipeline = _entity_list_pipeline()

    result = pipeline.generate("查询所有服务质量等级为Bronze的服务。", trace_id="trace-service-quality-entity-list")

    assert result.status == "generated"
    assert result.cypher == "MATCH (s:Service)\nWHERE s.quality_of_service = 'Bronze'\nRETURN s"
    assert [(item.attr, item.operator, item.value) for item in result.logical_plan.nodes[0].filters] == [
        ("quality_of_service", "=", "Bronze")
    ]
    assert result.logical_plan.projections == ()
    assert result.logical_plan.node_returns[0].node == "s1"


def test_question_framing_generic_service_info_returns_node_not_vector_attribute() -> None:
    pipeline = _question_framing_service_info_pipeline()

    result = pipeline.generate("查询所有的服务信息。", trace_id="trace-service-info")

    assert result.status == "generated"
    assert result.cypher == "MATCH (s:Service)\nRETURN s"
    assert result.trace.intent.intent.secondary == "entity_list_query"
    assert not any(mention.canonical_id == "Link.status" for mention in result.trace.lexer.mentions)
    assert result.logical_plan.projections == ()
    assert result.logical_plan.node_returns[0].node == "s1"


def test_pipeline_generates_service_tunnel_endpoint_elem_type_projection_without_structural_noise() -> None:
    retriever = _RelationPathStructuralVectorRetriever()
    pipeline = _service_tunnel_both_sides_pipeline(retriever)

    result = pipeline.generate(
        "查询所有服务与隧道之间的连接关系，并返回双方的元素类型。",
        trace_id="trace-service-tunnel-both-sides-type",
    )

    assert result.status == "generated"
    assert result.cypher == (
        "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)\n"
        "RETURN s.elem_type AS service_elem_type, t.elem_type AS tunnel_elem_type"
    )
    assert [edge.relation for edge in result.logical_plan.edges] == ["SERVICE_USES_TUNNEL"]
    assert [(item.attribute, item.alias) for item in result.logical_plan.projections] == [
        ("elem_type", "service_elem_type"),
        ("elem_type", "tunnel_elem_type"),
    ]
    assert not any(mention.canonical_id == "Link" for mention in result.trace.lexer.mentions)
    assert not any(mention.canonical_id == "Fiber.location" for mention in result.trace.lexer.mentions)
    assert not any(mention.canonical_id == "NetworkElement.software_version" for mention in result.trace.lexer.mentions)
    called_fragments = [call["fragment"] for call in retriever.calls]
    assert "之间" not in called_fragments
    assert "双方的元素" not in called_fragments


def test_ontology_generation_pipeline_returns_node_for_entity_detail_query() -> None:
    pipeline = _pipeline()

    result = pipeline.generate("查询所有服务的详细信息。", trace_id="trace-service-details")

    assert result.status == "generated"
    assert result.cypher == "MATCH (s:Service)\nRETURN s"
    assert result.logical_plan.node_returns[0].node == "s1"
    assert result.trace.to_dict()["shape_finalization"]["logical_plan"]["node_returns"] == [
        {"node": "s1", "alias": "s"}
    ]


def test_ontology_generation_pipeline_exposes_replay_evidence_for_each_step() -> None:
    pipeline = _pipeline()

    result = pipeline.generate("查询金牌服务使用的隧道名称", trace_id="trace-replay")
    trace = result.trace.to_dict()

    assert set(trace) == {
        "schema_version",
        "trace_id",
        "preprocessing",
        "lexer",
        "intent",
        "object_role_selection",
        "ontology_mapping",
        "ontology_path_selection",
        "coreference",
        "binding",
        "shape_finalization",
        "validator",
        "compiler",
    }
    assert trace["schema_version"] == "cga_trace_v2"
    assert trace["preprocessing"]["accepted"] is True
    assert trace["lexer"]["question"] == "查询金牌服务使用的隧道名称"
    assert trace["lexer"]["ac_matches"]
    assert trace["intent"]["rule_signals_used"]
    assert trace["object_role_selection"]["object_role_selection"]["selected_objects"]
    assert trace["ontology_path_selection"]["selected_paths"]
    assert trace["ontology_path_selection"]["candidate_paths"]
    assert trace["coreference"]["merged_nodes"]
    assert trace["binding"]["projections"]
    assert trace["shape_finalization"]["precheck_result"]["passed"] is True
    assert trace["validator"]["checks"]
    assert trace["compiler"]["cypher"] == result.cypher


def test_ontology_generation_pipeline_uses_preprocessed_core_question_before_lexing() -> None:
    pipeline = _pipeline()

    result = pipeline.generate(
        "你好，现在就是我们遇到了一些咨询类的问题，所以需要查询一下金牌服务 "
        "哦不对是银牌服务所使用的隧道和他的源网元，然后你需要给我返回隧道的IETF标准和源网元的IP地址，谢谢啦！",
        trace_id="trace-preprocessed",
    )

    trace = result.trace.to_dict()
    assert trace["preprocessing"]["accepted"] is True
    assert trace["preprocessing"]["core_question"] == (
        "银牌服务所使用的隧道和其源网元，返回隧道的IETF标准和源网元的IP地址"
    )
    assert trace["lexer"]["question"] == trace["preprocessing"]["core_question"]
    assert "Gold" not in result.cypher
    assert "WHERE s.quality_of_service = 'Silver'" in result.cypher
    assert "ne.ip_address AS source_ne_ip_address" in result.cypher


def test_runtime_pipeline_calls_step_3_3_path_selection_service() -> None:
    path_selection = _RecordingPathSelectionService(_path_selection_trace())
    pipeline = OntologyGenerationPipeline(
        assets=OntologyAssets.from_default_resources(),
        intent_layer=_FixtureIntentClassifier(),  # type: ignore[arg-type]
        object_role_selection_service=OntologyObjectRoleSelectionService(llm_selector=_FixtureObjectRoleSelectionSelector()),
        path_selection_service=path_selection,  # type: ignore[arg-type]
        logical_planning_service=OntologyLogicalPlanningService(
            assets=OntologyAssets.from_default_resources(),
            coreference_service=OntologyCoreferenceService(llm_selector=_SameInstanceCoreferenceSelector()),
            binding_service=OntologyBindingService(llm_selector=_FixtureBindingSelector()),
        ),
    )

    result = pipeline.generate("查询金牌服务使用的隧道名称", trace_id="trace-step-3-3")

    assert result.status == "generated"
    assert len(path_selection.calls) == 1
    assert path_selection.calls[0]["question"] == "查询金牌服务使用的隧道名称"
    assert set(path_selection.calls[0]) == {"ontology_mapping", "question", "lexer_trace"}
    assert path_selection.calls[0]["lexer_trace"] is not None
    mapped = path_selection.calls[0]["ontology_mapping"]
    assert isinstance(mapped, dict)
    assert mapped["ontology_objects"]
    assert mapped["ontology_relation_hints"]
    assert result.trace.to_dict()["ontology_path_selection"]["selected_paths"][0]["relation_chain"] == ["SERVICE_USES_TUNNEL"]


def test_runtime_pipeline_logical_plan_edges_come_from_step_3_3_selected_paths() -> None:
    path_selection = _RecordingPathSelectionService(_path_selection_trace(("SERVICE_USES_TUNNEL", "TUNNEL_SRC")))
    pipeline = OntologyGenerationPipeline(
        assets=OntologyAssets.from_default_resources(),
        intent_layer=_FixtureIntentClassifier(),  # type: ignore[arg-type]
        object_role_selection_service=OntologyObjectRoleSelectionService(llm_selector=_FixtureObjectRoleSelectionSelector()),
        path_selection_service=path_selection,  # type: ignore[arg-type]
        logical_planning_service=OntologyLogicalPlanningService(
            assets=OntologyAssets.from_default_resources(),
            coreference_service=OntologyCoreferenceService(llm_selector=_SameInstanceCoreferenceSelector()),
            binding_service=OntologyBindingService(llm_selector=_FixtureBindingSelector()),
        ),
    )

    result = pipeline.generate("查询金牌服务使用的隧道名称", trace_id="trace-path-source")

    assert [edge.relation for edge in result.logical_plan.edges] == ["SERVICE_USES_TUNNEL", "TUNNEL_SRC"]
    assert result.trace.ontology_path_selection.selected_paths[0].relation_chain == ("SERVICE_USES_TUNNEL", "TUNNEL_SRC")


def test_runtime_pipeline_calls_explicit_step_3_4_3_5_3_6_services() -> None:
    logical_planning = _RecordingExplicitLogicalPlanningService()
    pipeline = OntologyGenerationPipeline(
        assets=OntologyAssets.from_default_resources(),
        intent_layer=_FixtureIntentClassifier(),  # type: ignore[arg-type]
        object_role_selection_service=OntologyObjectRoleSelectionService(llm_selector=_FixtureObjectRoleSelectionSelector()),
        logical_planning_service=logical_planning,  # type: ignore[arg-type]
    )

    result = pipeline.generate("查询金牌服务使用的隧道名称", trace_id="trace-explicit-3-4")
    trace = result.trace.to_dict()

    assert result.status == "generated"
    assert logical_planning.calls == [
        "step_3_4_coreference",
        "step_3_5_binding",
        "step_3_6_shape_finalization",
    ]
    assert trace["coreference"]["stage"] == "step_3_4_coreference"
    assert trace["binding"]["stage"] == "step_3_5_binding"
    assert trace["shape_finalization"]["trace"]["stage"] == "step_3_6"


def test_runtime_pipeline_single_candidate_path_selection_does_not_call_llm() -> None:
    class NoPathSelectionLLM:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def select(self, prompt_name: str, variables: dict[str, object]):
            self.calls.append({"prompt_name": prompt_name, **variables})
            raise AssertionError("single-candidate path selection must not call the LLM")

    selector = NoPathSelectionLLM()
    pipeline = OntologyGenerationPipeline(
        assets=OntologyAssets.from_default_resources(),
        intent_layer=_FixtureIntentClassifier(),  # type: ignore[arg-type]
        object_role_selection_service=OntologyObjectRoleSelectionService(llm_selector=_FixtureObjectRoleSelectionSelector()),
        path_selection_service=OntologyPathSelectionService(
            assets=OntologyAssets.from_default_resources(),
            llm_selector=selector,
        ),
        logical_planning_service=OntologyLogicalPlanningService(
            assets=OntologyAssets.from_default_resources(),
            coreference_service=OntologyCoreferenceService(llm_selector=_SameInstanceCoreferenceSelector()),
            binding_service=OntologyBindingService(llm_selector=_FixtureBindingSelector()),
        ),
    )

    result = pipeline.generate(
        "查询金牌服务经过的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址",
        trace_id="trace-single-candidate-path",
    )

    assert result.trace.ontology_path_selection.selected_paths
    assert selector.calls == []


def test_runtime_pipeline_raises_clarification_for_step_3_3_path_selection() -> None:
    path_selection = _RecordingPathSelectionService(
        _path_selection_trace(
            clarification={
                "status": "unresolved",
                "reason_code": "ambiguous_path",
                "reason": "源网元存在多条候选路径",
                "options": ["隧道源网元", "经过网元"],
            }
        )
    )
    pipeline = OntologyGenerationPipeline(
        assets=OntologyAssets.from_default_resources(),
        intent_layer=_FixtureIntentClassifier(),  # type: ignore[arg-type]
        object_role_selection_service=OntologyObjectRoleSelectionService(llm_selector=_FixtureObjectRoleSelectionSelector()),
        path_selection_service=path_selection,  # type: ignore[arg-type]
        logical_planning_service=OntologyLogicalPlanningService(
            assets=OntologyAssets.from_default_resources(),
            coreference_service=OntologyCoreferenceService(llm_selector=_SameInstanceCoreferenceSelector()),
            binding_service=OntologyBindingService(llm_selector=_FixtureBindingSelector()),
        ),
    )

    with pytest.raises(ClarificationNeeded) as exc_info:
        pipeline.generate("查询金牌服务使用的隧道名称", trace_id="trace-step-3-3-clarify")

    assert exc_info.value.stage == "step_3_3"
    assert exc_info.value.clarification["source_step"] == "step_3_3_ontology_path_selection"
    assert exc_info.value.clarification["reason_code"] == "ambiguous_path"


def test_runtime_pipeline_preserves_coreference_source_step_after_shape_finalization() -> None:
    pipeline = OntologyGenerationPipeline(
        assets=OntologyAssets.from_default_resources(),
        intent_layer=_FixtureIntentClassifier(),  # type: ignore[arg-type]
        object_role_selection_service=OntologyObjectRoleSelectionService(llm_selector=_FixtureObjectRoleSelectionSelector()),
        logical_planning_service=OntologyLogicalPlanningService(
            assets=OntologyAssets.from_default_resources(),
            coreference_service=OntologyCoreferenceService(llm_selector=None),
            binding_service=OntologyBindingService(llm_selector=_FixtureBindingSelector()),
        ),
    )

    with pytest.raises(ClarificationNeeded) as exc_info:
        pipeline.generate(
            "查询金牌服务经过的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址",
            trace_id="trace-coreference-source-step",
        )

    assert exc_info.value.stage == "step_3_6"
    assert exc_info.value.clarification["source_step"] == "step_3_4_coreference"
    assert exc_info.value.clarification["precheck_result"]["failures"][0]["reason_code"] == "AMBIGUOUS_COREFERENCE"


def test_runtime_pipeline_routes_binding_clarification_to_unified_clarification() -> None:
    class ClarifyingBindingSelector:
        def select(self, prompt_name: str, variables: dict[str, object]):
            class Selection:
                raw_response = "需要澄清：名称可以属于服务或隧道。"

            return Selection()

    pipeline = OntologyGenerationPipeline(
        assets=OntologyAssets.from_default_resources(),
        intent_layer=_FixtureIntentClassifier(),  # type: ignore[arg-type]
        object_role_selection_service=OntologyObjectRoleSelectionService(llm_selector=_FixtureObjectRoleSelectionSelector()),
        logical_planning_service=OntologyLogicalPlanningService(
            assets=OntologyAssets.from_default_resources(),
            coreference_service=OntologyCoreferenceService(llm_selector=_SameInstanceCoreferenceSelector()),
            binding_service=OntologyBindingService(llm_selector=ClarifyingBindingSelector()),
        ),
    )

    with pytest.raises(ClarificationNeeded) as exc_info:
        pipeline.generate("查询金牌服务使用的隧道名称", trace_id="trace-binding-clarification")

    assert exc_info.value.stage == "step_3_6"
    assert exc_info.value.clarification["source_step"] == "step_3_5"
    failure = exc_info.value.clarification["precheck_result"]["failures"][0]
    assert failure["reason_code"] == "invalid_llm_binding"
    assert failure["message"] == "名称可以属于服务或隧道。"
