# Repair and Clarification Controller v1 设计

> 日期：2026-05-27
> 状态：设计 v1
> 上游：Semantic Validator、Execution Feedback Analyzer
> 下游：Grounded LLM Understanding、用户澄清、失败输出

## 1. 设计目标

Repair and Clarification Controller 决定当语义理解、绑定、校验或执行反馈出现问题时，系统是静默回灌 LLM 修复、反问用户、返回不支持，还是终止生成。

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
  "stop_reason": null
}
```

## 3. 决策矩阵

| 问题 | 默认决策 | 说明 |
| --- | --- | --- |
| 关系端点类型错误 | `repair_with_llm` | 给 LLM 错误和合法候选，让其重选 |
| 边方向错误 | `repair_with_llm` | 编译器不猜方向 |
| metric/dimension 误用 | `repair_with_llm` | 用户通常不知道内部类型 |
| fuzzy 高置信首选 | `continue_with_assumption` | trace 记录 assumption，结果解释可提示 |
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

进入状态指纹的字段：

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
- `path_pattern_id`
- `projection[*].semantic_id`
- `aggregation[*].function`
- `aggregation[*].field.semantic_id`

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

## 6. Clarification 输出

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

## 7. DSL 不支持的降级策略

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

## 8. 执行反馈接入

Execution Feedback Analyzer 可把运行异常回灌给 Controller。

| 执行反馈 | 决策 |
| --- | --- |
| 空结果 + low-confidence literal | 反问用户，使用 LiteralResolver alternatives |
| 空结果 + high-confidence exact | 正常返回空结果，并说明没有匹配数据 |
| 结果过大 | 反问用户是否增加过滤或 limit |
| 返回列与 plan 不一致 | `generation_failed`，reason 为 `compiler_shape_mismatch` |
| TuGraph runtime syntax error | `generation_failed`，reason 为 `target_dialect_compile_error` |
| timeout | 反问是否缩小路径范围、增加过滤或 limit |

“自动重试”只能回到明确的上游层：

- 字面值低置信：回 LiteralResolver/Clarification。
- 类型绑定错误：回 Grounded LLM Understanding。
- 编译器 shape mismatch：不重试，工程告警。
- timeout 或结果过大：不让 LLM 猜，反问用户收窄范围。

## 9. 配置

```yaml
repair_controller:
  max_repair_attempts: 3
  ambiguous_top2_gap_threshold: 0.10
  max_clarification_options: 3
  default_result_row_limit: 1000
  large_result_threshold_rows: 5000
  timeout_seconds: 30
```

`large_result_threshold_rows` 必须可配置。不同图规模和业务场景不能共用固定阈值。

## 10. 测试要求

v1 实现时至少覆盖：

- 关系端点错误 repair 成功。
- repair 3 次仍失败后终止。
- A -> B -> A 绑定震荡被 fingerprint 捕获。
- 多候选接近时反问用户。
- substantive term 未覆盖时不生成 DSL。
- DSL 不支持时不出现 raw Cypher fallback。
- compiler shape mismatch 标为严重失败，不自动重试。
