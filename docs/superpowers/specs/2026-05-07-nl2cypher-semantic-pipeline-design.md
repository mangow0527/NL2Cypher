# NL2Cypher 语义生成流水线设计

## 1. 设计目标

这份文档描述自然语言问题到 Cypher 查询的完整语义生成流水线。目标不是让 LLM 直接从问题猜 Cypher，而是把问题逐步编译成可解释、可校验、可回放的中间结构，最后再生成只读 Cypher。

核心路线：

```text
语义资产对齐
  -> TuGraph 物理 schema
  -> 知识 schema / 业务知识 / few-shot
  -> Semantic Layer contract

自然语言问题
  -> 三阶段意图识别
  -> 底层图谱槽位匹配
  -> 业务槽位 schema 选择
  -> 业务槽位填充与完整性校验
  -> 语义层 linking
  -> 语义层校验
  -> Semantic Query DSL/IR
  -> 知识选择/抽取
  -> Cypher 生成
  -> Preflight 校验
```

这条流水线参考 ChatBI 和 Semantic Layer 的主流做法：用受治理的实体、关系、属性、指标、维度、业务规则和查询 DSL 约束生成过程。LLM 可以参与补全、复杂生成和 fallback，但必须被语义层和 `SemanticQuerySpec` 约束，不能自由新增 schema 元素。

## 2. 核心分层

### 2.1 Intent

Intent 描述用户想要的答案形态，而不是具体图谱对象。它回答的是“这类问题最终要返回什么形态”：

- 明细列表或属性投影。
- 关联对象。
- 路径、可达性或拓扑结构。
- 数量、均值、最大值等指标。
- 分组统计。
- TopN / BottomN 排名。
- 存在性判断。

Intent 不直接包含实体、关系、字段和值。对象和条件由槽位与语义层承接。

### 2.2 Slot

槽位分两层：

```text
底层图谱槽位：entity、relationship、property、filter、metric、group_by、order_by、limit
业务槽位：query_object、relationship_scope、attribute_set、metric_family、group_by_dimension、order_topn、query_action
```

底层图谱槽位负责从问题里抽取候选语义元素。业务槽位负责表达业务任务是否完整，例如“关联明细查询至少需要两个对象和一个关系范围”，“指标查询必须有指标口径”。

### 2.3 Semantic Layer

Semantic Layer 是图数据库版本的语义视图。它把业务语言映射到正式图谱 schema：

- “服务/业务” -> `Service`
- “隧道” -> `Tunnel`
- “设备/网元” -> `NetworkElement`
- “服务使用隧道” -> `(:Service)-[:SERVICE_USES_TUNNEL]->(:Tunnel)`
- “类型” -> `elem_type`
- “平均时延” -> `avg(t.latency)`

TuGraph 物理 schema 是 label、edge、property 的事实源。知识 schema、业务知识和 few-shot 是业务解释源。Semantic Layer 是两者对齐后的结构化契约：它只能引用 TuGraph 已存在的物理元素，也必须覆盖知识中会指导生成的业务概念、属性引用和关系模式。

Prompt、RAG 和 few-shot 可以消费 Semantic Layer，也可以补充语法、业务解释和示例，但不能替代 Semantic Layer 直接创造 schema 权威。

### 2.4 Semantic Contract Alignment

Semantic Contract Alignment 是查询流水线的资产前置条件。它不理解单个用户问题，而是检查生成系统依赖的语义资产是否彼此一致：

- Semantic Layer 中的 entity label 必须存在于 TuGraph schema。
- Semantic Layer 中的 relationship edge 和 direction 必须符合 TuGraph edge constraints。
- Semantic Layer 中的 property、metric property、value mapping property 必须存在于对应 label。
- 知识 schema 不能引用 TuGraph 不存在的 label、edge、property。
- 业务知识和 few-shot 中出现的 `Label.property`、`(:Label)-[:EDGE]->(:Label)` 引用，必须同时存在于 TuGraph schema 和 Semantic Layer。

这一步的作用类似 MetricFlow/dbt Semantic Layer 或 Snowflake Semantic View 的 schema binding：业务语义不是孤立 prompt，而是绑定到物理数据模型并可被校验的契约。对齐失败时，系统不能把相关知识或语义配置视为可信生成依据。

### 2.5 Semantic Query DSL/IR

`SemanticQuerySpec` 是 Cypher 生成前的受控查询 DSL/IR。它表达业务语义，不直接暴露 Cypher 语法细节：

- 查询类型：`record_selection`、`metric_aggregation`、`dimension_breakdown`、`ranking`、`existence_check`。
- 参与实体、关系、字段、指标、维度和过滤条件。
- 输出字段、排序、limit、存在性输出别名。
- intent、业务槽位 schema、scenario 等来源信息。

Renderer 或受控 LLM fallback 只能围绕 `SemanticQuerySpec` 生成 Cypher。

## 3. 流水线步骤

服务处理自然语言问题前，语义资产必须处于已对齐状态。也就是说，Semantic Layer、TuGraph schema 和知识 schema / 业务知识 / few-shot 的引用关系要先通过 Semantic Contract Alignment。对齐失败属于服务级失败，不能继续使用不可信知识生成 Cypher。正式 `/api/v1/qa/questions` 入口执行这一前置检查；`/api/v1/semantic/parse` 是语义解析诊断入口，用于观察单个问题如何被编译。

### 3.1 自然语言问题输入

输入是用户原始问题，以及可选追踪字段：

```json
{
  "id": "qa-001",
  "question": "查询 Gold 服务使用的隧道名称和时延",
  "generation_run_id": "cypher-run-001"
}
```

功能：

- 保留原始问题文本。
- 为后续 intent、slot、linking、DSL、Cypher、preflight 提供同一个事实来源。
- 通过 `id` 和 `generation_run_id` 支撑日志、评测和失败归因。

实现原理：

请求进入语义解析入口后，原始字段不会被改写。后续每个阶段都只增加结构化解释，不覆盖原始问题。

### 3.2 意图识别

输入：

```text
question
```

输出示例：

```json
{
  "primary_intent": "record_retrieval_query",
  "secondary_intent": "related_record_query",
  "confidence": 0.93,
  "source": "rule",
  "decision": "accept"
}
```

功能：

- 判断答案形态。
- 选择后续业务槽位 schema 的范围。
- 约束 `SemanticQuerySpec` 的大类型。
- 在规则和向量相似度不确定时，转入 LLM 意图兜底或澄清。

实现原理：

当前采用三阶段识别：

```text
规则意图识别
  -> 向量相似度意图识别
  -> LLM 兜底意图识别
```

规则阶段优先接收高确定性问题。规则不能接受时进入向量相似度识别。向量相似度仍不能稳定接受时，进入第三阶段 LLM 意图识别。

第三阶段 LLM 只判断意图，不生成 Cypher。它必须输出受控 JSON，包含 `primary_intent`、`secondary_intent`、`confidence` 和 `decision`。当 `decision=accept` 时，流水线带着 LLM 给出的 intent 继续进入底层图谱槽位匹配；当 `decision=clarify` 或输出不合法时，流水线停止，不进入 Cypher 生成。

这里的 LLM 意图兜底和后面的受控 Cypher 兜底生成是两个不同环节。前者发生在槽位匹配之前，只补意图；后者发生在已经形成 `SemanticQuerySpec` 之后，只在确定性渲染器无法覆盖时使用。

### 3.3 底层图谱槽位匹配

输入：

```text
question
```

输出示例：

```json
{
  "entities": [
    {"text": "服务", "candidate": "service", "confidence": 0.95, "source": "dictionary"},
    {"text": "隧道", "candidate": "tunnel", "confidence": 0.96, "source": "dictionary"}
  ],
  "relationships": [
    {"text": "使用", "candidate": "service_uses_tunnel", "confidence": 0.91, "source": "dictionary"}
  ],
  "return_fields": [
    {"text": "名称", "candidate": "name", "confidence": 0.92, "source": "dictionary"},
    {"text": "时延", "candidate": "latency", "confidence": 0.92, "source": "dictionary"}
  ],
  "filters": [
    {"text": "Gold 服务", "entity": "service", "property": "quality_of_service", "operator": "=", "value": "Gold"}
  ]
}
```

功能：

- 抽取实体、关系、属性、过滤、指标、分组、排序和 limit 候选。
- 为业务槽位填充提供证据。
- 为语义层链接提供候选输入。

实现原理：

底层槽位匹配的运行前提是 intent 已被接受。这里的 intent 可以来自规则、向量相似度，也可以来自第三阶段 LLM 意图兜底。

底层槽位匹配是候选抽取器，不负责最终语义决策。它不根据 intent 改变抽取范围，而是基于词典、同义词、枚举值、聚合词、排序词和 limit 表达，从原始问题里召回所有可识别候选，并保留来源、置信度和原文位置。

intent 的作用发生在下一步：业务槽位 schema 会根据 intent 判断这些底层候选是否足够支撑当前查询任务。后续语义层再判断这些候选在图谱中是否成立。

### 3.4 业务槽位 Schema 选择

输入：

```text
intent_result
```

输出示例：

```json
{
  "schema_id": "graph_inventory.related_record",
  "scenario_id": "ops_inventory_static",
  "primary_intent": "record_retrieval_query",
  "secondary_intents": ["related_record_query"]
}
```

功能：

- 根据 intent 选择当前问题对应的业务任务 schema。
- 定义这个任务必须具备哪些业务槽位。
- 约束缺槽检查和澄清策略。

实现原理：

业务槽位 schema 由配置治理。每个 schema 绑定一级 intent 和若干二级 intent，并声明槽位的必填性、最小数量、依赖槽位、优先级、澄清问题，以及条件必填规则 `required_when`。

### 3.5 业务槽位填充与完整性校验

输入：

```text
intent_result + low_level_slots + business_slot_schema
```

输出示例：

```json
{
  "schema_id": "graph_inventory.related_record",
  "scenario_id": "ops_inventory_static",
  "slots": [
    {"name": "query_object", "values": ["service", "tunnel"], "source": "slot_matching"},
    {"name": "relationship_scope", "values": ["service_uses_tunnel"], "source": "slot_matching"},
    {"name": "attribute_set", "values": ["name", "latency"], "source": "slot_matching"},
    {"name": "query_action", "values": ["list"], "source": "intent"}
  ]
}
```

功能：

- 将底层槽位组织成业务任务槽位。
- 判断当前问题是否足以进入语义层链接。
- 对缺失的业务槽位给出澄清问题。

实现原理：

填充器把底层 entity 映射到 `query_object`，relationship 映射到 `relationship_scope`，return field 映射到 `attribute_set`，metric 映射到 `metric_family`，order 和 limit 映射到 `order_topn`，并从 intent 推导 `query_action`。

完整性校验分两类：

- 静态必填：`required=true` 的槽位必须满足 `min_count`。
- 条件必填：当 `required_when` 指定的槽位值出现时，目标槽位才变成必填。

校验失败时，流水线在语义层链接前停止。

### 3.6 语义层链接

输入：

```text
low_level_slots + semantic_layer
```

输出示例：

```json
{
  "entities": [
    {"semantic_name": "service", "label": "Service", "alias": "s"},
    {"semantic_name": "tunnel", "label": "Tunnel", "alias": "t"}
  ],
  "relationships": [
    {
      "semantic_name": "service_uses_tunnel",
      "from_entity": "service",
      "to_entity": "tunnel",
      "edge": "SERVICE_USES_TUNNEL",
      "direction": "out"
    }
  ],
  "return_fields": [
    {"semantic_name": "tunnel_name", "owner": "tunnel", "property": "name", "alias": "tunnel_name"},
    {"semantic_name": "tunnel_latency", "owner": "tunnel", "property": "latency", "alias": "tunnel_latency"}
  ],
  "filters": [
    {"owner": "service", "property": "quality_of_service", "operator": "=", "value": "Gold"}
  ]
}
```

功能：

- 把自然语言候选绑定到正式图谱 schema。
- 为后续校验和 DSL 生成提供 label、edge、property、metric。
- 防止候选槽位越过语义层直接参与 Cypher 生成。

实现原理：

Schema linker 使用 semantic layer 中的实体、关系、属性、指标和值映射来解析候选槽位。属性会结合 owner hint 和已匹配实体消歧；关系可以由显式关系槽位或实体组合推断；指标通过 semantic metric 定义绑定到 owner 和表达式。

### 3.7 语义层校验

输入：

```text
linked_semantics
```

输出示例：

```json
{
  "accepted": true,
  "diagnostics": []
}
```

功能：

- 判断 linked semantics 是否能构成合法图查询。
- 在生成 DSL 和 Cypher 前拦截不可达关系、非法属性和缺失实体。
- 生成可解释的诊断信息。

实现原理：

校验器基于 semantic layer 检查：

- 是否至少有一个 linked entity。
- relationship 的起止实体是否都在当前 query 中。
- 多实体查询是否存在可用 relationship。
- return field、group_by field、filter property 是否属于 semantic layer 中定义的 owner。

校验失败时，流水线停止，不进入 `SemanticQuerySpec` 生成。

### 3.8 Semantic Query DSL/IR 生成

输入：

```text
intent_result + business_slots + linked_semantics
```

输出示例：

```json
{
  "kind": "record_selection",
  "intent": "record_retrieval_query.related_record_query",
  "schema_id": "graph_inventory.related_record",
  "scenario_id": "ops_inventory_static",
  "entities": [
    {"name": "service", "label": "Service", "alias": "s"},
    {"name": "tunnel", "label": "Tunnel", "alias": "t"}
  ],
  "relationships": [
    {"name": "service_uses_tunnel", "from_entity": "service", "to_entity": "tunnel", "edge": "SERVICE_USES_TUNNEL", "direction": "out"}
  ],
  "projections": [
    {"name": "tunnel_name", "entity": "tunnel", "alias": "t", "property": "name", "output_alias": "tunnel_name", "expression": "t.name"}
  ],
  "filters": [
    {"entity": "service", "alias": "s", "property": "quality_of_service", "operator": "=", "value": "Gold", "left": "s.quality_of_service"}
  ]
}
```

功能：

- 把已校验的语义结果编译成受控查询 DSL/IR。
- 隔离语义理解和 Cypher 语法渲染。
- 作为 renderer、LLM fallback、preflight 和调试的共同契约。

实现原理：

Builder 根据 intent 选择 `SemanticQuerySpec.kind`：

- `record_selection`：返回实体字段或关联对象字段。
- `metric_aggregation`：返回 count、avg、max 等指标。
- `dimension_breakdown`：按维度分组聚合。
- `ranking`：按属性或指标排序并截断。
- `existence_check`：返回关系是否存在。

DSL 中的 label、edge、property 都来自 linked semantics，不从原始自然语言直接产生。

明细查询如果没有显式 return field，builder 会按当前实体补默认投影 `id` 和 `name`；关联明细会为参与关系的实体补默认投影，保证 DSL 始终有可渲染的返回列。

### 3.9 知识选择/抽取

输入：

```text
question + intent_result + semantic_query
```

输出示例：

```json
{
  "fragments": [
    {"id": "verified.service_tunnel_projection", "type": "verified_query"},
    {"id": "syntax.readonly_match_return", "type": "cypher_syntax"}
  ],
  "prompt_context": "...",
  "selection_trace": ["matched relationship service_uses_tunnel", "matched query kind record_selection"]
}
```

功能：

- 为受控 LLM fallback 提供最小必要上下文。
- 避免把完整知识包无差别塞进 prompt。
- 只选择与当前 `SemanticQuerySpec` 相关的 schema 片段、业务规则、few-shot、verified query 和 Cypher 约束。

实现原理：

知识选择不替代 semantic layer。Semantic layer 仍然是 schema 权威来源。RAG 只补充生成上下文。推荐使用两层检索：

- 符号检索：按 query kind、intent、schema_id、scenario_id、entity、relationship、metric、property 精确召回。
- 语义检索：对候选知识片段做 embedding 检索或重排，用于复杂业务规则和相似 verified query。

最终进入 prompt 的知识必须可追踪，包含片段 id、类型、来源和选择原因。知识片段中的 schema 引用必须已经通过 Semantic Contract Alignment；如果片段引用了 Semantic Layer 未暴露的字段或关系，它不能直接进入生成上下文。

### 3.10 Cypher 生成

输入：

```text
semantic_query + selected_knowledge
```

输出：

```cypher
MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)
WHERE s.quality_of_service = 'Gold'
RETURN t.name AS tunnel_name, t.latency AS tunnel_latency
```

功能：

- 将 `SemanticQuerySpec` 转换为一条只读 Cypher。
- 优先使用确定性 renderer。
- renderer 不支持时，使用受控 LLM fallback。

实现原理：

确定性 renderer 直接根据 `SemanticQuerySpec` 渲染：

- entities 和 relationships -> `MATCH`
- filters -> `WHERE`
- projections、dimensions、metrics -> `RETURN`
- order_by -> `ORDER BY`
- limit -> `LIMIT`

受控 LLM fallback 的 prompt 必须包含 `SemanticQuerySpec` JSON，并明确禁止新增未授权 label、edge、property。LLM 输出不会直接通过，必须先被 parser 提取为 Cypher，再进入 preflight。

### 3.11 Preflight 校验

输入：

```text
generated_cypher + semantic_query
```

输出：

```json
{
  "accepted": true,
  "reason": null
}
```

功能：

- 防止非只读查询进入评测或执行。
- 防止多语句、Markdown 包装、JSON 包装、解释性文本和非法 CALL。
- 检查生成 Cypher 是否越过 `SemanticQuerySpec` 引用未授权 schema。
- 检查生成 Cypher 是否遗漏关键语义条件。

实现原理：

Preflight 分两层：

1. 基础安全检查：空输出、多语句、括号不平衡、字符串未闭合、写操作、非法 CALL、非法起始子句。
2. 语义级检查：Cypher 中出现的 label、edge、MATCH/WHERE 属性和 node map 属性必须来自 `SemanticQuerySpec`；Cypher 必须覆盖 DSL 中声明的实体、关系、过滤、投影、维度、指标、排序、limit 和存在性输出别名。

典型失败原因包括：

- `empty_output`
- `multiple_statements`
- `write_operation`
- `unsupported_call`
- `unsupported_start_clause`
- `unauthorized_schema_reference`
- `semantic_query_mismatch`

## 4. 端到端样例

问题：

```text
查询 Gold 服务使用的隧道名称和时延
```

流水线结果：

```text
Intent:
record_retrieval_query.related_record_query

Business Slots:
query_object = [service, tunnel]
relationship_scope = [service_uses_tunnel]
attribute_set = [name, latency]
query_action = [list]

Linked Semantics:
service -> Service as s
tunnel -> Tunnel as t
service_uses_tunnel -> (s)-[:SERVICE_USES_TUNNEL]->(t)
service_qos -> s.quality_of_service
tunnel_name -> t.name
tunnel_latency -> t.latency

SemanticQuerySpec:
record_selection over service/tunnel with service_uses_tunnel, filter s.quality_of_service = Gold, return t.name and t.latency

Cypher:
MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)
WHERE s.quality_of_service = 'Gold'
RETURN t.name AS tunnel_name, t.latency AS tunnel_latency
```

## 5. 失败分支

流水线不是所有问题都会生成 Cypher。常见停止点如下：

- 语义资产未对齐：返回 `semantic_contract_unaligned`。
- Intent 未接受：返回 `intent_not_accepted`。
- 业务槽位缺失：返回 `missing_required_business_slot`，并给出澄清问题。
- Semantic linking 无法绑定：linked semantics 为空或不完整。
- Semantic validation 失败：返回关系缺失、属性不存在、实体缺失等诊断。
- Renderer 不支持：进入受控 LLM fallback。
- LLM 输出不可解析：返回 parser failure reason。
- Preflight 失败：返回安全或语义级 failure reason。

这种分阶段失败设计让问题可以定位到具体环节，而不是只看到“Cypher 生成失败”。

## 6. 设计边界

### 6.1 Semantic layer 是生成契约

TuGraph schema 是物理事实源，知识是业务解释源，Semantic Layer 是两者对齐后的生成契约。实体、关系、属性、指标和值映射必须来自 Semantic Layer。Prompt、RAG 和 few-shot 只能补充上下文，不能创建新的 schema 权威。

### 6.2 DSL/IR 是生成边界

`SemanticQuerySpec` 是 Cypher 生成的边界。Renderer 和 LLM fallback 都只能消费它，不能绕过它直接根据原始自然语言拼 schema。

### 6.3 LLM 是受控 fallback

LLM 用于 renderer 不覆盖的复杂结构，而不是默认生成器。LLM 输出必须经过 parser、只读 preflight 和语义级 preflight。

### 6.4 图查询需要路径语义

传统 ChatBI 主要处理 table、join、measure、dimension。NL2Cypher 还需要处理 edge direction、path pattern、hop count、reachable、subgraph 等图结构语义。这些能力应进入 semantic layer 和 `SemanticQuerySpec`，而不是散落在 prompt 中。

## 7. 总结

这条流水线把自然语言到 Cypher 拆成一组可解释的编译阶段：

```text
intent-driven semantic parsing
  + business slot completeness
  + governed graph semantic layer
  + validated SemanticQuerySpec
  + controlled Cypher generation
  + semantic preflight
```

它的核心价值是降低 LLM 自由生成的不确定性，把生成质量建立在结构化语义、可验证 DSL 和可回放诊断之上。
