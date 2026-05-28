from __future__ import annotations

from typing import Any

from .models import QUESTION_DECOMPOSITION_SCHEMA_VERSION, question_decomposition_json_schema


def build_question_decomposition_prompt(question: str) -> str:
    return "\n".join(
        [
            "你是图原生 Cypher 生成流水线中的问题结构化拆解器。",
            f"只返回符合 {QUESTION_DECOMPOSITION_SCHEMA_VERSION} schema 的结构化结果。",
            "必须从 schema 允许的枚举值中填写 intent_type 和 output_shape。",
            "只使用用户问题中的表层语言词语。不要输出图 label、边名、属性名、指标名、path pattern id 或 Cypher。",
            "literal_candidates 必须保持图无关，只填写必需的 text、kind_hint 和 attached_to。",
            "把每个有意义的表层词语准确放入且只放入一个分类桶：",
            "- substantive_terms：领域概念、指标、实体、关系、状态和动作。",
            "- stopword_terms：礼貌表达、连接词或不会驱动召回的填充词。",
            "- modality_terms：近似、不确定性或软约束表达。",
            "- time_terms：时间或时间范围表达。",
            "- unparsed_terms：你无法可靠分类、但可能影响语义的文本。",
            "保留用户问题中的分类词和附着词作为表层词语；下游工程代码会负责规范化。",
            "如果问题中的代词或指示词缺少明确指代对象，返回 result_type=clarification_required，并给出简洁的 clarification_question。",
            "不要生成 Cypher，不要解释过程，不要返回 Markdown。",
            f"用户问题：{question}",
        ]
    )


def build_question_decomposition_schema() -> dict[str, Any]:
    return question_decomposition_json_schema()
