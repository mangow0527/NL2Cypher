from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.cypher_generator_agent.app.ontology_layer.coreference import (
    CoreferenceValidationError,
    OntologyCoreferenceService,
)


QUESTION = "查询金牌服务经过的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址"


def _ontology_mapping(extra_mappings: list[dict[str, object]] | None = None) -> dict[str, object]:
    mapped_mentions: list[dict[str, object]] = [
        {
            "mapping_id": "OM1",
            "mention_id": "m_service_1",
            "mention_type": "OBJECT",
            "surface": "服务",
            "span": [4, 6],
            "ontology_kind": "class",
            "ontology_id": "Service",
            "object_candidate_id": "SM1",
            "selected_roles": ["filter_subject", "path_subject"],
        },
        {
            "mapping_id": "OM2",
            "mention_id": "m_tunnel_1",
            "mention_type": "OBJECT",
            "surface": "隧道",
            "span": [9, 11],
            "ontology_kind": "class",
            "ontology_id": "Tunnel",
            "object_candidate_id": "SM2",
            "selected_roles": ["path_subject"],
        },
        {
            "mapping_id": "OM3",
            "mention_id": "m_source_ne_1",
            "mention_type": "RELATION",
            "surface": "源网元",
            "span": [13, 16],
            "ontology_kind": "relation_role",
            "ontology_id": "TUNNEL_SRC",
            "role": "source",
            "target_class": "NetworkElement",
            "object_candidate_id": "SM3",
            "selected_roles": ["path_subject"],
        },
        {
            "mapping_id": "OM4",
            "mention_id": "m_gold_1",
            "mention_type": "VALUE",
            "surface": "金牌",
            "span": [2, 4],
            "ontology_kind": "enum_value",
            "ontology_id": "ServiceQuality.Gold",
        },
        {
            "mapping_id": "OM5",
            "mention_id": "m_tunnel_2",
            "mention_type": "OBJECT",
            "surface": "隧道",
            "span": [19, 21],
            "ontology_kind": "class",
            "ontology_id": "Tunnel",
            "object_candidate_id": "SM4",
            "selected_roles": ["projection_subject"],
        },
        {
            "mapping_id": "OM6",
            "mention_id": "m_source_ne_2",
            "mention_type": "RELATION",
            "surface": "源网元",
            "span": [29, 32],
            "ontology_kind": "relation_role",
            "ontology_id": "TUNNEL_SRC",
            "role": "source",
            "target_class": "NetworkElement",
            "object_candidate_id": "SM5",
            "selected_roles": ["projection_subject"],
        },
    ]
    if extra_mappings:
        mapped_mentions.extend(extra_mappings)
    return {"mapped_mentions": mapped_mentions}


def _selected_paths() -> list[dict[str, object]]:
    return [
        {"request_id": "PR1", "path_id": "P1", "relation_chain": ["SERVICE_USES_TUNNEL"], "mapping_ids": ["OM1", "OM2"]},
        {"request_id": "PR2", "path_id": "P2", "relation_chain": ["TUNNEL_SRC"], "mapping_ids": ["OM2", "OM3", "OM5", "OM6"]},
    ]


def _shape_signals() -> list[dict[str, object]]:
    return [{"signal_id": "SS1", "signal_type": "PROJECTION_REGION_CUE", "text": "返回", "span": [17, 19]}]


def _context_signals() -> list[dict[str, object]]:
    return [
        {"signal_id": "CS1", "signal_type": "PROXIMAL_MODIFIER", "text": "隧道的IETF标准", "span": [19, 28], "supports": ["OM5"]},
        {"signal_id": "CS2", "signal_type": "PROXIMAL_MODIFIER", "text": "源网元的IP地址", "span": [29, 37], "supports": ["OM6"]},
    ]


class StaticCoreferenceSelector:
    def __init__(self, candidate_id: str) -> None:
        self.candidate_id = candidate_id

    def select(self, prompt_name: str, variables: dict[str, object]) -> SimpleNamespace:
        assert prompt_name == "coreference_selection"
        assert len(variables["allowed_signal_ids"]) >= 2
        return SimpleNamespace(raw_response=f"选择 {self.candidate_id}。理由：依据输入线索选择。")


def test_generates_candidate_pairs_and_merges_same_class_projection_mappings() -> None:
    result = OntologyCoreferenceService(llm_selector=StaticCoreferenceSelector("C1")).resolve(
        question=QUESTION,
        ontology_mapping=_ontology_mapping(),
        selected_paths=_selected_paths(),
        shape_signals=_shape_signals(),
        context_signals=_context_signals(),
        explicit_distinction_signals=[],
    )

    pairs = {(item["left_mapping_id"], item["right_mapping_id"]) for item in result["candidate_pairs"]}

    assert ("OM2", "OM5") in pairs
    assert ("OM3", "OM6") in pairs
    assert all("OM4" not in pair for pair in pairs)
    assert result["merged_nodes"] == [
        {"node_id": "n1", "class_id": "Tunnel", "mapping_ids": ["OM2", "OM5"]},
        {"node_id": "n2", "class_id": "NetworkElement", "mapping_ids": ["OM3", "OM6"]},
    ]
    tunnel = next(item for item in result["resolved_pairs"] if item["candidate_pair_id"] == "CR1")
    assert tunnel["decision"] == "same_instance"
    assert tunnel["selected_by"] == "llm"


def test_explicit_distinction_signal_splits_instances() -> None:
    result = OntologyCoreferenceService(llm_selector=StaticCoreferenceSelector("C2")).resolve(
        question="查询服务经过的隧道和另一条隧道",
        ontology_mapping=_ontology_mapping(),
        selected_paths=[],
        shape_signals=[],
        context_signals=[],
        explicit_distinction_signals=[{"signal_id": "DS1", "text": "另一", "span": [12, 14], "supports": ["OM2", "OM5"]}],
    )

    tunnel = next(
        item for item in result["resolved_pairs"] if {item["left_mapping_id"], item["right_mapping_id"]} == {"OM2", "OM5"}
    )
    assert tunnel["decision"] == "distinct_instances"
    assert "explicit_distinction" in tunnel["evidence"]


def test_role_relation_same_role_and_range_corefer() -> None:
    result = OntologyCoreferenceService(llm_selector=StaticCoreferenceSelector("C1")).resolve(
        question=QUESTION,
        ontology_mapping=_ontology_mapping(),
        selected_paths=_selected_paths(),
        shape_signals=_shape_signals(),
        context_signals=_context_signals(),
        explicit_distinction_signals=[],
    )

    role_pair = next(
        item for item in result["resolved_pairs"] if {item["left_mapping_id"], item["right_mapping_id"]} == {"OM3", "OM6"}
    )
    assert role_pair["decision"] == "same_instance"
    assert "same_role" in role_pair["evidence"]
    assert role_pair["merged_to"] == "n2"


def test_gray_zone_uses_llm_accept_when_two_valid_signals_are_present() -> None:
    class Selector:
        def select(self, prompt_name: str, variables: dict[str, object]) -> SimpleNamespace:
            assert prompt_name == "coreference_selection"
            assert variables["allowed_candidate_ids"] == ["C1", "C2"]
            return SimpleNamespace(raw_response="选择 C1。理由：投影区延续前文对象。")

    result = OntologyCoreferenceService(llm_selector=Selector()).resolve(
        question="查询隧道，返回隧道名称",
        ontology_mapping=_ontology_mapping(),
        selected_paths=[],
        shape_signals=[],
        context_signals=_context_signals(),
        explicit_distinction_signals=[],
    )

    tunnel = next(
        item for item in result["resolved_pairs"] if {item["left_mapping_id"], item["right_mapping_id"]} == {"OM2", "OM5"}
    )
    assert tunnel["decision"] == "same_instance"
    assert tunnel["selected_by"] == "llm"
    assert result["llm_decision_traces"][0]["llm_raw_output"].startswith("选择 C1")


@pytest.mark.parametrize(
    "raw,error_part",
    [
        ("选择 C9。理由：bad", "unrecognized coreference selection line"),
        ("随便输出", "unrecognized coreference selection line"),
    ],
)
def test_rejects_invalid_llm_selection_text(raw: str, error_part: str) -> None:
    class Selector:
        def select(self, prompt_name: str, variables: dict[str, object]) -> SimpleNamespace:
            return SimpleNamespace(raw_response=raw)

    service = OntologyCoreferenceService(llm_selector=Selector())

    with pytest.raises(CoreferenceValidationError, match=error_part):
        service.resolve(
            question="查询隧道，返回隧道名称",
            ontology_mapping=_ontology_mapping(),
            selected_paths=[],
            shape_signals=[],
            context_signals=_context_signals(),
            explicit_distinction_signals=[],
        )


def test_value_mappings_do_not_participate_in_coreference_pairs() -> None:
    result = OntologyCoreferenceService().resolve(
        question=QUESTION,
        ontology_mapping=_ontology_mapping(),
        selected_paths=_selected_paths(),
        shape_signals=_shape_signals(),
        context_signals=_context_signals(),
        explicit_distinction_signals=[],
    )

    assert all("OM4" not in (pair["left_mapping_id"], pair["right_mapping_id"]) for pair in result["candidate_pairs"])


def test_coreference_requires_object_candidate_id() -> None:
    mapping = {
        "mapped_mentions": [
            {
                "mapping_id": "OM_WITHOUT_ID_1",
                "mention_id": "m_without_id_1",
                "mention_type": "OBJECT",
                "surface": "服务",
                "span": [0, 2],
                "ontology_kind": "class",
                "ontology_id": "Service",
                "selected_roles": ["path_subject"],
            },
            {
                "mapping_id": "OM_WITHOUT_ID_2",
                "mention_id": "m_without_id_2",
                "mention_type": "OBJECT",
                "surface": "服务",
                "span": [5, 7],
                "ontology_kind": "class",
                "ontology_id": "Service",
                "selected_roles": ["projection_subject"],
            },
        ]
    }

    result = OntologyCoreferenceService().resolve(
        question=QUESTION,
        ontology_mapping=mapping,
        selected_paths=[],
        shape_signals=[],
        context_signals=[],
        explicit_distinction_signals=[],
    )

    assert result["candidate_pairs"] == []
