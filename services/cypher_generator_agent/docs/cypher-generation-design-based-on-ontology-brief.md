# Cypher 生成设计简版

本文是 `cypher-generation-design-based-on-ontology.md` 的简洁版，只说明整体流程、每一步做什么，以及核心输入输出。示例 JSON 展示步骤之间传递的关键字段；完整 trace、资源版本、提示词和工程接口细节放在详细版文档中。

## 整体流程

```text
上游预处理产出 core_question
  -> Step 0 问题框定 Question Framing（可选 hint）
  -> Step 1 词法层 Lexer
  -> Step 2 意图与答案形态识别 Intent / Shape
  -> Step 3 本体逻辑规划 Ontology Planner
  -> Step 4 语义校验 Semantic Validator
  -> Step 5 物理编译 Physical Compiler
  -> 执行 Cypher / 返回结果
```

核心思想是把“自然语言到 Cypher”拆成一个可降级的前置 hint 层和五个主步骤：

1. 可选地先把问题拆成原子片段，给词法层提供 hint。
2. 再把问题切成可处理的 mention 和线索。
3. 再判断用户想要的答案形态。
4. 再把 mention 和 intent 规划成本体级 logical plan。
5. 再检查 logical plan 是否符合业务语义。
6. 最后把本体级计划编译成具体 Cypher。

下文用同一个问题串起每一步的输入输出：`查询金牌服务穿越的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址`。

## Step 0：问题框定 Question Framing

Step 0 是词法层之前的可选辅助层，负责让 LLM 做普通问题拆分，把 `core_question` 拆成若干原子问题片段。LLM 只知道这些片段后续会辅助图数据库 / Cypher 查询，不知道系统内部的 mention、本体、canonical、logical plan 等术语。当前运行时会把 Step 0 的 `prompt`、`raw_response`、解析后的 `atoms` 和派生的 `retrieval_plan` 一起写入 trace，便于运行中心回放和问题归因；完整提示词放在详细版文档中。

提示词要求 LLM 输出简单文本，不输出 JSON。典型输出类似：

```text
找什么对象：金牌服务
通过什么关系继续找：穿越的隧道
通过什么关系继续找：隧道的源网元
最后返回什么：隧道的IETF标准
最后返回什么：源网元的IP地址
```

代码层会把 LLM 文本解析并包装成内部 `question_framing.atoms`，再交给 Lexer 作为 hint：

```json
{
  "question_framing": {
    "enabled": true,
    "raw_response": "原子问题：\n1. 金牌服务 ｜ 找什么对象 + 用什么条件筛选\n2. 穿越的隧道 ｜ 通过什么关系继续找\n3. 隧道的源网元 ｜ 通过什么关系继续找\n4. 隧道的IETF标准 ｜ 最后返回什么\n5. 源网元的IP地址 ｜ 最后返回什么",
    "atoms": [
      {"atom_id": "QA1", "text": "金牌服务", "roles": ["FIND_OBJECT", "FILTER_CONDITION"], "span": [2, 6], "confidence": 0.86, "raw_role_text": "找什么对象 + 用什么条件筛选"},
      {"atom_id": "QA2", "text": "穿越的隧道", "roles": ["RELATION_PATH"], "span": [6, 11], "confidence": 0.82, "raw_role_text": "通过什么关系继续找"},
      {"atom_id": "QA3", "text": "隧道的源网元", "roles": ["RELATION_PATH"], "span": [9, 16], "confidence": 0.8, "raw_role_text": "通过什么关系继续找"},
      {"atom_id": "QA4", "text": "隧道的IETF标准", "roles": ["RETURN_CONTENT"], "span": [19, 28], "confidence": 0.9, "raw_role_text": "最后返回什么"},
      {"atom_id": "QA5", "text": "源网元的IP地址", "roles": ["RETURN_CONTENT"], "span": [29, 37], "confidence": 0.9, "raw_role_text": "最后返回什么"}
    ],
    "retrieval_plan": {
      "version": "question_framing_retrieval_plan_v1",
      "path_queries": [
        {"query_id": "PQ1", "atom_ids": ["QA1", "QA2"], "source_text": "金牌服务", "path_text": "穿越的隧道", "retrieval_text": "金牌服务 穿越的隧道"},
        {"query_id": "PQ2", "atom_ids": ["QA1", "QA3"], "source_text": "金牌服务", "path_text": "隧道的源网元", "retrieval_text": "金牌服务 隧道的源网元"}
      ],
      "return_targets": [
        {"atom_id": "QA4", "text": "隧道的IETF标准"},
        {"atom_id": "QA5", "text": "源网元的IP地址"}
      ],
      "attribute_queries": [
        {"atom_id": "QA4", "text": "隧道的IETF标准"},
        {"atom_id": "QA5", "text": "源网元的IP地址"}
      ]
    },
    "diagnostics": []
  }
}
```

atom 的 `roles` 使用内部规范化枚举：`FIND_OBJECT`、`FILTER_CONDITION`、`RELATION_PATH`、`RETURN_CONTENT`、`AGG_SORT_TIME`、`UNKNOWN`。LLM 的中文角色只保留在 `raw_role_text` 里用于 trace；`span`、`confidence` 和 `diagnostics` 由代码补充，LLM 不直接输出内部结构。

Step 0 只影响词法层 hint：可以指导残片向量召回的 `expected_mention_type`，帮助区分 projection / filter 角色，或限制未命中片段的召回范围。`retrieval_plan.path_queries` 会给 Step 1 的路径近义词召回提供更干净的短查询文本，`return_targets` / `attribute_queries` 会帮助识别返回字段区域。它不能覆盖词典和向量事实，不能生成本体 canonical，不能生成 logical plan 或 Cypher。

如果 LLM 失败、输出无法解析、角色不合法或 span 找不到，系统直接降级为无 framing 模式。降级不阻塞主流程，也不产生澄清请求。

## Step 1：词法层 Lexer

Step 1 负责把标准化后的 `core_question` 转成 mention 序列和词法线索。若 Step 0 产出了可用 `question_framing.atoms`，Lexer 可以把它们作为 hint；若 Step 0 降级或关闭，Lexer 按原流程运行。

它主要做：

- 用词典扫描业务对象、关系、属性、属性值和操作词。
- 抽取字面值、运算符、量词、时间表达等结构化元素；这是与 AC 词典扫描、向量召回并列的独立通道。
- 识别没有被词典覆盖的残片，并对残片做向量召回；Step 0 hint 只可辅助判断 `expected_mention_type` 和召回范围。
- 处理重叠命中，例如“源网元”覆盖“源”和“网元”。
- 保留候选族，例如“名称”可能对应服务名称、隧道名称、网元名称。
- 抽取上下文线索和答案形态线索，例如“返回”后面的字段区域。

Step 1 输出 9 类 `mention_type`。词典命中产生 `OPERATION`、`VALUE`、`OBJECT`、`RELATION`、`ATTRIBUTE`；结构化抽取产生 `LITERAL_VALUE`、`COMPARISON_OPERATOR`、`QUANTIFIER`、`TIME_EXPRESSION`。

本步骤输入：

```json
{
  "preprocessing_output": {
    "accepted": true,
    "original_question": "查询金牌服务穿越的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址",
    "core_question": "查询金牌服务穿越的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址",
    "clarification_request": null
  },
  "question_framing": {
    "enabled": true,
    "atoms": [
      {"atom_id": "QA1", "text": "金牌服务", "roles": ["FIND_OBJECT", "FILTER_CONDITION"], "span": [2, 6]},
      {"atom_id": "QA2", "text": "穿越的隧道", "roles": ["RELATION_PATH"], "span": [6, 11]},
      {"atom_id": "QA4", "text": "隧道的IETF标准", "roles": ["RETURN_CONTENT"], "span": [19, 28]},
      {"atom_id": "QA5", "text": "源网元的IP地址", "roles": ["RETURN_CONTENT"], "span": [29, 37]}
    ]
  }
}
```

这个 JSON 表示预处理认为问题可以继续进入 Cypher 生成流程。Lexer 使用 `core_question` 做词典扫描和向量召回，`original_question` 只保留在 trace 中用于回溯；`question_framing` 是可选 hint，缺失时不影响 Step 1 执行。

本步骤输出：

```json
{
  "lexer_output": {
    "core_question": "查询金牌服务穿越的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址",
    "mentions": [
      {"mention_id": "M1", "mention_type": "OPERATION", "surface": "查询", "span": [0, 2], "canonical_id": "OP_QUERY"},
      {"mention_id": "M2", "mention_type": "VALUE", "surface": "金牌", "span": [2, 4], "canonical_id": "ServiceQuality.Gold", "candidate_refs": ["Service.quality_of_service"]},
      {"mention_id": "M3", "mention_type": "OBJECT", "surface": "服务", "span": [4, 6], "canonical_id": "Service"},
      {"mention_id": "M4", "mention_type": "RELATION", "surface": "穿越", "span": [6, 8], "canonical_id": "REL_PATH_THROUGH", "match_source": "vector_recall", "vector_recall_id": "VR1"},
      {"mention_id": "M5", "mention_type": "OBJECT", "surface": "隧道", "span": [9, 11], "canonical_id": "Tunnel"},
      {"mention_id": "M6", "mention_type": "RELATION", "surface": "源网元", "span": [13, 16], "canonical_id": "REL_TUNNEL_SRC"},
      {"mention_id": "M7", "mention_type": "OPERATION", "surface": "返回", "span": [17, 19], "canonical_id": "OP_RETURN_FIELD"},
      {"mention_id": "M8", "mention_type": "OBJECT", "surface": "隧道", "span": [19, 21], "canonical_id": "Tunnel"},
      {"mention_id": "M9", "mention_type": "ATTRIBUTE", "surface": "IETF标准", "span": [22, 28], "canonical_id": "Tunnel.ietf_standard"},
      {"mention_id": "M10", "mention_type": "RELATION", "surface": "源网元", "span": [29, 32], "canonical_id": "REL_TUNNEL_SRC"},
      {"mention_id": "M11", "mention_type": "ATTRIBUTE", "surface": "IP地址", "span": [33, 37], "canonical_id": "NetworkElement.ip_address"}
    ],
    "context_signals": [
      {"signal_id": "CS1", "signal_type": "PROXIMAL_MODIFIER", "text": "金牌服务", "supports": ["M2", "M3"]},
      {"signal_id": "CS2", "signal_type": "ROLE_RELATION_CUE", "text": "源网元", "supports": ["M6", "M10"]},
      {"signal_id": "CS3", "signal_type": "PROXIMAL_MODIFIER", "text": "隧道的IETF标准", "supports": ["M8", "M9"]},
      {"signal_id": "CS4", "signal_type": "PROXIMAL_MODIFIER", "text": "源网元的IP地址", "supports": ["M10", "M11"]}
    ],
    "shape_signals": [
      {"signal_id": "SS1", "signal_type": "PROJECTION_REGION_CUE", "marker_mention_id": "M7", "projected_mention_ids": ["M9", "M11"]}
    ],
    "unmatched_fragments": [
      {"fragment_id": "UF1", "surface": "穿越", "span": [6, 8], "reason": "no_dictionary_hit"}
    ],
    "vector_recalls": [
      {
        "recall_id": "VR1",
        "fragment_id": "UF1",
        "surface": "穿越",
        "expected_mention_type": "RELATION",
        "top_candidates": [
          {"canonical_id": "REL_PATH_THROUGH", "matched_surface": "穿过", "score": 0.91}
        ],
        "accepted_candidate_id": "REL_PATH_THROUGH"
      }
    ],
    "unmatched_spans": []
  }
}
```

这个 JSON 是词法层交付物：`mentions` 是原文命中的可处理片段，`context_signals` 是局部修饰和角色线索，`shape_signals` 说明“返回”后面是投影字段区域。这里的“穿越”没有直接命中词典，所以先进入 `unmatched_fragments`，再由向量召回补成关系 mention `M4`；`vector_recalls` 记录召回过程，`unmatched_spans` 表示最终仍无法解释的原文区间。如果问题里写的是“穿过”，它会直接命中词典里的 `REL_PATH_THROUGH`，不会走向量召回。`IETF标准` 在词法层是 `ATTRIBUTE` mention，canonical id 是 `Tunnel.ietf_standard`；它会在 3.2 映射成本体属性，并在 3.5 绑定到 `Tunnel` 语义节点作为投影字段。

结构化抽取示例：

```json
{
  "mentions": [
    {"mention_id": "M2", "mention_type": "ATTRIBUTE", "surface": "延迟", "canonical_id": "Service.latency"},
    {"mention_id": "M3", "mention_type": "COMPARISON_OPERATOR", "surface": "小于", "canonical_id": "OP_LT", "metadata": {"cypher_op": "<"}},
    {"mention_id": "M4", "mention_type": "LITERAL_VALUE", "surface": "20ms", "canonical_id": "LITERAL_RUNTIME", "metadata": {"raw": "20ms"}},
    {"mention_id": "M5", "mention_type": "QUANTIFIER", "surface": "所有", "canonical_id": "QUANT_ALL", "metadata": {"semantic": "no_implicit_filter"}}
  ],
  "context_signals": [
    {"signal_id": "CS1", "signal_type": "PREDICATE_GROUP", "text": "延迟小于20ms", "supports": ["Service.latency", "OP_LT", "20ms"]},
    {"signal_id": "CS2", "signal_type": "QUANTIFIER_BINDING", "text": "所有服务", "supports": ["QUANT_ALL", "no_implicit_filter"]}
  ]
}
```

## Step 2：意图与答案形态识别 Intent / Shape

Step 2 负责判断用户问题属于哪类查询，以及预期返回形态是什么。它只回答“用户想要什么答案”，不做本体映射，也不选择路径。

它主要做：

- 识别用户是要查记录、查路径、统计、对比，还是其他类型问题。
- 生成初始 `shape`，例如是否需要投影字段、是否需要路径解析、是否需要聚合。
- 消费量词信号；例如 `QUANT_ALL` 不改变 intent 但写入 `filter_level_hint=explicit_only_no_implicit`，`QUANT_NONE` 先进入 `quantifier_effects`，为 absence/existence intent 做准备。
- 如果无法识别 intent，输出澄清请求。
- 规则和召回不能稳定判断时，可进入 LLM 兜底；澄清请求进入统一澄清反问通道。

本步骤输入：

```json
{
  "intent_input": {
    "core_question": "查询金牌服务穿越的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址",
    "shape_signals": [
      {"signal_id": "SS1", "signal_type": "PROJECTION_REGION_CUE", "marker_mention_id": "M7", "projected_mention_ids": ["M9", "M11"]}
    ]
  }
}
```

这个 JSON 表示 Step 2 只判断“用户想要什么答案形态”。它使用 `core_question` 做 intent 判断，使用 `shape_signals` 判断是否需要投影、聚合、排序等初始 shape；`mentions` 和 `context_signals` 从 Step 3 开始再消费。

本步骤输出：

```json
{
  "intent_output": {
    "intent": {
      "primary": "record_retrieval_query",
      "secondary": "related_record_query",
      "source": "rule",
      "confidence": 0.92
    },
    "planning_prompt_text": "用户想查询相关记录，并返回指定字段。后续应重点关注过滤条件、路径对象和返回字段所属对象。",
    "initial_shape": {
      "answer_type": "records",
      "requires_projection": true,
      "requires_path": true,
      "aggregation": null,
      "projection_region": {
        "cue_mention_id": "M7",
        "projected_mention_ids": ["M9", "M11"]
      }
    },
    "clarification_request": null
  }
}
```

这个 JSON 表示系统判断用户要查相关记录，并且需要返回具体字段；`initial_shape` 是后续规划使用的初始答案形态。

## Step 3：本体逻辑规划 Ontology Planner

Step 3 负责把 Step 1 的 mention 和线索，结合 Step 2 的 intent / initial shape，转换成本体级 logical plan。它不关心物理图库字段，只使用本体对象、关系、属性和值。

### 3.1 对象提取与角色标注

从 mention 序列里提取后续规划真正需要关注的对象，并标注这些对象可能承担的角色。

它主要做：

- 根据用户问题、intent 说明和 mention 片段，筛选关键对象。
- 给对象标注角色，例如过滤主体、路径主体、投影主体、返回主体。
- 保留 LLM 的原始选择文本，结构化结果由服务层生成。
- 对象不足或角色不明时，输出结构化澄清原因，交给统一澄清反问通道。

3.1 使用固定角色配置约束 LLM 的标注结果：

| 角色 | 含义 |
|---|---|
| `filter_subject` | 被过滤条件限定的对象，例如“金牌服务”里的“服务”。 |
| `path_subject` | 参与关系路径连接的对象或角色，例如“隧道”“源网元”。 |
| `projection_subject` | 返回字段所属的对象，例如“隧道的IETF标准”里的“隧道”。 |
| `return_subject` | 需要把对象本身作为结果返回时使用；如果只是返回字段，使用 `projection_subject`。 |

本步骤输入：

```json
{
  "object_role_selection_input": {
    "core_question": "查询金牌服务穿越的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址",
    "intent": {
      "primary": "record_retrieval_query",
      "secondary": "related_record_query"
    },
    "planning_prompt_text": "用户想查询相关记录，并返回指定字段。后续应重点关注过滤条件、路径对象和返回字段所属对象。",
    "candidate_mentions": [
      {"mention_id": "M3", "mention_type": "OBJECT", "surface": "服务", "span": [4, 6]},
      {"mention_id": "M5", "mention_type": "OBJECT", "surface": "隧道", "span": [9, 11]},
      {"mention_id": "M6", "mention_type": "RELATION", "surface": "源网元", "span": [13, 16], "candidate_reason": "role_like_relation"},
      {"mention_id": "M8", "mention_type": "OBJECT", "surface": "隧道", "span": [19, 21]},
      {"mention_id": "M10", "mention_type": "RELATION", "surface": "源网元", "span": [29, 32], "candidate_reason": "role_like_relation"}
    ],
    "evidence_mentions": [
      {"mention_id": "M2", "mention_type": "VALUE", "surface": "金牌", "used_as": "filter_evidence_for_M3"},
      {"mention_id": "M4", "mention_type": "RELATION", "surface": "穿越", "used_as": "path_evidence"},
      {"mention_id": "M7", "mention_type": "OPERATION", "surface": "返回", "used_as": "projection_region_marker"},
      {"mention_id": "M9", "mention_type": "ATTRIBUTE", "surface": "IETF标准", "used_as": "projection_evidence_for_M8"},
      {"mention_id": "M11", "mention_type": "ATTRIBUTE", "surface": "IP地址", "used_as": "projection_evidence_for_M10"}
    ],
    "context_and_shape_evidence": [
      {"signal_id": "CS1", "signal_type": "PROXIMAL_MODIFIER", "text": "金牌服务", "supports": ["M2", "M3"]},
      {"signal_id": "CS2", "signal_type": "ROLE_RELATION_CUE", "text": "源网元", "supports": ["M6", "M10"]},
      {"signal_id": "CS3", "signal_type": "PROXIMAL_MODIFIER", "text": "隧道的IETF标准", "supports": ["M8", "M9"]},
      {"signal_id": "CS4", "signal_type": "PROXIMAL_MODIFIER", "text": "源网元的IP地址", "supports": ["M10", "M11"]},
      {"signal_id": "SS1", "signal_type": "PROJECTION_REGION_CUE", "marker_mention_id": "M7", "projected_mention_ids": ["M9", "M11"]}
    ]
  }
}
```

这个 JSON 表示 3.1 的运行态输入。`intent` 来自 Step 2；`planning_prompt_text` 是 intent 对应的中文问题类型说明；`candidate_mentions` 是待选择的对象片段；`evidence_mentions` 是辅助判断的原文片段；`context_and_shape_evidence` 是 Step 1 产出的上下文线索和答案形态线索。

本步骤输出：

```json
{
  "object_role_selection_output": {
    "llm_raw_output": "选择 SM1：filter_subject、path_subject。理由：\"金牌服务\"是被限定的对象，且通过\"穿越\"关系参与路径连接。\n选择 SM2：path_subject。理由：\"隧道\"是\"穿越\"关系的直接对象，属于路径连接的一部分。\n选择 SM3：path_subject。理由：\"源网元\"是路径中的角色对象，明确出现在问题中。\n选择 SM4：projection_subject。理由：\"隧道的IETF标准\"表明该字段来自\"隧道\"对象，需关注其属性。\n选择 SM5：projection_subject。理由：\"源网元的IP地址\"表明该字段来自\"源网元\"对象，需关注其属性。",
    "selected_objects": [
      {"selection_id": "SM1", "surface": "服务", "mention_ids": ["M3"], "roles": ["filter_subject", "path_subject"]},
      {"selection_id": "SM2", "surface": "隧道", "mention_ids": ["M5"], "roles": ["path_subject"]},
      {"selection_id": "SM3", "surface": "源网元", "mention_ids": ["M6"], "roles": ["path_subject"]},
      {"selection_id": "SM4", "surface": "隧道", "mention_ids": ["M8"], "roles": ["projection_subject"]},
      {"selection_id": "SM5", "surface": "源网元", "mention_ids": ["M10"], "roles": ["projection_subject"]}
    ],
    "clarification_request": null
  }
}
```

这个 JSON 只说明哪些 mention 需要继续关注、它们承担什么角色。它还不映射本体，也不决定路径；`llm_raw_output` 是模型原话，`selected_objects` 是服务层解析后的结构化结果。

### 3.2 Mention 映射到本体

把 mention 映射到本体概念。

它主要做：

- 把对象 mention 映射为本体 class。
- 把关系 mention 映射为本体 relation 或 relation role。
- 把属性 mention 映射为本体 attribute 或属性候选族。
- 把值 mention 映射为 enum value、literal value 或过滤值线索。
- 保留候选族，供后续属性绑定和路径选择使用。

本步骤输入：

```json
{
  "lexer_trace": {
    "mentions": [
      {"mention_type": "VALUE", "surface": "金牌", "canonical_id": "ServiceQuality.Gold", "metadata": {"candidate_refs": ["Service.quality_of_service"]}},
      {"mention_type": "OBJECT", "surface": "服务", "canonical_id": "Service"},
      {"mention_type": "RELATION", "surface": "穿越", "canonical_id": "REL_PATH_THROUGH", "metadata": {"match_source": "vector_recall"}},
      {"mention_type": "OBJECT", "surface": "隧道", "canonical_id": "Tunnel"},
      {"mention_type": "RELATION", "surface": "源网元", "canonical_id": "REL_TUNNEL_SRC"},
      {"mention_type": "OBJECT", "surface": "隧道", "canonical_id": "Tunnel"},
      {"mention_type": "ATTRIBUTE", "surface": "IETF标准", "canonical_id": "Tunnel.ietf_standard"},
      {"mention_type": "RELATION", "surface": "源网元", "canonical_id": "REL_TUNNEL_SRC"},
      {"mention_type": "ATTRIBUTE", "surface": "IP地址", "canonical_id": "NetworkElement.ip_address"}
    ]
  },
  "object_role_selection": {
    "selected_objects": [
      {"candidate_id": "SM1", "mention_id": "m_service_1", "roles": ["filter_subject", "path_subject"]},
      {"candidate_id": "SM2", "mention_id": "m_tunnel_1", "roles": ["path_subject"]},
      {"candidate_id": "SM3", "mention_id": "m_rel_tunnel_src_1", "roles": ["path_subject"]},
      {"candidate_id": "SM4", "mention_id": "m_tunnel_2", "roles": ["projection_subject"]},
      {"candidate_id": "SM5", "mention_id": "m_rel_tunnel_src_2", "roles": ["projection_subject"]}
    ]
  }
}
```

这对应代码里的真实调用：`OntologyMappingService.map(lexer_trace=lexer_trace, object_role_selection=object_role_selection_trace.object_role_selection)`。3.2 主要读取 `lexer_trace.mentions` 做本体映射，并用 `object_role_selection.selected_objects` 回填哪些 mention 是后续规划重点以及它们的角色。向量召回结果已经体现在对应 mention 的 `canonical_id` 或 metadata 中。

本步骤输出：

```json
{
  "ontology_mapping": {
    "ontology_objects": [
      {
        "object_id": "OO1",
        "class_id": "Service",
        "source_mapping_id": "OM2",
        "object_candidate_id": "SM1",
        "selected_roles": ["filter_subject", "path_subject"],
        "evidence_refs": ["OM2"]
      },
      {
        "object_id": "OO2",
        "class_id": "Tunnel",
        "source_mapping_id": "OM4",
        "object_candidate_id": "SM2",
        "selected_roles": ["path_subject"],
        "evidence_refs": ["OM4"]
      },
      {
        "object_id": "OO3",
        "class_id": "NetworkElement",
        "source_mapping_id": "OM5",
        "object_candidate_id": "SM3",
        "selected_roles": ["path_subject", "projection_subject"],
        "role_hint": {
          "relation_id": "TUNNEL_SRC",
          "role": "source",
          "from_class": "Tunnel"
        },
        "evidence_refs": ["OM5", "OM8"]
      }
    ],
    "ontology_relation_hints": [
      {
        "relation_hint_id": "ORH1",
        "relation_id": "SERVICE_USES_TUNNEL",
        "from_class": "Service",
        "to_class": "Tunnel",
        "from_object_id": "OO1",
        "to_object_id": "OO2",
        "evidence_refs": ["OM3"]
      },
      {
        "relation_hint_id": "ORH2",
        "relation_id": "TUNNEL_SRC",
        "role": "source",
        "from_class": "Tunnel",
        "to_class": "NetworkElement",
        "from_object_id": "OO2",
        "to_object_id": "OO3",
        "evidence_refs": ["OM5", "OM8"]
      }
    ],
    "ontology_values": [
      {
        "value_id": "OV1",
        "ontology_id": "ServiceQuality.Gold",
        "constrains_attribute": "Service.quality_of_service",
        "evidence_refs": ["OM1"]
      }
    ],
    "ontology_attributes": [
      {
        "attribute_id": "OA1",
        "ontology_id": "Tunnel.ietf_standard",
        "parent_class": "Tunnel",
        "evidence_refs": ["OM7"]
      },
      {
        "attribute_id": "OA2",
        "ontology_id": "NetworkElement.ip_address",
        "parent_class": "NetworkElement",
        "evidence_refs": ["OM9"]
      }
    ],
    "evidence": [
      {
        "evidence_id": "OM1",
        "mention_id": "m_servicequality_gold_1",
        "lexical_type": "VALUE",
        "text": "金牌",
        "span": [2, 4],
        "map_source": "candidate_refs"
      },
      {
        "evidence_id": "OM2",
        "mention_id": "m_service_1",
        "lexical_type": "OBJECT",
        "text": "服务",
        "span": [4, 6],
        "map_source": "candidate_refs"
      },
      {
        "evidence_id": "OM3",
        "mention_id": "m_rel_path_through_1",
        "lexical_type": "RELATION",
        "text": "穿越",
        "span": [6, 8],
        "map_source": "vector_recall"
      },
      {
        "evidence_id": "OM4",
        "mention_id": "m_tunnel_1",
        "lexical_type": "OBJECT",
        "text": "隧道",
        "span": [9, 11],
        "map_source": "candidate_refs"
      },
      {
        "evidence_id": "OM5",
        "mention_id": "m_rel_tunnel_src_1",
        "lexical_type": "RELATION",
        "text": "源网元",
        "span": [13, 16],
        "map_source": "mention_to_ontology"
      },
      {
        "evidence_id": "OM7",
        "mention_id": "m_tunnel_ietf_standard_1",
        "lexical_type": "ATTRIBUTE",
        "text": "IETF标准",
        "span": [22, 28],
        "map_source": "candidate_refs"
      },
      {
        "evidence_id": "OM8",
        "mention_id": "m_rel_tunnel_src_2",
        "lexical_type": "RELATION",
        "text": "源网元",
        "span": [29, 32],
        "map_source": "mention_to_ontology"
      },
      {
        "evidence_id": "OM9",
        "mention_id": "m_networkelement_ip_address_1",
        "lexical_type": "ATTRIBUTE",
        "text": "IP地址",
        "span": [33, 37],
        "map_source": "candidate_refs"
      }
    ]
  }
}
```

这个 JSON 是 3.2 应交付给本体层后续步骤的输出形状。`ontology_objects`、`ontology_relation_hints`、`ontology_attributes`、`ontology_values` 是下游消费的本体结构；`evidence` 保存原文来源，方便 trace、审计和 prompt 展示。3.3 基于这些本体结构选择路径。

### 3.3 本体路径选择

为对象之间的连接选择本体路径。

它主要做：

- 根据 3.2 的本体对象和本体关系线索生成路径选择任务。
- 从本体关系图里枚举候选路径。
- 单候选路径由服务层自动接受。
- 多候选路径交给 LLM 在候选中选择。
- 输出最终 `selected_paths`，并回填路径相关 shape 信息。
- 路径无法安全选择时，输出结构化澄清原因，交给统一澄清反问通道。

本步骤输入：

```json
{
  "ontology_mapping": {
    "ontology_objects": [
      {
        "object_id": "OO1",
        "class_id": "Service",
        "selected_roles": ["filter_subject", "path_subject"],
        "evidence_refs": ["OM2"]
      },
      {
        "object_id": "OO2",
        "class_id": "Tunnel",
        "selected_roles": ["path_subject"],
        "evidence_refs": ["OM4"]
      },
      {
        "object_id": "OO3",
        "class_id": "NetworkElement",
        "selected_roles": ["path_subject", "projection_subject"],
        "role_hint": {"relation_id": "TUNNEL_SRC", "role": "source", "from_class": "Tunnel"},
        "evidence_refs": ["OM5", "OM8"]
      }
    ],
    "ontology_relation_hints": [
      {
        "relation_hint_id": "ORH1",
        "relation_id": "SERVICE_USES_TUNNEL",
        "from_class": "Service",
        "to_class": "Tunnel",
        "from_object_id": "OO1",
        "to_object_id": "OO2",
        "evidence_refs": ["OM3"]
      },
      {
        "relation_hint_id": "ORH2",
        "relation_id": "TUNNEL_SRC",
        "role": "source",
        "from_class": "Tunnel",
        "to_class": "NetworkElement",
        "from_object_id": "OO2",
        "to_object_id": "OO3",
        "evidence_refs": ["OM5", "OM8"]
      }
    ]
  },
  "question": "查询金牌服务穿越的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址"
}
```

这对应代码里的目标调用：`OntologyPathSelectionService.fill(ontology_mapping=..., question=...)`。3.3 读取 3.2 产出的本体对象和本体关系线索生成 `path_requests`。`question` 在 LLM 选择多候选路径时用于提示词；中文证据从 `evidence_refs` 反查后展示给模型。

本步骤输出：

```json
{
  "path_selection_output": {
    "path_requests": [
      {"request_id": "PR1", "from_object_id": "O1", "to_object_id": "O2", "relation_hint": null},
      {"request_id": "PR2", "from_object_id": "O2", "to_object_id": "O3", "relation_hint": "TUNNEL_SRC"}
    ],
    "candidate_paths": [
      {"path_id": "P1", "request_id": "PR1", "relation_chain": ["SERVICE_USES_TUNNEL"], "status": "acceptable"},
      {"path_id": "P2", "request_id": "PR2", "relation_chain": ["TUNNEL_SRC"], "status": "acceptable"}
    ],
    "selected_paths": [
      {"request_id": "PR1", "path_id": "P1", "relation_chain": ["SERVICE_USES_TUNNEL"], "selected_by": "auto_single_candidate"},
      {"request_id": "PR2", "path_id": "P2", "relation_chain": ["TUNNEL_SRC"], "selected_by": "auto_single_candidate"}
    ],
    "shape_updates": {
      "hop_count": 2,
      "relation_chain_type": "fixed_chain"
    },
    "clarification_request": null
  }
}
```

这个 JSON 说明对象之间的本体连接已经确定。`PR1` 没有可直接使用的关系提示，因此根据 `Service` 和 `Tunnel` 在本体图里的唯一可接受路径选择 `SERVICE_USES_TUNNEL`；`PR2` 使用“源网元”对应的 `TUNNEL_SRC`。这里每个连接任务只有一个可接受路径，所以服务层直接接受，没有调用 LLM。

### 3.4 指代消解

判断多个本体对象记录是否指向同一个业务对象，并合并成最终语义节点。

它主要做：

- 为可能同指的对象记录生成候选对。
- 没有同指候选对时，不调用 LLM，直接把对象记录作为独立语义节点输出。
- 利用原文位置、返回字段区域、区分词和已接受路径作为判断证据。
- 调用 LLM 判断“同一个对象 / 不同对象 / 需要澄清”。
- 输出合并后的语义节点。
- 同指关系无法判断时，输出结构化澄清原因，交给统一澄清反问通道。

本步骤输出：

```json
{
  "coreference_output": {
    "candidate_pairs": [
      {"pair_id": "CP1", "left_object_id": "O2", "right_object_id": "O4", "decision": "same_object", "evidence": ["same_class", "projection_mentions_path_object"]},
      {"pair_id": "CP2", "left_object_id": "O3", "right_object_id": "O5", "decision": "same_object", "evidence": ["same_class", "same_role_relation"]}
    ],
    "semantic_nodes": [
      {"node_id": "N1", "class_id": "Service", "source_object_ids": ["O1"]},
      {"node_id": "N2", "class_id": "Tunnel", "source_object_ids": ["O2", "O4"]},
      {"node_id": "N3", "class_id": "NetworkElement", "source_object_ids": ["O3", "O5"]}
    ],
    "clarification_request": null
  }
}
```

这个 JSON 把多次出现的对象记录合并成最终语义节点。后续步骤只使用 `N1/N2/N3`，不会再区分路径里的“隧道”和返回字段里的“隧道”。

### 3.5 谓词组装、属性、值与投影绑定

把过滤条件和返回字段绑定到具体语义节点上。

它主要做：

- 把“属性 + 运算符 + 字面值”组装成完整谓词。
- 对字面值做基于绑定属性的类型推断；Step 1 只抽原文，不做属性相关类型判断。
- 为每个待绑定的属性、值或运行时字面值生成绑定候选。
- 无候选时输出资料缺口或澄清请求。
- 唯一候选由服务层自动接受。
- 多候选交给 LLM 选择。
- 输出 filter 绑定、projection 绑定和相关 shape 更新。
- 字段或条件归属不明时，输出结构化澄清原因，交给统一澄清反问通道。

本步骤输出：

```json
{
  "binding_output": {
    "filters": [
      {
        "filter_id": "F1",
        "node_id": "N1",
        "attribute_id": "Service.quality_of_service",
        "operator": "=",
        "value_kind": "enum",
        "value_id": "ServiceQuality.Gold",
        "source_mentions": ["M2"]
      },
      {
        "filter_id": "F2",
        "node_id": "N1",
        "attribute_id": "Service.latency",
        "operator": "<",
        "value_kind": "literal",
        "value_literal": {"raw": "20ms", "parsed": 20, "type": "duration_ms", "unit": "ms"},
        "source_mentions": ["M12", "M13", "M14"],
        "composed_by": "predicate_assembly"
      }
    ],
    "projections": [
      {
        "projection_id": "PJ1",
        "node_id": "N2",
        "attribute_id": "Tunnel.ietf_standard",
        "alias": "tunnel_ietf_standard",
        "source_mentions": ["M9"]
      },
      {
        "projection_id": "PJ2",
        "node_id": "N3",
        "attribute_id": "NetworkElement.ip_address",
        "alias": "source_ne_ip_address",
        "source_mentions": ["M11"]
      }
    ],
    "shape_updates": {
      "filter_level": "single_subject",
      "projection_count": 2
    },
    "clarification_request": null
  }
}
```

这个 JSON 把过滤值和返回字段绑定到具体语义节点上：`金牌` 约束 `Service`，`延迟小于20ms` 由谓词组装生成 literal filter，`IETF标准` 属于 `Tunnel`，`IP地址` 属于源网元。

谓词组装扩展不新增主流程 Step；不改 `domain_ontology` 结构；不改 3.1-3.4；不在 Step 1 做类型推断；不在 Step 5 做参数化。Step 5 只复用 `value_kind=literal` 的 parsed value 直接渲染 Cypher。

### 3.6 Shape 回填与结构预校验

汇总 Step 3 前面各阶段的结果，形成完整 logical plan，并在进入 Step 4 前做结构预检查。

它主要做：

- 回填最终 `hop_count`、`relation_chain_type`、`filter_level` 等 shape 字段。
- 汇总 unresolved items，判断是否需要澄清、资料补齐或工程失败。
- 检查节点、边、属性、过滤、投影和 shape 是否结构完整。
- 通过后输出本体级 logical plan。

本步骤输出：

```json
{
  "logical_plan_output": {
    "logical_plan": {
      "intent": {
        "primary": "record_retrieval_query",
        "secondary": "related_record_query"
      },
      "shape": {
        "answer_type": "records",
        "hop_count": 2,
        "relation_chain_type": "fixed_chain",
        "requires_projection": true
      },
      "nodes": [
        {"node_id": "N1", "class_id": "Service", "alias": "s"},
        {"node_id": "N2", "class_id": "Tunnel", "alias": "t"},
        {"node_id": "N3", "class_id": "NetworkElement", "alias": "n"}
      ],
      "edges": [
        {"edge_id": "E1", "from_node_id": "N1", "to_node_id": "N2", "relation_id": "SERVICE_USES_TUNNEL"},
        {"edge_id": "E2", "from_node_id": "N2", "to_node_id": "N3", "relation_id": "TUNNEL_SRC"}
      ],
      "filters": [
        {"filter_id": "F1", "node_id": "N1", "attribute_id": "Service.quality_of_service", "operator": "=", "value_id": "ServiceQuality.Gold"}
      ],
      "projections": [
        {"projection_id": "PJ1", "node_id": "N2", "attribute_id": "Tunnel.ietf_standard", "alias": "tunnel_ietf_standard"},
        {"projection_id": "PJ2", "node_id": "N3", "attribute_id": "NetworkElement.ip_address", "alias": "source_ne_ip_address"}
      ]
    },
    "precheck_result": {
      "passed": true,
      "failures": []
    }
  }
}
```

这个 JSON 是 Step 3 的最终产物：完整的本体级 logical plan。它还没有任何物理图库 label、edge type 或 property，只描述业务语义。

## Step 4：语义校验 Semantic Validator

Step 4 负责验收 Step 3 产出的 logical plan 是否符合本体语义和业务约束，并把失败原因分成澄清、资料缺口或工程错误。

它主要做：

- 检查 node、edge、projection、filter、metric 引用是否完整。
- 检查 class、relation、attribute、value 是否存在于本体资产。
- 检查 relation 的方向、domain / range 和多跳 chain 是否连通。
- 检查 projection / filter / metric condition 的属性是否属于对应对象。
- 检查 answer shape 是否匹配 intent，例如明细查询需要返回字段，指标查询需要 metric。
- 检查 cardinality、必填关系、业务约束和不变量。

本步骤输出：

```json
{
  "semantic_validation_output": {
    "status": "accepted",
    "checks": [
      {"check": "node_classes_exist", "accepted": true},
      {"check": "relation_domain_range_valid", "accepted": true},
      {"check": "attribute_owner_valid", "accepted": true},
      {"check": "filter_value_valid", "accepted": true},
      {"check": "shape_matches_intent", "accepted": true},
      {"check": "relation_cardinality_policy", "accepted": true}
    ],
    "validated_logical_plan_ref": "logical_plan_output.logical_plan",
    "failure_channel": null,
    "clarification_request": null
  }
}
```

这个 JSON 表示 logical plan 已经通过业务语义校验，可以交给物理编译层。常见场景包括：明细字段表、单指标统计、分组统计、条件统计、路径查询和存在性判断。失败时，Step 4 会保留具体 check、失败元素和建议修正方向。

## Step 5：物理编译 Physical Compiler

Step 5 负责把通过校验的本体级 logical plan 编译成 TuGraph Cypher。

它主要做：

- 根据 answer shape 选择明细、指标、分组指标、路径或存在性 renderer。
- 把本体 class 映射为物理 node label。
- 把本体 relation 映射为物理 edge type。
- 把本体 attribute 映射为图属性。
- 根据 logical plan 生成 `MATCH`、`WHERE`、`RETURN`、聚合、条件聚合、排序和分页。
- 把本体枚举值通过 `value_transform` 转换成图库存储值。
- 校验映射是否能落到当前物理 schema。

本步骤输出：

```json
{
  "physical_compile_output": {
    "cypher": "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)-[:TUNNEL_SRC]->(n:NetworkElement)\nWHERE s.quality_of_service = 'Gold'\nRETURN t.ietf_standard AS tunnel_ietf_standard,\n       n.ip_address AS source_ne_ip_address",
    "parameters": {},
    "mapping_used": {
      "nodes": {"Service": "Service", "Tunnel": "Tunnel", "NetworkElement": "NetworkElement"},
      "relations": {"SERVICE_USES_TUNNEL": "SERVICE_USES_TUNNEL", "TUNNEL_SRC": "TUNNEL_SRC"},
      "properties": {
        "Service.quality_of_service": "quality_of_service",
        "Tunnel.ietf_standard": "ietf_standard",
        "NetworkElement.ip_address": "ip_address"
      }
    }
  }
}
```

这个 JSON 是最终可执行输出：`cypher` 是发给 TuGraph 的查询语句，`mapping_used` 记录本体概念如何落到物理图 schema 上。Step 5 的常见输出形态包括：

| 场景 | Cypher 形态 |
|---|---|
| 明细字段表 | `MATCH ... WHERE ... RETURN t.name AS tunnel_name` |
| 单指标统计 | `MATCH ... RETURN count(t) AS tunnel_count` |
| 分组统计 | `MATCH ... RETURN s.bandwidth AS service_bandwidth, count(t) AS tunnel_count` |
| 条件统计 | `RETURN sum(CASE WHEN ... THEN 1 ELSE 0 END) AS ...` |
| 路径查询 | `MATCH p=(...)-[...]-(...) RETURN p` |
| 存在性判断 | `RETURN count(*) > 0 AS exists` |

缺少 mapping、mapping 指向不存在的 label / edge type / property、renderer 覆盖不到当前 shape 时，输出工程失败或资料缺口，并保留 mapping 版本、schema 版本和缺失项。
