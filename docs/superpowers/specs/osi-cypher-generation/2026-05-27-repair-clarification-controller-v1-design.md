# Repair and Clarification Controller v1 设计

> 日期：2026-05-27
> 状态：设计 v1
> 上游：Semantic Validator、Execution Feedback Analyzer
> 下游：Grounded LLM Understanding、用户澄清、失败输出

## 1. 设计目标

Repair and Clarification Controller 决定当语义理解、绑定、校验或执行反馈出现问题时，系统是静默回灌 LLM 修复、反问用户、返回不支持，还是终止生成。

Question Decomposer 之前或之内的输入不清晰问题不由本 Controller 处理。该类问题由总体架构中的 Input Clarification Gate 负责：

- 问题缺少指代对象或没有可解析 substantive term 时，直接返回 `clarification_required`。
- Question Decomposer 连续 schema violation 且输入本身含糊时，由 Input Clarification Gate 构造澄清问题。
- 输入正常但 Decomposer LLM 连续输出非法结构时，返回 `generation_failed`，reason 为 `question_decomposer_schema_invalid`。

目标：

- 用户不应承担 LLM 可自行修复的类型错误。
- 用户必须看到会改变语义的问题，例如歧义、覆盖缺失、字面值无法解析。
- repair loop 有最大轮次和震荡检测，避免在两个错误状态之间来回切换。
- DSL 不支持时不绕过 DSL 安全边界。

## 2. 输入输出契约

输入：

```json
{
  "schema_version": "repair_controller_input_v1",
  "trace_id": "q-20260527-001",
  "question": "Gold 级别的服务都用了哪些 MPLS-TE 隧道",
  "attempt_no": 1,
  "selected_bindings": {},
  "validator_errors": [
    {
      "code": "relationship_endpoint_mismatch",
      "severity": "error",
      "repairable": true,
      "message": "service_uses_tunnel cannot connect service to network_element"
    }
  ],
  "history": []
}
```

输出类型：

```json
{
  "schema_version": "repair_controller_decision_v1",
  "decision": "repair_with_llm | ask_user | unsupported | generation_failed | continue_with_assumption",
  "reason_code": "relationship_endpoint_mismatch",
  "repair_prompt_delta": {},
  "clarification": null,
  "assumptions": [],
  "user_visible_notices": [],
  "stop_reason": null
}
```

## 3. 决策矩阵

| 问题 | 默认决策 | 说明 |
| --- | --- | --- |
| 关系端点类型错误 | `repair_with_llm` | 给 LLM 错误和合法候选，让其重选 |
| 边方向错误 | `repair_with_llm` | 编译器不猜方向 |
| metric/dimension 误用 | `repair_with_llm` | 用户通常不知道内部类型 |
| fuzzy 高置信首选 | `continue_with_assumption` | trace 记录 assumption，并必须返回用户可见 notice |
| 多候选接近 | `ask_user` | 最多给 3 个候选 |
| substantive term 未覆盖 | `ask_user` 或 `generation_failed` | 不允许静默丢词 |
| time term 未解析 | `ask_user` | 相对时间需要明确范围 |
| modality term 未落地 | `continue_with_assumption` | 作为 warning-only |
| 字面值 unresolved | `ask_user` | 使用 LiteralResolver alternatives |
| DSL 不支持 | `unsupported` | 给可改写建议；不走 raw Cypher |
| 编译后 shape mismatch | `generation_failed` | 视为 compiler bug，严重告警 |
| TuGraph runtime schema error | `generation_failed` | 表示 semantic registry 或 compiler 有缺陷 |

## 4. Repair Loop

配置：

```yaml
repair_controller:
  max_repair_attempts: 3
  stop_if_same_error_repeats: true
  stop_if_binding_oscillates: true
```

循环流程：

1. Semantic Validator 返回错误列表。
2. Controller 按最高 severity 和产品策略选择 repair 或 clarification。
3. 若 decision 为 `repair_with_llm`，构造最小 repair prompt：
   - 原始问题。
   - 当前结构化理解。
   - 校验错误。
   - 可选合法候选。
   - 明确禁止发明候选。
4. LLM 重新输出结构化理解。
5. Semantic Binder 和 Validator 重新执行。
6. 若通过，继续 DSL。
7. 若失败，记录历史状态和错误原因。
8. 达到上限、重复错误或状态震荡时停止，转为 ask_user、unsupported 或 generation_failed。

## 5. 状态指纹与震荡检测

每一轮 repair 后记录 canonical state fingerprint。

状态指纹有两个来源：

- repair loop 中优先使用 Semantic Binding 指纹，因为此时 DSL 可能尚未生成。
- DSL Builder 之后使用 Normalized DSL 指纹，作为 compiler 和 execution feedback 的状态依据。

两种来源必须归一到同一个 canonical state schema：

```json
{
  "query_shape": "two_step_aggregate",
  "bindings": [],
  "filters": [],
  "relationships": [],
  "path_patterns": [],
  "projections": [],
  "groups": [],
  "measures": [],
  "sorts": [],
  "limits": [],
  "subqueries": []
}
```

### 5.1 指纹字段与 DSL/绑定的映射

| canonical 字段 | Semantic Binding 来源 | Restricted DSL 来源 |
| --- | --- | --- |
| `query_shape` | `binding.query_shape` | `query_shape` |
| `bindings[]` | `selected_bindings[*].semantic_type/semantic_id/role` | `bindings.*.semantic_type/semantic_id`，key 作为 role |
| `filters[]` | `filters[*].target/field/operator/value.normalized` | 顶层 `filters[]`、`operations[].filters[]`、`operations[].through.filters[]`、`filter_subquery.predicate` |
| `relationships[]` | `relationship_paths[*].relationship_id/direction/min_hops/max_hops` | `traverse.relationship/direction`、`variable_path.allowed_relationships/min_hops/max_hops` |
| `path_patterns[]` | `selected_path_pattern.pattern_id` | `operations[op=use_path_pattern].pattern_id` |
| `projections[]` | `projection_items[*].semantic_id/source/alias/target` | `projection.items[].field.semantic_id` 或 `projection.items[].source`；同时保留 alias 和 target role |
| `groups[]` | `group_by[*].target/field.semantic_id/alias` | `operations[op=aggregate].group_by[]` 和 `operations[op=subquery].group_by[]` |
| `measures[]` | `measures[*].alias/function/target/field.semantic_id/metric_id` | `operations[op=aggregate].measures[]` 和 `operations[op=subquery].measures[]` |
| `sorts[]` | `sorts[*].source/direction` | `operations[op=sort].by[]` 和顶层 `order_by[]` |
| `limits[]` | `limit.value` | `operations[op=limit].value` 和顶层 `limit` |
| `subqueries[]` | `subqueries[*]` | `operations[op=subquery]` 的递归指纹 |

### 5.2 两步聚合与子查询指纹

`two_step_aggregate` 必须递归生成子查询指纹：

```json
{
  "query_shape": "two_step_aggregate",
  "subqueries": [
    {
      "bind_as": "device_port_counts",
      "fingerprint_payload": {
        "query_shape": "aggregate_group_by",
        "groups": [
          {
            "target": "device",
            "field": "network_element.id"
          }
        ],
        "measures": [
          {
            "alias": "port_count",
            "function": "count",
            "target": "port",
            "field": "port.id"
          }
        ]
      }
    }
  ],
  "filters": [
    {
      "target": "device_port_counts",
      "field": "port_count",
      "operator": "gt",
      "value": 10
    }
  ],
  "sorts": [
    {
      "source": "device_port_counts.port_count",
      "direction": "desc"
    }
  ],
  "limits": [
    {
      "value": 5
    }
  ]
}
```

子查询指纹规则：

- 子查询 `bind_as` 进入父指纹。
- 子查询内部按同一 canonical state schema 递归规范化。
- 子查询内 confidence、reason、原始 LLM 文本不进入指纹。
- 两个子查询如果 `bind_as` 不同但语义引用相同，v1 判定为不同状态，避免错误合并。

进入状态指纹的语义字段：

- `query_shape`
- `selected_bindings[*].semantic_type`
- `selected_bindings[*].semantic_id`
- `selected_bindings[*].role`
- `filters[*].target`
- `filters[*].field.semantic_id`
- `filters[*].operator`
- `filters[*].value.normalized`
- `relationship_paths[*].relationship_id`
- `relationship_paths[*].direction`
- `relationship_paths[*].min_hops`
- `relationship_paths[*].max_hops`
- `operations[op=use_path_pattern].pattern_id`
- `projection.items[*].field.semantic_id`
- `projection.items[*].source`
- `operations[op=aggregate].group_by[*].field.semantic_id`
- `operations[op=aggregate].measures[*].function`
- `operations[op=aggregate].measures[*].field.semantic_id`
- `operations[op=subquery]` 的递归 canonical payload
- `operations[op=sort].by[*].source/direction`
- `operations[op=limit].value`

不进入状态指纹的字段：

- confidence 数值。
- reason 文本。
- LLM 原始输出文本。
- candidate 返回顺序。
- duration、token usage。
- trace stage id。

canonicalization：

- 对对象 key 做稳定排序。
- 对集合类绑定按 `(semantic_type, semantic_id, role)` 排序。
- 对 filter 按 `(target, field, operator, value)` 排序。
- 删除空字段和 null 字段。
- 生成 sorted JSON 后取 sha256。

震荡定义：

- 新 fingerprint 与历史任一轮 fingerprint 相同，即判定 oscillation。
- v1 使用集合相等的简单判定，不做复杂语义等价。
- confidence 变化不会解除震荡判定。

处理：

- 若 oscillation 出现在 repairable 类型错误上，停止 repair，返回 `generation_failed`，reason 为 `repair_binding_oscillation`。
- 若 oscillation 涉及歧义候选，在还有 alternatives 时改为 `ask_user`。

## 6. Continue With Assumption 的用户可见性

`continue_with_assumption` 不能只写 trace。Controller 必须输出 `user_visible_notices`，由 API 响应和 runtime console 展示。

示例：

```json
{
  "decision": "continue_with_assumption",
  "reason_code": "high_confidence_fuzzy_literal",
  "assumptions": [
    {
      "kind": "literal_binding",
      "raw": "gold",
      "assumed_as": "GOLD",
      "confidence": 0.87,
      "field": "service.quality_of_service"
    }
  ],
  "user_visible_notices": [
    "我把“gold”理解为服务质量等级 GOLD。"
  ]
}
```

规则：

- 每个会影响查询语义的 assumption 必须有用户可见 notice。
- notice 由 Repair Controller 基于结构化 assumption 模板生成，不由自由文本 LLM 生成。
- warning-only modality 也应生成 notice，例如“问题中的‘应该’没有被解释为查询约束”。
- notice 不阻塞查询，但必须随结果返回。

## 7. Clarification 输出

澄清问题必须短、可回答、带选项：

```json
{
  "source_stage": "semantic_validator",
  "reason_code": "ambiguous_semantic_binding",
  "question_zh": "你说的“隧道”是指业务隧道还是物理链路隧道？",
  "expected_answer_type": "single_choice",
  "options": [
    {
      "id": "business_tunnel",
      "label": "业务隧道",
      "semantic_id": "tunnel",
      "confidence": 0.77
    },
    {
      "id": "link_tunnel",
      "label": "物理链路隧道",
      "semantic_id": "link_tunnel",
      "confidence": 0.74
    }
  ]
}
```

规则：

- 单轮最多问一个关键问题。
- 选项最多 3 个。
- 不向用户暴露内部错误栈。
- 对覆盖缺失必须说明哪个词没有被使用，例如“问题中的‘增长’没有在当前语义模型中找到对应指标”。

## 8. DSL 不支持的降级策略

采用 A + C：

- A：直接返回 `unsupported_query_shape`，说明系统 v1 不支持该查询形态。
- C：如果能拆成多个支持查询，给用户改写建议。

不采用 B：

- 不允许 fallback 到 LLM 直接生成 Cypher。
- 不允许低信任 raw Cypher 路径。
- 不允许在 DSL 中加入 escape hatch。

示例：

```json
{
  "decision": "unsupported",
  "reason_code": "graph_algorithm_not_supported",
  "message_zh": "当前语义生成链路暂不支持最短路径类图算法查询。",
  "suggested_rewrites": [
    "可以先查询两个设备之间已注册路径模板中的可达路径。",
    "可以查询经过指定设备的隧道列表。"
  ]
}
```

## 9. 执行反馈接入

Execution Feedback Analyzer 可把运行异常回灌给 Controller。

| 执行反馈 | 决策 |
| --- | --- |
| 空结果 + low-confidence literal | 反问用户，使用 LiteralResolver alternatives |
| 空结果 + high-confidence exact | 正常返回空结果，并说明没有匹配数据 |
| 结果过大 | 按动态阈值判断，反问用户是否增加过滤或 limit |
| 返回列与 plan 不一致 | `generation_failed`，reason 为 `compiler_shape_mismatch` |
| TuGraph runtime syntax error | `generation_failed`，reason 为 `target_dialect_compile_error` |
| timeout | 反问是否缩小路径范围、增加过滤或 limit |

“自动重试”只能回到明确的上游层：

- 字面值低置信：回 LiteralResolver/Clarification。
- 类型绑定错误：回 Grounded LLM Understanding。
- 编译器 shape mismatch：不重试，工程告警。
- timeout 或结果过大：不让 LLM 猜，反问用户收窄范围。

## 10. 配置

```yaml
repair_controller:
  max_repair_attempts: 3
  ambiguous_top2_gap_threshold: 0.10
  max_clarification_options: 3
  default_result_row_limit: 1000
  large_result_threshold_policy:
    fallback_rows: 50000
    aggregate_group_by_rows: 5000
    explicit_limit_multiplier: 5
    max_threshold_rows: 100000
  timeout_seconds: 30
```

结果过大阈值不能是单一常量。v1 采用动态策略：

- `top_n` 且有显式 limit 时，不触发结果过大反问，除非实际行数超过 `limit * explicit_limit_multiplier`。
- `aggregate_group_by` 默认阈值较低，因为聚合结果通常应可浏览。
- `entity_lookup`、`single_hop_traversal`、`variable_path_traversal`、`named_path_pattern` 使用 `fallback_rows`，并可按 target dataset 规模或 query profile 调整。
- 核心网络节点、端口、链路等高基数字段必须通过真实查询样本 benchmark 后确定生产阈值。
- 超过 `max_threshold_rows` 一律要求用户收窄范围，避免误触发超大结果导出。

## 11. 测试要求

v1 实现时至少覆盖：

- 关系端点错误 repair 成功。
- repair 3 次仍失败后终止。
- A -> B -> A 绑定震荡被 fingerprint 捕获。
- 多候选接近时反问用户。
- substantive term 未覆盖时不生成 DSL。
- DSL 不支持时不出现 raw Cypher fallback。
- compiler shape mismatch 标为严重失败，不自动重试。
- two_step_aggregate 的子查询递归指纹能区分 measure、filter_subquery、sort、limit 的实质变化。
- continue_with_assumption 必须输出用户可见 notice。
