# Cypher 生成设计简版

本文是 `cypher-generation-design-based-on-ontology.md` 的简洁版，只说明整体流程、每一步做什么，以及核心输入输出。示例 JSON 展示步骤之间传递的关键字段；完整 trace、资源版本、提示词和工程接口细节放在详细版文档中。

## 整体流程

```text
上游预处理产出 core_question
  -> Step 1 词法层 Lexer
  -> Step 2 逻辑规划 Logical Planner
  -> Step 3 语义校验 Semantic Validator
  -> Step 4 物理编译 Physical Compiler
  -> 执行 Cypher / 返回结果
```

核心思想是把“自然语言到 Cypher”拆成四层：

1. 先把问题切成可处理的 mention 和线索。
2. 再把 mention 规划成本体级 logical plan。
3. 再检查 logical plan 是否符合业务语义。
4. 最后把本体级计划编译成具体 Cypher。

下文用同一个问题串起每一步的输入输出：`查询金牌服务使用的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址`。

上游预处理先把用户问题归一成标准问题：

```json
{
  "preprocessing_output": {
    "accepted": true,
    "original_question": "查询金牌服务使用的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址",
    "core_question": "查询金牌服务使用的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址",
    "clarification_request": null
  }
}
```

这个 JSON 表示预处理认为问题可以继续进入 Cypher 生成流程；后续步骤统一使用 `core_question`，不直接处理原始用户输入。

## Step 1：词法层 Lexer

Step 1 负责把标准化后的 `core_question` 转成 mention 序列和词法线索。

它主要做：

- 用词典扫描业务对象、关系、属性、属性值和操作词。
- 识别没有被词典覆盖的残片，并对残片做向量召回。
- 处理重叠命中，例如“源网元”覆盖“源”和“网元”。
- 保留候选族，例如“名称”可能对应服务名称、隧道名称、网元名称。
- 抽取上下文线索和答案形态线索，例如“返回”后面的字段区域。

本步骤输出：

```json
{
  "lexer_output": {
    "core_question": "查询金牌服务使用的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址",
    "mentions": [
      {"mention_id": "M1", "mention_type": "OPERATION", "surface": "查询", "span": [0, 2], "canonical_id": "OP_QUERY"},
      {"mention_id": "M2", "mention_type": "VALUE", "surface": "金牌", "span": [2, 4], "canonical_id": "ServiceQuality.Gold", "candidate_refs": ["Service.quality_of_service"]},
      {"mention_id": "M3", "mention_type": "OBJECT", "surface": "服务", "span": [4, 6], "canonical_id": "Service"},
      {"mention_id": "M4", "mention_type": "RELATION", "surface": "使用", "span": [6, 8], "canonical_id": "REL_SERVICE_USES_TUNNEL"},
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
      {"signal_id": "CS3", "signal_type": "PROXIMAL_MODIFIER", "text": "源网元的IP地址", "supports": ["M10", "M11"]}
    ],
    "shape_signals": [
      {"signal_id": "SS1", "signal_type": "PROJECTION_REGION_CUE", "marker_mention_id": "M7", "projected_mention_ids": ["M9", "M11"]}
    ],
    "unmatched_spans": [],
    "vector_recalls": []
  }
}
```

这个 JSON 是词法层交付物：`mentions` 是原文命中的可处理片段，`context_signals` 是局部修饰和角色线索，`shape_signals` 说明“返回”后面是投影字段区域。

## Step 2：逻辑规划 Logical Planner

Step 2 负责把 Step 1 的 mention 和线索转换成本体级 logical plan。它不关心物理图库字段，只使用本体对象、关系、属性和值。

### 2.0 意图分类与初始 Shape

判断用户问题属于哪类查询，以及预期返回形态是什么。

它主要做：

- 识别用户是要查记录、查路径、统计、对比，还是其他类型问题。
- 生成初始 `shape`，例如是否需要投影字段、是否需要路径解析、是否需要聚合。
- 如果无法识别 intent，输出澄清请求。
- 规则和召回不能稳定判断时，可进入 LLM 兜底；澄清请求进入统一澄清反问通道。

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

### 2.1 对象提取与角色标注

从 mention 序列里提取后续规划真正需要关注的对象，并标注这些对象可能承担的角色。

它主要做：

- 根据用户问题、intent 说明和 mention 片段，筛选关键对象。
- 给对象标注角色，例如过滤主体、路径主体、投影主体、返回主体。
- 保留 LLM 的原始选择文本，结构化结果由服务层生成。
- 对象不足或角色不明时，输出结构化澄清原因，交给统一澄清反问通道。

本步骤输出：

```json
{
  "object_role_selection_output": {
    "llm_raw_output": "服务是过滤和路径起点；第一个隧道是路径对象；第一个源网元是路径对象；返回区域里的隧道和源网元是投影字段所属对象。",
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

### 2.2 Mention 映射到本体

把 mention 映射到本体概念。

它主要做：

- 把对象 mention 映射为本体 class。
- 把关系 mention 映射为本体 relation 或 relation role。
- 把属性 mention 映射为本体 attribute 或属性候选族。
- 把值 mention 映射为 enum value、literal value 或过滤值线索。
- 保留候选族，不在本阶段做属性绑定或路径选择。

本步骤输出：

```json
{
  "ontology_mapping_output": {
    "object_mappings": [
      {"object_id": "O1", "selection_id": "SM1", "class_id": "Service", "source_mentions": ["M3"]},
      {"object_id": "O2", "selection_id": "SM2", "class_id": "Tunnel", "source_mentions": ["M5"]},
      {"object_id": "O3", "selection_id": "SM3", "class_id": "NetworkElement", "source_mentions": ["M6"], "derived_from_relation_role": "REL_TUNNEL_SRC"},
      {"object_id": "O4", "selection_id": "SM4", "class_id": "Tunnel", "source_mentions": ["M8"]},
      {"object_id": "O5", "selection_id": "SM5", "class_id": "NetworkElement", "source_mentions": ["M10"], "derived_from_relation_role": "REL_TUNNEL_SRC"}
    ],
    "relation_mappings": [
      {"relation_mapping_id": "R1", "mention_id": "M4", "lexical_canonical_id": "REL_SERVICE_USES_TUNNEL", "ontology_relation_id": "SERVICE_USES_TUNNEL", "domain": "Service", "range": "Tunnel"},
      {"relation_mapping_id": "R2", "mention_id": "M6", "lexical_canonical_id": "REL_TUNNEL_SRC", "ontology_relation_id": "TUNNEL_SRC", "domain": "Tunnel", "range": "NetworkElement"}
    ],
    "value_mappings": [
      {"value_mapping_id": "V1", "mention_id": "M2", "value_id": "ServiceQuality.Gold", "constrains_attribute": "Service.quality_of_service"}
    ],
    "attribute_mappings": [
      {"attribute_mapping_id": "A1", "mention_id": "M9", "attribute_id": "Tunnel.ietf_standard"},
      {"attribute_mapping_id": "A2", "mention_id": "M11", "attribute_id": "NetworkElement.ip_address"}
    ],
    "unresolved": []
  }
}
```

这个 JSON 把词法 mention 落到本体概念上。`REL_TUNNEL_SRC` 是词法层关系词，映射成本体关系 `TUNNEL_SRC`，并派生出目标对象 `NetworkElement`。

### 2.3 本体路径选择

为对象之间的连接选择本体路径。

它主要做：

- 根据 2.2 的本体映射生成路径选择任务。
- 从本体关系图里枚举候选路径。
- 单候选路径由服务层自动接受。
- 多候选路径交给 LLM 在候选中选择。
- 输出最终 `selected_paths`，并回填路径相关 shape 信息。
- 路径无法安全选择时，输出结构化澄清原因，交给统一澄清反问通道。

本步骤输出：

```json
{
  "path_selection_output": {
    "path_requests": [
      {"request_id": "PR1", "from_object_id": "O1", "to_object_id": "O2", "relation_hint": "SERVICE_USES_TUNNEL"},
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

这个 JSON 说明对象之间的本体连接已经确定。这里每个连接任务只有一个可接受路径，所以服务层直接接受，没有调用 LLM。

### 2.4 指代消解

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

### 2.5 属性、值与投影绑定

把过滤条件和返回字段绑定到具体语义节点上。

它主要做：

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
        "value_id": "ServiceQuality.Gold",
        "source_mentions": ["M2"]
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
        "alias": "source_ne_ip",
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

这个 JSON 把过滤值和返回字段绑定到具体语义节点上：`金牌` 约束 `Service`，`IETF标准` 属于 `Tunnel`，`IP地址` 属于源网元。

### 2.6 Shape 回填与结构预校验

汇总 Step 2 前面各阶段的结果，形成完整 logical plan，并在进入 Step 3 前做结构预检查。

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
        {"projection_id": "PJ2", "node_id": "N3", "attribute_id": "NetworkElement.ip_address", "alias": "source_ne_ip"}
      ]
    },
    "precheck_result": {
      "passed": true,
      "failures": []
    }
  }
}
```

这个 JSON 是 Step 2 的最终产物：完整的本体级 logical plan。它还没有任何物理图库 label、edge type 或 property，只描述业务语义。

## Step 3：语义校验 Semantic Validator

Step 3 负责检查 Step 2 产出的 logical plan 是否符合业务语义约束。

它主要做：

- 检查节点类型是否存在。
- 检查关系方向和 domain / range 是否合法。
- 检查属性是否属于对应对象。
- 检查 cardinality、必填关系、业务约束和不变量。
- 检查 logical plan 是否还能被后续物理编译安全消费。
- 可由用户补充修正的语义问题，输出结构化澄清原因，交给统一澄清反问通道。

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
      {"check": "shape_matches_intent", "accepted": true}
    ],
    "validated_logical_plan_ref": "logical_plan_output.logical_plan",
    "clarification_request": null
  }
}
```

这个 JSON 表示 logical plan 已经通过业务语义校验，可以交给物理编译层；如果某条检查失败，才会进入澄清、资料缺口或工程失败分支。

## Step 4：物理编译 Physical Compiler

Step 4 负责把通过校验的本体级 logical plan 编译成 TuGraph Cypher。

它主要做：

- 把本体 class 映射为物理 node label。
- 把本体 relation 映射为物理 edge type。
- 把本体 attribute 映射为图属性。
- 根据 logical plan 生成 `MATCH`、`WHERE`、`RETURN`、聚合、排序和分页。
- 校验映射是否能落到当前物理 schema。

本步骤输出：

```json
{
  "physical_compile_output": {
    "cypher": "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)-[:TUNNEL_SRC]->(n:NetworkElement)\nWHERE s.quality_of_service = 'Gold'\nRETURN t.ietf_standard AS tunnel_ietf_standard,\n       n.ip_address AS source_ne_ip",
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

这个 JSON 是最终可执行输出：`cypher` 是发给 TuGraph 的查询语句，`mapping_used` 记录本体概念如何落到物理图 schema 上。Step 4 不做业务判断，也不调用 LLM。
