# Observability v1 设计

> 日期：2026-05-27
> 状态：设计 v1
> 覆盖范围：cypher-generator-agent 的 OSI 语义生成链路

## 1. 设计目标

这套架构的核心优势是“出错可定位”。Observability v1 让每次查询都产出完整 trace，覆盖从自然语言拆解到候选召回、字面值解析、LLM 绑定、校验、DSL、编译、执行反馈的全过程。

目标：

- 能回答“为什么生成了这个 Cypher”。
- 能回答“失败发生在哪一层”。
- 能复盘 repair loop 为什么停止。
- 能定位性能瓶颈。
- 能支持 testing-agent 和 runtime console 展示生成证据。

非目标：

- v1 不做分布式链路追踪系统替代品。
- v1 不记录敏感凭据、数据库连接串或完整大结果集。
- v1 不把 trace 作为业务事实来源。

## 2. Trace 顶层结构

```yaml
trace_schema_version: cga_osi_trace_v1
trace_id: q-20260527-001
question_id: qa-001
generation_run_id: cypher-run-001
source_question: "Gold 级别的服务都用了哪些 MPLS-TE 隧道？"
started_at: "2026-05-27T10:00:00+08:00"
finished_at: "2026-05-27T10:00:02+08:00"
final_status: generated
semantic_model:
  model_id: osi-network-model
  version: "0.2.0.dev0"
  checksum: sha256:abc123
stages: []
final_outputs:
  dsl: {}
  cypher: "MATCH ..."
  clarification: null
  user_visible_notices: []
  failure: null
```

`final_status` 取值：

- `generated`
- `clarification_required`
- `unsupported_query_shape`
- `generation_failed`
- `service_failed`

## 3. Stage 结构

每个 stage 必须包含：

```yaml
stage: literal_resolver
status: success
started_at: "2026-05-27T10:00:00.300+08:00"
duration_ms: 42
input_ref: inline_or_redacted
output_ref: inline_or_artifact
metrics: {}
errors: []
warnings: []
```

字段规则：

| 字段 | 含义 |
| --- | --- |
| `stage` | 固定枚举，便于查询和统计 |
| `status` | `success`、`warning`、`failed`、`skipped` |
| `duration_ms` | 当前 stage 耗时 |
| `input_ref` | 小输入可 inline，大输入存 artifact 引用 |
| `output_ref` | 小输出可 inline，大输出存 artifact 引用 |
| `metrics` | stage 专用指标 |
| `errors` | 错误码、严重级别、消息 |
| `warnings` | assumption、低置信、覆盖 warning |

## 4. 必须记录的 stages

| stage | 关键内容 |
| --- | --- |
| `input_clarification_gate` | 原始问题是否缺少指代对象、Decomposer schema 失败后的澄清决策 |
| `question_decomposer` | 结构化拆解、substantive/stopword/modality/time/unparsed 分类、LLM 调用次数 |
| `candidate_retrieval` | 每类候选数量、match_type、score、evidence |
| `literal_resolver` | 每个 literal 的解析结果、alternatives、cache/live lookup 信号 |
| `grounded_understanding` | LLM 结构化输出、schema 校验结果、候选选择 |
| `semantic_binder` | selected_bindings、normalized filters、relationship paths |
| `semantic_validator` | errors、warnings、coverage report |
| `repair_controller` | decision、attempt_no、fingerprint、oscillation、clarification |
| `dsl_builder` | query_shape、DSL 输出、unsupported reason |
| `dsl_parser` | JSON Schema 校验、AST 规范化 |
| `cypher_compiler` | compiler template、输出 Cypher、target dialect |
| `cypher_validation` | parser 结果、read-only check、schema-aware check |
| `execution` | rows_returned、duration、timeout、runtime error |
| `feedback_analyzer` | 空结果/过大/shape mismatch 等后处理 |

## 5. Stage 示例

```yaml
- stage: literal_resolver
  status: success
  duration_ms: 38
  metrics:
    items_total: 2
    items_resolved: 2
    cache_hits: 1
    live_lookup_count: 0
    live_lookup_rate_limited_count: 0
  output_ref:
    type: inline
    value:
      results:
        - raw_literal: Gold
          expected_field: service.quality_of_service
          resolved_value: GOLD
          match_type: synonym
          confidence: 0.98
          alternatives: []
        - raw_literal: MPLS-TE
          expected_field: tunnel.type
          resolved_value: MPLS_TE
          match_type: exact
          confidence: 1.0
          alternatives: []
  errors: []
  warnings: []
```

Repair stage 示例：

```yaml
- stage: repair_controller
  status: warning
  duration_ms: 5
  metrics:
    attempt_no: 2
    max_attempts: 3
    historical_fingerprints: 2
  output_ref:
    type: inline
    value:
      decision: ask_user
      reason_code: ambiguous_semantic_binding
      fingerprint: sha256:def456
      oscillation_detected: false
      clarification:
        expected_answer_type: single_choice
        options_count: 2
      user_visible_notices: []
  errors: []
  warnings:
    - code: repair_limit_near
      message: "Repair attempt 2 of 3"
```

## 6. 覆盖报告

Semantic Validator 必须写入 coverage report：

```yaml
coverage:
  substantive_terms:
    total: 4
    covered: 4
    uncovered: []
  stopword_terms:
    ignored: ["麻烦", "帮我", "查一下"]
  modality_terms:
    warning_only: ["应该"]
  time_terms:
    covered: ["最近"]
    unresolved: []
  unparsed_terms:
    unresolved: []
```

规则：

- `substantive_terms.uncovered` 非空时不得生成 Cypher。
- `stopword_terms` 只记录，不触发失败。
- `modality_terms` 可以 warning-only，但必须出现在 trace 中。
- `unparsed_terms` 非空时必须进入 clarification 或 generation_failed。

## 7. 指标与告警

核心指标：

- `cga_osi_generation_success_count`
- `cga_osi_clarification_required_count`
- `cga_osi_unsupported_query_shape_count`
- `cga_osi_generation_failed_count`
- `cga_osi_stage_duration_ms`
- `cga_osi_llm_call_count`
- `cga_osi_repair_attempt_count`
- `cga_osi_repair_oscillation_count`
- `cga_osi_literal_cache_hit_rate`
- `cga_osi_literal_live_lookup_hit_rate`
- `cga_osi_literal_live_lookup_rate_limited_count`
- `cga_osi_literal_live_lookup_singleflight_join_count`
- `cga_osi_coverage_failure_count`
- `cga_osi_input_clarification_required_count`
- `cga_osi_assumption_notice_count`
- `cga_osi_compiler_shape_mismatch_count`

严重告警：

- compiler shape mismatch。
- DSL Parser 通过但 compiler 输出无法通过 read-only/syntax 校验。
- schema registry 引用不存在。
- repair oscillation 频繁发生。
- literal cache stale suspected 突增。
- live lookup rate limited 突增。
- coverage failure 在某类问题上持续上升。

## 8. 隐私与截断

trace 可进入 testing-agent 和 runtime console，因此需要截断策略：

- 不记录数据库凭据。
- 不记录完整大结果集，只记录行数、列名和最多 5 行 sample。
- LLM prompt 可记录，但候选列表超过阈值时用 artifact 引用。
- 用户问题原文保留，因为它是生成审计必要上下文。
- Cypher 保留，因为它是评测与复盘必要输出。

## 9. 与 testing-agent 的契约

生成成功时，`input_prompt_snapshot` 使用 `cga_osi_trace_v1` 的 JSON string。

非成功输出也必须提交 trace：

- `clarification_required`：保留 clarification、coverage、候选歧义证据。
- `clarification_required` 也覆盖 input clarification，例如问题缺少指代对象或 Decomposer 无法产出有效结构。
- `unsupported_query_shape`：保留 unsupported reason 和 suggested rewrites。
- `generation_failed`：保留 validator/compiler/execution 错误和最后可用 DSL/Cypher。
- `service_failed`：保留工程异常，但不构造正式评测 attempt。

testing-agent 不重新解释 trace，只负责保存、关联 attempt，并展示给 runtime console 或 repair-agent。

## 10. 查询排障视图

runtime console 至少应能展示：

- 总耗时和每个 stage 耗时。
- LLM 调用次数和 schema violation 次数。
- 候选召回 top results。
- LiteralResolver 的 resolved/unresolved/alternatives。
- 覆盖报告。
- repair loop 历史、fingerprint 和停止原因。
- 用户可见 assumption notices。
- DSL、AST 摘要、Cypher。
- 执行结果摘要和反馈分类。

这样用户或开发者可以回答：

- 是问题拆解错了，还是语义召回错了？
- 是字面值不存在，还是缓存陈旧？
- 是 DSL 不支持，还是 compiler bug？
- 是数据确实为空，还是解析错了？
