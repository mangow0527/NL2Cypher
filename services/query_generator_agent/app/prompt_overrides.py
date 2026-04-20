from __future__ import annotations

import json
from typing import Any


def uses_intent_guided_flow(id: str) -> bool:
    return id.startswith("semantic_intent_guided_eval_")


def should_bypass_knowledge_ops_prompt(id: str) -> bool:
    return (
        id.startswith("manual_prompt_eval_")
        or id.startswith("semantic_two_stage_eval_")
        or uses_intent_guided_flow(id)
    )


def build_manual_prompt_override(id: str, question: str) -> str | None:
    if not (id.startswith("manual_prompt_eval_") or id.startswith("semantic_two_stage_eval_")):
        return None

    return _strict_manual_eval_prompt(question)


def uses_semantic_two_stage_flow(id: str) -> bool:
    return id.startswith("semantic_two_stage_eval_")


def build_semantic_parsing_prompt(question: str) -> str:
    return f"""task: semantic_parsing

instruction: |
  将自然语言查询解析为结构化图查询语义，不要直接生成 Cypher。
  只能使用给定 Schema 与术语映射中的概念。
  不得虚构实体、关系、属性、过滤条件或聚合语义。
  如果问题要求“信息”或“详情”但未明确字段，attributes 允许为空，并在 return_shape 中表达返回对象级信息的意图。
  结果必须输出为单个 JSON 对象，不要附加解释或 Markdown。

output_format:
  entities: 查询涉及的实体标签列表
  relations: 查询涉及的关系类型列表
  attributes: 问题明确要求返回的属性列表；若未明确字段可为空
  conditions: 过滤条件列表，每项包含 field、operator、value
  limit: 返回数量；没有则为 null
  direction: directed / undirected / none
  aggregation: none 或结构化聚合描述
  ordering: none 或结构化排序描述
  return_shape: scalar_fields / entity_object / key_plus_entity / aggregation_rows

schema:
{_indented_block(_schema_block(), "  ")}

business_mappings:
{_indented_block(_business_mappings_block(), "  ")}

examples:
  - input: 查询3个设备
    output:
      entities: ["NetworkElement"]
      relations: []
      attributes: []
      conditions: []
      limit: 3
      direction: "none"
      aggregation: "none"
      ordering: "none"
      return_shape: "entity_object"
  - input: 按类型统计隧道的数量
    output:
      entities: ["Tunnel"]
      relations: []
      attributes: ["type"]
      conditions: []
      limit: null
      direction: "none"
      aggregation:
        type: "count_by"
        field: "type"
      ordering: "none"
      return_shape: "aggregation_rows"
  - input: 查询5条链路及其目的端口信息
    output:
      entities: ["Link", "Port"]
      relations: ["LINK_DST"]
      attributes: []
      conditions: []
      limit: 5
      direction: "directed"
      aggregation: "none"
      ordering: "none"
      return_shape: "key_plus_entity"

query: {question}
"""


def build_intent_understanding_prompt(question: str) -> str:
    return f"""task: intent_understanding

instruction: |
  将自然语言查询解析为结构化意图，不要直接生成 Cypher。
  你的目标是识别这条查询属于什么题型、主实体是谁、涉及哪些关系路径、有哪些过滤条件、是否需要聚合、以及最终结果应该如何返回。
  只能使用给定 Schema 与术语映射中的概念。
  不得虚构实体、关系、属性、过滤条件或聚合语义。
  输出必须是单个 JSON 对象，不要附加解释或 Markdown。

required_semantics:
  - query_type: entity_info / relation_association / path_query / filtering / aggregation / ordering_topk / attribute_projection / mixed_compound
  - primary_entity: 主查询对象
  - related_entities: 与主实体直接相关的实体列表
  - relation_paths: 关系或路径列表
  - filters: 过滤条件列表，每项包含 field、operator、value
  - aggregation: none 或结构化聚合描述
  - ordering_limit: none 或结构化排序与数量描述
  - return_shape: scalar_fields / entity_object / key_plus_entity / aggregation_rows

schema:
{_indented_block(_schema_block(), "  ")}

business_mappings:
{_indented_block(_business_mappings_block(), "  ")}

examples:
  - input: 查询5条链路及其目的端口信息
    output:
      query_type: relation_association
      primary_entity: Link
      related_entities: [Port]
      relation_paths: [LINK_DST]
      filters: []
      aggregation: none
      ordering_limit:
        limit: 5
      return_shape: key_plus_entity
  - input: 按类型统计隧道的数量
    output:
      query_type: aggregation
      primary_entity: Tunnel
      related_entities: []
      relation_paths: []
      filters: []
      aggregation:
        type: count_by
        field: type
      ordering_limit: none
      return_shape: aggregation_rows
  - input: 查询10条带宽大于等于1的隧道信息
    output:
      query_type: entity_info
      primary_entity: Tunnel
      related_entities: []
      relation_paths: []
      filters:
        - field: bandwidth
          operator: ">="
          value: 1
      aggregation: none
      ordering_limit:
        limit: 10
      return_shape: entity_object

query: {question}
"""


def build_two_stage_generation_prompt(
    *,
    base_generation_prompt: str,
    semantic_parse: dict[str, Any],
    semantic_parse_raw_output: str,
) -> str:
    structured = json.dumps(semantic_parse, ensure_ascii=False, indent=2)
    return f"""【两阶段实验说明】
- 本次先完成了语义拆解，请在生成 Cypher 时优先服从下述结构化语义表示。
- 不要补充结构化语义表示中不存在的实体、关系、条件或聚合语义。

【结构化语义表示】
{structured}

【语义拆解模型原始输出】
{semantic_parse_raw_output.strip()}

【原始生成提示词】
{base_generation_prompt}
"""


def build_intent_guided_generation_prompt(
    *,
    question: str,
    intent: dict[str, Any],
) -> str:
    query_type = str(intent.get("query_type", "mixed_compound"))
    primary_entity = str(intent.get("primary_entity", ""))
    related_entities = intent.get("related_entities") or []
    relation_paths = intent.get("relation_paths") or []
    filters = intent.get("filters") or []
    aggregation = intent.get("aggregation", "none")
    ordering_limit = intent.get("ordering_limit", "none")
    return_shape = str(intent.get("return_shape", "scalar_fields"))

    selected_knowledge = _select_knowledge_blocks(
        query_type=query_type,
        primary_entity=primary_entity,
        related_entities=related_entities,
        relation_paths=relation_paths,
        filters=filters,
        aggregation=aggregation,
        return_shape=return_shape,
    )
    structured = json.dumps(intent, ensure_ascii=False, indent=2)
    return f"""## Core Rules
[id: role_system]
- 你是严格的 TuGraph Text2Cypher 生成器。
[id: schema_only_system]
- 只能使用 Schema 中存在的节点、关系、属性。
[id: no_hallucination_system]
- 不得虚构标签、关系、属性、业务含义或过滤条件。
[id: direction_system]
- 所有关系方向必须与 Schema 定义一致。
[id: single_query_system]
- 只输出单条 Cypher，不要解释，不要 Markdown。
[id: return_shape_system]
- 必须优先服从结构化意图中的 return_shape，不要自行扩展或压缩返回结构。

【结构化意图】
{structured}

【题型判断】
- query_type: {query_type}
- primary_entity: {primary_entity}
- related_entities: {json.dumps(related_entities, ensure_ascii=False)}
- relation_paths: {json.dumps(relation_paths, ensure_ascii=False)}
- filters: {json.dumps(filters, ensure_ascii=False)}
- aggregation: {json.dumps(aggregation, ensure_ascii=False)}
- ordering_limit: {json.dumps(ordering_limit, ensure_ascii=False)}
- return_shape: {return_shape}

【Schema】
{_schema_block()}

【术语映射】
{_business_mappings_block()}

【按题型选择的知识】
{selected_knowledge["knowledge"]}

【按题型选择的正例示例】
{selected_knowledge["positive_few_shots"]}

【按题型选择的错误示例】
{selected_knowledge["negative_few_shots"]}

【生成要求】
- 输出必须是单条 Cypher
- 不要输出解释
- 不要输出 Markdown
- 只使用上面结构化意图和 Schema 中允许的元素
- 如果 query_type 是 aggregation，严格返回聚合行，不返回节点对象
- 如果 return_shape 是 entity_object，优先返回实体对象本身
- 如果 return_shape 是 key_plus_entity，优先返回主实体标识加关联实体对象
- 如果 return_shape 是 scalar_fields，只返回题目明确需要的字段

【用户问题】
{question}
"""


def _indented_block(text: str, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" if line else line for line in text.splitlines())


def _schema_block() -> str:
    return """Labels:
- NetworkElement(id, ip_address, location, model, name, software_version, type, vendor)
- Protocol(id, ietf_category, name, standard, version)
- Tunnel(bandwidth, latency, id, ietf_standard, name, type)
- Service(bandwidth, latency, id, name, quality_of_service, type)
- Port(speed, id, mac_address, name, status, type, vlan_id)
- Fiber(bandwidth_capacity, length, id, location, name, type, wavelength)
- Link(bandwidth, latency, mtu, admin_status, id, name, protocol, status, type, vlan_id)

Relationships:
- (:NetworkElement)-[:HAS_PORT]->(:Port)
- (:Fiber)-[:FIBER_SRC]->(:Port)
- (:Fiber)-[:FIBER_DST]->(:Port)
- (:Link)-[:LINK_SRC]->(:Port)
- (:Link)-[:LINK_DST]->(:Port)
- (:Tunnel)-[:TUNNEL_SRC]->(:NetworkElement)
- (:Tunnel)-[:TUNNEL_DST]->(:NetworkElement)
- (:Tunnel)-[:TUNNEL_PROTO]->(:Protocol)
- (:Tunnel)-[:PATH_THROUGH]->(:NetworkElement)
- (:Service)-[:SERVICE_USES_TUNNEL]->(:Tunnel)"""


def _business_mappings_block() -> str:
    return """- “网络设备”、“网元”、“设备” -> `NetworkElement`
- “端口”、“接口” -> `Port`
- “链路” -> `Link`
- “光纤” -> `Fiber`
- “隧道” -> `Tunnel`
- “协议” -> `Protocol`
- “业务”、“服务” -> `Service`
- “ID”、“编号” -> `id`
- “名称” -> `name`
- “类型” -> `type`
- “状态” -> `status`；链路管理状态优先使用 `Link.admin_status`
- “链路源端口”、“链路起点端口” 表示模式 `(l:Link)-[:LINK_SRC]->(p:Port)`。
- “链路目的端口”、“链路终点端口” 表示模式 `(l:Link)-[:LINK_DST]->(p:Port)`。
- “光纤源端口” 表示模式 `(f:Fiber)-[:FIBER_SRC]->(p:Port)`。
- “光纤目的端口” 表示模式 `(f:Fiber)-[:FIBER_DST]->(p:Port)`。
- “设备有哪些端口” 表示模式 `(n:NetworkElement)-[:HAS_PORT]->(p:Port)`。
- “隧道协议” 表示模式 `(t:Tunnel)-[:TUNNEL_PROTO]->(proto:Protocol)`。
- “隧道路径经过哪些设备” 表示模式 `(t:Tunnel)-[pt:PATH_THROUGH]->(n:NetworkElement)`，需要按 `pt.hop_order` 排序。
- “业务使用哪些隧道” 表示模式 `(s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)`。
- 分组统计字段别名通常使用 `group_key`，统计值别名通常使用 `total`
- 当结果需要通用主键别名 `key` 时，`key` 对应主实体的 `id`"""


def _select_knowledge_blocks(
    *,
    query_type: str,
    primary_entity: str,
    related_entities: list[Any],
    relation_paths: list[Any],
    filters: list[Any],
    aggregation: Any,
    return_shape: str,
) -> dict[str, str]:
    positive_shots: list[str] = []
    negative_shots: list[str] = []
    knowledge: list[str] = []

    if query_type == "relation_association":
        knowledge.extend(
            [
                "- 关系关联查询重点检查：主实体、关联实体、关系方向、返回结构。",
                "- 当问题是“X及其Y信息”时，优先区分主实体与关联实体，不要把两边都完整返回。",
            ]
        )
        positive_shots.append(
            """[id: link_dst_port_info_few_shot]
Question: 查询5条链路及其目的端口信息
Cypher: MATCH (l:Link)-[:LINK_DST]->(p:Port) RETURN l.id AS key, p LIMIT 5
Why: 主实体是 `Link`，关联实体是 `Port`；“目的端口信息”更适合返回 `key + 关联对象`。"""
        )
        negative_shots.append(
            """Anti-Pattern: MATCH (l:Link)-[:LINK_DST]->(p:Port) RETURN l, p LIMIT 5
Why Not: 主实体对象 `l` 不是问题真正关注的返回主体，返回结构过宽。"""
        )
    if query_type == "aggregation":
        knowledge.extend(
            [
                "- 聚合统计查询必须显式返回聚合行，不返回节点对象。",
                "- Cypher 聚合通过 WITH / RETURN 隐式分组，禁止使用 GROUP BY。",
            ]
        )
        positive_shots.append(
            """[id: tunnel_type_count_few_shot]
Question: 按类型统计隧道的数量
Cypher: MATCH (t:Tunnel) RETURN t.type AS group_key, count(t) AS total
Why: “按类型统计数量”属于分组聚合，返回聚合行。"""
        )
        negative_shots.append(
            """Anti-Pattern: MATCH (t:Tunnel) RETURN t
Why Not: 这是对象返回，不是统计结果。"""
        )
    if query_type == "entity_info":
        knowledge.extend(
            [
                "- 实体信息查询重点检查：主实体、过滤条件、返回对象还是字段。",
                "- 当问题要求“信息”且未明确字段时，优先考虑返回实体对象本身。",
            ]
        )
        positive_shots.append(
            """[id: tunnel_info_filtered_few_shot]
Question: 查询10条带宽大于等于1的隧道信息
Cypher: MATCH (t:Tunnel) WHERE t.bandwidth >= 1 RETURN t LIMIT 10
Why: 用户要求“隧道信息”而未明确字段，应返回 `Tunnel` 节点对象本身。"""
        )
        negative_shots.append(
            """Anti-Pattern: MATCH (t:Tunnel) WHERE t.bandwidth >= 1 RETURN t.id AS id, t.name AS name LIMIT 10
Why Not: 问题要求“隧道信息”且未指定字段时，过早压缩成字段投影会削弱对象语义。"""
        )

    if "LINK_DST" in [str(p) for p in relation_paths]:
        knowledge.append("- `LINK_DST` 表示从链路到目的端口的有向关系，不能误用 `LINK_SRC`。")
    if filters:
        knowledge.append("- 过滤条件必须使用 `WHERE`，且字段必须存在于主实体或正确的关联实体上。")
    if aggregation != "none":
        knowledge.append("- 聚合题的返回结构必须是 `aggregation_rows`，通常使用 `group_key` / `total`。")
    if return_shape == "entity_object":
        knowledge.append("- 当前意图要求对象级返回，不要将对象压缩为少量字段。")
    if return_shape == "key_plus_entity":
        knowledge.append("- 当前意图要求主实体标识加关联对象，优先返回 `key + entity`。")

    return {
        "knowledge": "\n".join(knowledge) if knowledge else "- 无额外题型知识。",
        "positive_few_shots": "\n\n".join(positive_shots) if positive_shots else "- 暂无按题型匹配的正例。",
        "negative_few_shots": "\n\n".join(negative_shots) if negative_shots else "- 暂无按题型匹配的反例。",
    }


def _strict_manual_eval_prompt(question: str) -> str:
    return f"""## Core Rules
[id: role_system]
- 你是严格的 TuGraph Text2Cypher 生成器。
[id: schema_only_system]
- 只能使用 Schema 中存在的节点、关系、属性。
[id: no_hallucination_system]
- 不得虚构标签、关系、属性、业务含义或过滤条件。
[id: direction_system]
- 所有关系方向必须与 Schema 定义一致。
[id: projection_system]
- 默认返回满足问题语义的最小结果结构；若问题要求对象信息且未明确字段，可直接返回实体对象。
[id: detail_system]
- 当用户要求详细信息时，若明确字段则返回关键属性字段；若问题未明确字段，则可以直接返回实体对象，但不要使用 RETURN *。
[id: aggregation_system]
- 聚合只能通过 WITH / RETURN 的隐式分组实现，绝不能使用 GROUP BY。
[id: null_group_system]
- 分组统计默认保留 null 分组，除非用户明确要求过滤空值。
[id: single_query_system]
- 只输出单条 Cypher，不要解释，不要 Markdown。

【Schema】
{_schema_block()}

【术语映射】
{_business_mappings_block()}

【关键路径与过滤约束】
- `MATCH` 中的节点必须使用正确标签，关系必须使用正确类型。
- 关系必须写出正确方向，不要把有向边当作无向边处理。
- `RETURN` 只返回题目需要的属性字段，并使用显式别名。
- 禁止使用 `RETURN *`。
- 禁止使用 `GROUP BY`。
- 聚合写法使用 `WITH` / `RETURN`，例如 `RETURN n.type AS group_key, count(n) AS total`。
- 属性过滤使用 `WHERE`，不要虚构不存在的过滤字段。
- 查询隧道路径时，如需体现路径顺序，必须使用 `pt.hop_order` 排序。
- 不要使用 Schema 中不存在的标签、关系、属性或函数约定。

【正例示例】
[id: service_tunnel_few_shot]
Question: 查询业务使用的隧道名称
Cypher: MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN s.name AS service_name, t.name AS tunnel_name
Why: 业务与隧道的关系应使用 `SERVICE_USES_TUNNEL`。
Anti-Pattern: MATCH (s:Service)-[:LINK_TO]->(t:Tunnel) RETURN s.name, t.name
Why Not: `LINK_TO` 不在当前 Schema 中。

[id: tunnel_path_few_shot]
Question: 查询指定隧道经过的设备顺序
Cypher: MATCH (t:Tunnel {{id: 'tun-mpls-1'}})-[pt:PATH_THROUGH]->(n:NetworkElement) RETURN t.id AS tunnel_id, pt.hop_order AS hop_order, n.name AS network_element_name ORDER BY pt.hop_order ASC
Why: `PATH_THROUGH` 是隧道经过设备的唯一主路径，并且必须按 `hop_order` 排序。
Anti-Pattern: MATCH (t:Tunnel)-[:TUNNEL_SRC|TUNNEL_DST]->(n:NetworkElement) RETURN n.name
Why Not: `TUNNEL_SRC` 和 `TUNNEL_DST` 只是端点，不代表完整路径。

【反例提醒】
- 错误示例：MATCH (s:Service)-[:LINK_TO]->(t:Tunnel) RETURN s.name, t.name
- 原因：`LINK_TO` 不在当前 Schema 中。
- 错误示例：MATCH (t:Tunnel)-[:TUNNEL_SRC|TUNNEL_DST]->(n:NetworkElement) RETURN n.name
- 原因：`TUNNEL_SRC` 和 `TUNNEL_DST` 只是端点，不代表完整路径。

【生成要求】
- 输出必须是单条 Cypher
- 不要输出解释
- 不要输出 Markdown
- 确保方向、属性、过滤条件、聚合语义正确
- 生成前先校对术语映射、路径方向、过滤条件、返回对象
- 如果正例与当前问题高度一致，优先复用其路径骨架，再根据过滤条件做最小改写
- 严格避开反例提醒中的错误返回对象、错误路径或过宽查询

【用户问题】
{question}
"""
