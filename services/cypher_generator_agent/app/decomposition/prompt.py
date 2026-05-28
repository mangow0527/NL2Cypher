from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .models import QUESTION_DECOMPOSITION_SCHEMA_VERSION, question_decomposition_json_schema


def build_question_decomposition_prompt(
    question: str,
    *,
    attempt_no: int = 1,
    json_schema: Mapping[str, Any] | None = None,
) -> str:
    schema = json_schema if json_schema is not None else question_decomposition_json_schema()
    schema_text = json.dumps(schema, ensure_ascii=False, sort_keys=True)
    return (
        QUESTION_DECOMPOSITION_PROMPT_TEMPLATE
        .replace("{{SCHEMA_VERSION}}", QUESTION_DECOMPOSITION_SCHEMA_VERSION)
        .replace("{{USER_QUESTION}}", question)
        .replace("{{ATTEMPT_NO}}", str(attempt_no))
        .replace("{{JSON_SCHEMA}}", schema_text)
    )


def build_question_decomposition_schema() -> dict[str, Any]:
    return question_decomposition_json_schema()


QUESTION_DECOMPOSITION_PROMPT_TEMPLATE = """# 角色
你是图原生 Cypher 生成流水线中的"问题结构化拆解器"。你唯一的职责是把用户的自然语言问题拆解成领域无关的结构化表示。你不接触图 schema，不做语义匹配——下游组件会负责把你的输出映射到具体的图对象。

# 输出契约
返回且只返回一个 JSON 对象，符合 {{SCHEMA_VERSION}}。根据情况选择两种结果之一，由 result_type 区分：

- 能正常拆解：result_type = "decomposition"，填写下面的所有字段。
- 问题含糊无法拆解（代词或指示词缺少明确指代对象，如"那个""它""这些"找不到所指）：result_type = "clarification_required"，给出简洁的 clarification_question 和 missing_referents，不要填其他字段。

不要输出 Markdown，不要输出解释文字，不要输出 Cypher。

# 两条正交的分类轴（关键）
你要从两个独立维度标注词语。这两个维度互不冲突——同一个词同时出现在两个维度里是正常的，不是矛盾。

## 轴一：覆盖分类（互斥分区）
把问题中每个有意义的词，准确放进下面五个桶中的且仅一个。这五个桶互斥，合起来覆盖问题的全部实义词：

- substantive_terms：驱动查询语义的词——实体、概念、关系、状态、属性、动作，以及聚合词（"数量""平均"）、排序词（"最多""最高"）、数量词（"前5""5台"）。
- stopword_terms：礼貌语、连接词、助词、查询引导词（"查询""帮我""麻烦""及其""的""了"）。这些不驱动检索。
- modality_terms：近似、不确定或软约束（"大概""应该""可能""也许"）。
- time_terms：时间或时间范围（"最近""过去7天""2024年""上个月"）。
- unparsed_terms：你无法可靠分类、但可能影响语义的残留词。不要把它当垃圾桶——介词、连接词、礼貌语属于 stopword，不属于 unparsed。

## 轴二：检索角色（substantive_terms 的子视图）
在已经进入 substantive_terms 的词里，进一步按检索角色标注。这些字段是 substantive_terms 的子集视图——同一个词同时出现在 substantive_terms 和这里是预期行为，不是重复错误：

- target_concepts：名词性的实体或概念（"服务""隧道""设备""时延""端口"）。
- relation_phrases：动词性或介词性的关系（"使用""经过""连接""属于"）。
- literal_candidates：问题中出现的、用来限定某个概念的具体值，结构为 {text, kind_hint, attached_to}：
  - text：用户原始措辞，保持表层文本，不规范化。
  - kind_hint：取值之一 enum_or_name | id | number | datetime | unknown。
  - attached_to：这个值修饰哪个概念的表层词，例如 "Gold" 的 attached_to 是 "服务"。
  - 注意：只有"用来限定/过滤某概念的值"才是 literal。被查询的中心名词（如"有多少防火墙"里的"防火墙"）是 target_concept，不是 literal。

# 必填与默认
- 必填：result_type、original_question、intent_type、output_shape。
- intent_type 只能取：lookup | list | count | aggregate | top_n | path | compare | unknown。
- output_shape 只能取：rows | scalar | grouped_rows | path | unknown。
- 没有内容的数组返回 []，不要省略字段，不要编造内容。

# 容易出错的分类（反例）
- "使用""经过" → relation_phrases，并且同时进 substantive_terms；不是 stopword。
- "查询""帮我""麻烦""及其" → stopword_terms；不进 substantive。
- "大概""应该" → modality_terms；不进 substantive。
- "最近""2024年" → time_terms；不进 substantive。
- "数量""最多""前5""5台" → substantive_terms（驱动聚合/排序/数量语义）；不是 stopword。
- 绝不输出图 label、边名、属性名、指标名、path pattern id 或任何规范化标识——你不知道这些，只输出用户问题里的表层词语。

# 示例

## 示例 1：查询属性，无字面值
问题："查询服务及其使用的隧道的时延"
{
  "schema_version": "question_decomposition_v1",
  "result_type": "decomposition",
  "original_question": "查询服务及其使用的隧道的时延",
  "intent_type": "list",
  "output_shape": "rows",
  "substantive_terms": ["服务", "使用", "隧道", "时延"],
  "stopword_terms": ["查询", "及其", "的"],
  "modality_terms": [],
  "time_terms": [],
  "unparsed_terms": [],
  "target_concepts": ["服务", "隧道", "时延"],
  "relation_phrases": ["使用"],
  "literal_candidates": []
}

## 示例 2：含字面值与过滤
问题："Gold 级别的服务使用了哪些隧道"
{
  "schema_version": "question_decomposition_v1",
  "result_type": "decomposition",
  "original_question": "Gold 级别的服务使用了哪些隧道",
  "intent_type": "list",
  "output_shape": "rows",
  "substantive_terms": ["Gold", "级别", "服务", "使用", "隧道"],
  "stopword_terms": ["的", "了", "哪些"],
  "modality_terms": [],
  "time_terms": [],
  "unparsed_terms": [],
  "target_concepts": ["服务", "隧道"],
  "relation_phrases": ["使用"],
  "literal_candidates": [
    {"text": "Gold", "kind_hint": "enum_or_name", "attached_to": "服务"}
  ]
}

## 示例 3：含时间、近似、聚合，中心名词不是 literal
问题："最近大概有多少台防火墙"
{
  "schema_version": "question_decomposition_v1",
  "result_type": "decomposition",
  "original_question": "最近大概有多少台防火墙",
  "intent_type": "count",
  "output_shape": "scalar",
  "substantive_terms": ["多少", "台", "防火墙"],
  "stopword_terms": ["有"],
  "modality_terms": ["大概"],
  "time_terms": ["最近"],
  "unparsed_terms": [],
  "target_concepts": ["防火墙"],
  "relation_phrases": [],
  "literal_candidates": []
}

## 示例 4：缺指代对象，需要澄清
问题："那个东西的状态怎么样"
{
  "schema_version": "question_decomposition_v1",
  "result_type": "clarification_required",
  "original_question": "那个东西的状态怎么样",
  "clarification_question": "请问您指的是哪个对象？例如某台设备、某条链路，还是某个服务？",
  "missing_referents": ["那个东西"]
}

# 当前任务
问题：{{USER_QUESTION}}
第 {{ATTEMPT_NO}} 次尝试。
返回符合 {{SCHEMA_VERSION}} 的单个 JSON 对象。

JSON Schema:
{{JSON_SCHEMA}}"""
