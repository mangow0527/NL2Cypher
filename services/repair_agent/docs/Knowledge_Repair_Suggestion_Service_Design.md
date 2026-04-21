# Knowledge Repair Suggestion Service 架构与契约设计

## 1. 定位

Knowledge Repair Suggestion Service（KRSS，知识修复建议服务）是 Text2Cypher 闭环中的知识诊断与知识修复建议服务。它接收 Testing Service 产出的失败问题单，基于失败样本、评测证据和生成证据判断知识缺口，并把结构化的知识修复建议投递给 Knowledge Ops。

一句话边界：

```text
Testing Service 证明“这次生成哪里错了”；
KRSS 判断“为什么错、该修哪类知识”。
```

KRSS 不负责执行 Cypher，不重新调用 CGS，不重新评测业务正确性，也不直接编辑 prompt 或知识文件。它只负责把一次失败事件转成可追踪、可投递的 `KnowledgeRepairSuggestionRequest`。

当前实现主线：

- LLM-first diagnosis：优先由强模型基于失败证据做根因归因。
- Prompt evidence from IssueTicket：prompt 快照来自 Testing Service 的失败事件快照，而不是 KRSS 回查 CGS。
- Lightweight validation：在 LLM 要求验证时，执行类型级启发式筛选。
- Knowledge Ops apply on success：只有 Knowledge Ops apply 成功后，KRSS 写接口才返回 `applied`。
- Analysis record idempotency by ticket：按 `ticket_id` 保存并复用分析记录。

## 2. 术语与核心数据结构

本章定义 KRSS 文档中反复出现的业务术语和数据结构。后续流程、接口和责任边界都以这些对象为基础。

### 2.1 `IssueTicket`

`IssueTicket` 是 Testing Service 提交给 KRSS 的失败问题单。它只在 Testing Service 对某次 submission 的最终评测结论不是 `pass` 时生成。

它包含：

| 字段 | 含义 |
| --- | --- |
| `ticket_id` | 问题单唯一 ID，当前格式通常为 `ticket-{id}-attempt-{attempt_no}` |
| `id` | QA 样本主键 |
| `difficulty` | 题目难度，取值为 `L1` 到 `L8` |
| `question` | 原始自然语言问题 |
| `expected` | 黄金 Cypher 与黄金答案 |
| `actual` | CGS 生成 Cypher 与 Testing Service 实际执行结果 |
| `evaluation` | Testing Service 生成的评测结论 |
| `generation_evidence` | CGS 生成过程证据，由 Testing Service 从 submission 中复制到问题单 |
| `diagnostic_summary` | Testing Service 生成的失败现象诊断合同，包含失败类别、严重度、维度信号、结构差异、诊断标签和证据摘要 |
| `input_prompt_snapshot` | prompt 快照兼容字段。新流程优先使用 `generation_evidence.input_prompt_snapshot` |

它的意义是：把一次失败事件中 KRSS 需要的事实都固定下来。KRSS 不再为了补齐 prompt 或生成证据回头查询 CGS。

### 2.2 `GenerationEvidence`

`GenerationEvidence` 表示 CGS 生成阶段留下的过程证据。它的来源是 CGS 提交给 Testing Service 的 `EvaluationSubmissionRequest`，Testing Service 只负责保存、关联 attempt，并写入 `IssueTicket`。

它包含：

| 字段 | 含义 |
| --- | --- |
| `generation_run_id` | CGS 本次生成运行 ID，用于串联 CGS 日志和问题单 |
| `attempt_no` | Testing Service 记录的尝试序号 |
| `parse_summary` | CGS 如何从模型输出得到 `generated_cypher` |
| `guardrail_summary` | CGS 最小守门结果 |
| `raw_output_snapshot` | LLM 原始输出快照 |
| `input_prompt_snapshot` | CGS 本轮生成实际使用的 prompt 快照 |

它和 `evaluation` 的区别是：

- `generation_evidence` 描述“CGS 当时如何生成”。
- `evaluation` 描述“Testing Service 观察到哪里失败”。
- KRSS 同时消费二者，用于区分 prompt 知识缺口、few-shot 缺失、输出解析偏差、守门不足和图谱语义错误。

### 2.3 `DiagnosisContext`

`DiagnosisContext` 是 KRSS 内部传给 LLM 诊断客户端的结构化上下文。它不是外部 API 契约，而是把 `IssueTicket` 和 prompt evidence 压缩成更适合根因分析的材料。

它主要包含：

| 字段 | 含义 |
| --- | --- |
| `question` | 原始自然语言问题 |
| `difficulty` | 题目难度 |
| `sql_pair` | `expected_cypher` 与 `actual_cypher` |
| `evaluation_summary` | verdict、dimensions、symptom 和 evidence 摘要 |
| `diagnostic_summary` | Testing Service 已整理的失败现象诊断合同 |
| `failure_diff` | 优先来自 `diagnostic_summary.failure_diff`；历史问题单缺失时由 KRSS 兼容派生 |
| `prompt_evidence` | 压缩后的完整 prompt 证据 |
| `generation_evidence` | 压缩后的生成过程证据 |
| `relevant_prompt_fragments` | 从 prompt 中抽取的 system、business、few-shot、repair 片段 |
| `recent_applied_repairs` | 最近已应用修复，当前主流程默认为空 |

它的意义是：让 LLM 不需要理解完整服务调用链，也能看到根因分析所需的核心证据。

### 2.4 `failure_diff`

`failure_diff` 是 expected、actual 和 evaluation 的轻量结构化对比。新流程中它优先由 Testing Service 放在 `diagnostic_summary.failure_diff` 中传入；KRSS 只在历史问题单没有 `diagnostic_summary` 时进行兼容派生。

它包含：

| 字段 | 含义 |
| --- | --- |
| `ordering_problem` | golden 要求排序但 actual 缺失或不一致 |
| `limit_problem` | golden 要求 limit 但 actual 缺失或数量不一致 |
| `return_shape_problem` | RETURN 结构不一致 |
| `entity_or_relation_problem` | 实体或关系路径疑似不一致 |
| `execution_problem` | TuGraph 执行失败或返回错误信息 |
| `syntax_problem` | Testing Service 判定语法维度失败 |
| `missing_or_wrong_clauses` | 以上问题的摘要列表 |
| `semantic_mismatch_summary` | evaluation symptom 或 evidence 摘要 |

它的意义是：给 LLM 和 lightweight validation 一个稳定的失败现象骨架。它不是最终根因结论。

### 2.5 `prompt_evidence` 与 `relevant_prompt_fragments`

KRSS 同时保留两类 prompt 证据：

| 字段 | 来源 | 作用 |
| --- | --- | --- |
| `prompt_evidence` | `generation_evidence.input_prompt_snapshot` 或兼容字段 `input_prompt_snapshot` | 压缩后的完整 prompt 证据，保证中文和结构化 prompt 不会被抽空 |
| `relevant_prompt_fragments` | 从 prompt 中按关键词抽取的片段 | 辅助判断 prompt 中是否已有 system rule、business knowledge、few-shot 或 repair 信息 |

`relevant_prompt_fragments` 只是辅助字段。KRSS 不再只依赖英文关键词抽片段来判断知识是否缺失。

### 2.6 `KRSSAnalysisResult`

`KRSSAnalysisResult` 是 KRSS 内部分析器的输出。

它包含：

| 字段 | 含义 |
| --- | --- |
| `id` | QA 样本主键 |
| `suggestion` | 面向 Knowledge Ops 的修复建议文本 |
| `knowledge_types` | 本次建议涉及的知识类型 |
| `confidence` | 诊断置信度，范围 0 到 1 |
| `rationale` | LLM 给出的归因理由 |
| `used_experiments` | 是否执行 lightweight validation |
| `primary_knowledge_type` | LLM 诊断的主知识类型 |
| `secondary_knowledge_types` | 次要知识类型 |
| `candidate_patch_types` | LLM 建议验证的候选类型 |
| `validation_mode` | `disabled` 或 `lightweight` |
| `validation_result` | 验证通过/拒绝的类型与理由 |
| `diagnosis_context_summary` | 诊断上下文摘要，用于追踪与审计 |

它的意义是：把 LLM 诊断、可选验证和最终知识类型选择汇总成可保存、可投递的内部结果。

### 2.7 `KnowledgeRepairSuggestionRequest`

`KnowledgeRepairSuggestionRequest` 是 KRSS 投递给 Knowledge Ops 的正式出站契约。

它严格只有三个字段：

| 字段 | 含义 |
| --- | --- |
| `id` | QA 样本主键 |
| `suggestion` | 给 Knowledge Ops 的修复建议 |
| `knowledge_types` | 建议修复的知识类型 |

允许的知识类型只有：

```text
cypher_syntax
few_shot
system_prompt
business_knowledge
```

它的意义是：把 KRSS 内部诊断结果收敛成 Knowledge Ops 可以应用的最小修复请求。

### 2.8 `KRSSAnalysisRecord`

`KRSSAnalysisRecord` 是 KRSS 落盘保存的稳定分析记录。

它包含：

| 字段 | 含义 |
| --- | --- |
| `analysis_id` | 分析记录主键，当前为 `analysis-{ticket_id}` |
| `ticket_id` | Testing Service 失败问题单 ID |
| `id` | QA 样本主键 |
| `prompt_snapshot` | KRSS 实际用于诊断的 prompt 快照，来源于 IssueTicket |
| `knowledge_repair_request` | 已投递给 Knowledge Ops 的修复请求 |
| `knowledge_ops_response` | Knowledge Ops apply 响应 |
| `confidence` | 诊断置信度 |
| `rationale` | 根因说明 |
| `used_experiments` | 是否执行 lightweight validation |
| `primary_knowledge_type` | 主知识类型 |
| `secondary_knowledge_types` | 次要知识类型 |
| `candidate_patch_types` | 候选修复类型 |
| `validation_mode` | 验证模式 |
| `validation_result` | 验证结果 |
| `diagnosis_context_summary` | 诊断上下文摘要 |
| `created_at` | 记录创建时间 |
| `applied_at` | Knowledge Ops apply 成功时间 |

它的意义是：为幂等返回、审计、回放和控制台展示提供稳定事实。

## 3. 根因分析流程

### 3.1 总流程

KRSS 的根因分析从 `IssueTicket` 进入服务开始。

```text
IssueTicket
  -> 按 ticket_id 查询 KRSSAnalysisRecord
  -> 已存在：直接返回历史 applied 响应
  -> 不存在：从 IssueTicket 提取 prompt snapshot
  -> 构造 DiagnosisContext
  -> LLM-first diagnosis
  -> 可选 lightweight validation
  -> 生成 KRSSAnalysisResult
  -> 转换 KnowledgeRepairSuggestionRequest
  -> Knowledge Ops apply
  -> 保存 KRSSAnalysisRecord
  -> 返回 KRSSIssueTicketResponse
```

每一步的意义：

| 步骤 | 输入 | 输出 | 意义 |
| --- | --- | --- | --- |
| 幂等查询 | `ticket_id` | 已有记录或空 | 避免同一失败事件重复诊断和重复 apply |
| 提取 prompt | `IssueTicket.generation_evidence` | prompt snapshot | 使用 Testing Service 固化的失败事件快照作为事实源 |
| 构造上下文 | `IssueTicket` 与 prompt | `DiagnosisContext` | 将失败事实整理为 LLM 可消费材料 |
| LLM 诊断 | `DiagnosisContext` | diagnosis JSON | 判断知识类型、置信度、建议和是否需要验证 |
| 轻量验证 | candidate patch types | selected knowledge types | 对候选知识类型做启发式筛选 |
| 生成请求 | `KRSSAnalysisResult` | `KnowledgeRepairSuggestionRequest` | 收敛为 Knowledge Ops 出站契约 |
| apply | 修复请求 | Knowledge Ops 响应 | 投递正式修复建议 |
| 落盘 | 全链路结果 | `KRSSAnalysisRecord` | 支撑审计、回放和幂等 |

### 3.2 prompt snapshot 来源

KRSS 当前不向 CGS 拉取 prompt snapshot。

prompt snapshot 的来源优先级是：

```text
IssueTicket.generation_evidence.input_prompt_snapshot
  -> IssueTicket.input_prompt_snapshot
```

`generation_evidence` 是 Testing Service 从 CGS submission 中保存并写入问题单的生成证据。KRSS 使用它，是为了保证根因分析和失败评测使用同一 attempt 的事实快照。

当前服务对象中仍保留 `prompt_snapshot_client` 和 `cgs_base_url` 等兼容配置，但 `create_issue_ticket_response()` 主链路不调用 CGS prompt 查询接口。它们不再是 KRSS 根因分析的数据来源。

### 3.3 构造诊断上下文

KRSS 通过 `build_diagnosis_context(ticket, prompt_snapshot)` 构造 `DiagnosisContext`。

输入：

```text
IssueTicket
prompt_snapshot
recent_applied_repairs（当前主流程默认空）
```

输出：

```json
{
  "question": "...",
  "difficulty": "L3",
  "sql_pair": {
    "expected_cypher": "MATCH ...",
    "actual_cypher": "MATCH ..."
  },
  "evaluation_summary": {
    "verdict": "partial_fail",
    "dimensions": {
      "syntax_validity": "pass",
      "schema_alignment": "pass",
      "result_correctness": "fail",
      "question_alignment": "fail"
    },
    "symptom": "Wrong tunnel returned",
    "evidence_preview": ["result does not match expected tunnel"]
  },
  "diagnostic_summary": {
    "failure_classes": ["result_correctness", "query_intent_alignment"],
    "primary_failure_class": "query_intent_alignment",
    "severity": "high",
    "dimension_signals": {},
    "failure_diff": {
      "projection_mismatch": true,
      "limit_mismatch": false
    },
    "diagnostic_tags": ["projection_mismatch"],
    "evidence_preview": ["result does not match expected tunnel"]
  },
  "failure_diff": {
    "projection_mismatch": true,
    "limit_mismatch": false
  },
  "prompt_evidence": "压缩后的完整 prompt",
  "generation_evidence": {
    "generation_run_id": "gen-001",
    "attempt_no": 2,
    "parse_summary": "parsed_json",
    "guardrail_summary": "accepted",
    "raw_output_snapshot": "...",
    "input_prompt_snapshot": "压缩后的 prompt"
  },
  "relevant_prompt_fragments": {
    "system_rules_fragment": "...",
    "business_knowledge_fragment": "...",
    "few_shot_fragment": "...",
    "recent_repair_fragment": "..."
  },
  "recent_applied_repairs": []
}
```

### 3.4 LLM-first diagnosis

KRSS 将 `DiagnosisContext` 压缩后送入 `OpenAICompatibleKRSSAnalyzer`。

LLM 必须返回 JSON：

| 字段 | 含义 |
| --- | --- |
| `primary_knowledge_type` | 主知识类型 |
| `secondary_knowledge_types` | 次要知识类型 |
| `candidate_patch_types` | 需要验证的候选类型 |
| `confidence` | 置信度 |
| `suggestion` | 修复建议 |
| `rationale` | 诊断理由 |
| `need_validation` | 是否需要 lightweight validation |

如果 LLM 返回旧字段 `knowledge_types`，KRSS 会兼容地将第一个类型视为 primary，其余类型视为 secondary。

### 3.5 knowledge type 归一化

KRSS 不直接信任 LLM 输出的知识类型。

归一化规则：

- `primary_knowledge_type` 必须属于四个正式类型，否则回退为 `system_prompt`。
- `secondary_knowledge_types` 和 `candidate_patch_types` 中的非法类型会被丢弃。
- 重复类型会被去重。
- `confidence` 会被限制在 0 到 1 之间，非法或非有限值回退为 0。

这一步的意义是：保证出站到 Knowledge Ops 的 `knowledge_types` 不会被 LLM 幻觉污染。

### 3.6 lightweight validation

lightweight validation 是可选步骤。

触发条件：

```text
LLM 返回 need_validation = true
且 candidate_patch_types 非空
且 KRSSAnalyzer 配置了 experiment_runner
```

当前默认服务配置会注入 `_lightweight_experiment_runner`，因此 KRSS 具备执行 lightweight validation 的能力。

当前触发逻辑不由 `min_confidence_for_direct_return` 阈值决定。该配置仍存在于分析器构造参数中，但主流程实际只看 LLM 返回的 `need_validation`、候选类型和 `experiment_runner` 是否存在。

但当前 lightweight validation 不是重新生成或真实对照实验。它不做：

- 不重新调用 CGS。
- 不重新执行 TuGraph。
- 不向 Knowledge Ops 拉补丁包。
- 不验证知识修复后是否通过评测。

它当前做的是类型级启发式筛选：

| 判断项 | 含义 |
| --- | --- |
| `explanatory_power` | 候选知识类型是否能解释 `failure_diff` |
| `duplicate_repair` | 最近修复记录中是否已有同类修复 |
| `fragment_conflict` | 当前 prompt fragments 是否已经覆盖该类型 |

判定规则：

```text
improved = explanatory_power
           and not duplicate_repair
           and not fragment_conflict
```

如果有候选类型通过验证，KRSS 优先选择验证指标最高的类型；如果没有候选类型通过验证，则回退到 LLM 的 primary knowledge type。

### 3.7 生成知识修复建议

`KRSSAnalysisResult.to_request()` 会生成正式出站请求：

```json
{
  "id": "q-001",
  "suggestion": "Add a few-shot example that covers Service -> Tunnel traversal.",
  "knowledge_types": ["few_shot"]
}
```

该请求随后投递给 Knowledge Ops apply 接口。

## 4. 当前运行流程

### 4.1 步骤 1：接收失败问题单

接口：

```text
POST /api/v1/issue-tickets
```

输入结构：

```json
{
  "ticket_id": "ticket-q-001-attempt-2",
  "id": "q-001",
  "difficulty": "L3",
  "question": "查询协议版本对应的隧道",
  "expected": {
    "cypher": "MATCH ...",
    "answer": []
  },
  "actual": {
    "generated_cypher": "MATCH ...",
    "execution": {
      "success": true,
      "rows": [],
      "row_count": 0,
      "error_message": null,
      "elapsed_ms": 12
    }
  },
  "evaluation": {
    "verdict": "partial_fail",
    "dimensions": {
      "syntax_validity": "pass",
      "schema_alignment": "pass",
      "result_correctness": "fail",
      "question_alignment": "fail"
    },
    "symptom": "Wrong tunnel returned",
    "evidence": ["result does not match expected tunnel"]
  },
  "generation_evidence": {
    "generation_run_id": "gen-001",
    "attempt_no": 2,
    "parse_summary": "parsed_json",
    "guardrail_summary": "accepted",
    "raw_output_snapshot": "{\"cypher\":\"MATCH ...\"}",
    "input_prompt_snapshot": "..."
  },
  "input_prompt_snapshot": "..."
}
```

输出：

```json
{
  "status": "applied",
  "analysis_id": "analysis-ticket-q-001-attempt-2",
  "id": "q-001",
  "knowledge_repair_request": {
    "id": "q-001",
    "suggestion": "...",
    "knowledge_types": ["few_shot"]
  },
  "knowledge_ops_response": {
    "status": "ok"
  },
  "applied": true
}
```

### 4.2 步骤 2：幂等检查

KRSS 根据 `ticket_id` 派生：

```text
analysis_id = analysis-{ticket_id}
```

如果该记录已存在，KRSS 直接返回存量结果，不重新诊断，也不重复投递 Knowledge Ops。

### 4.3 步骤 3：诊断与建议

如果记录不存在，KRSS 执行：

```text
prompt snapshot from IssueTicket
  -> build DiagnosisContext
  -> LLM diagnosis
  -> optional lightweight validation
  -> KRSSAnalysisResult
  -> KnowledgeRepairSuggestionRequest
```

### 4.4 步骤 4：Knowledge Ops apply

接口：

```text
POST /api/knowledge/repairs/apply
```

出站 payload：

```json
{
  "id": "q-001",
  "suggestion": "...",
  "knowledge_types": ["business_knowledge", "few_shot"]
}
```

成功语义：

```text
只有 HTTP 200 视为 apply 成功。
```

transport error 与可重试非 200 响应会重试；4xx 直接终止。

### 4.5 步骤 5：保存分析记录

Knowledge Ops apply 成功后，KRSS 保存 `KRSSAnalysisRecord`。

默认路径：

```text
data/repair_service/analyses/<analysis_id>.json
```

只有保存记录后，KRSS 写接口才返回 `status = applied`。

## 5. API 与数据契约

### 5.1 写入口：提交 IssueTicket

```text
POST /api/v1/issue-tickets
```

请求体：

```text
IssueTicket
```

响应体：

```text
KRSSIssueTicketResponse
```

语义：

- 诊断成功、Knowledge Ops apply 成功、分析记录落盘后返回 200。
- 如果中途失败，异常向上抛出，不保存假成功记录。

### 5.2 读入口：查询分析记录

```text
GET /api/v1/krss-analyses/{analysis_id}
```

响应体：

```text
KRSSAnalysisRecord
```

语义：

- 返回稳定分析记录。
- 如果不存在，返回 404。

### 5.3 状态入口

```text
GET /api/v1/status
```

返回：

```json
{
  "storage": "data/repair_service",
  "cgs_base_url": "...",
  "knowledge_ops_repairs_apply_url": "...",
  "llm_enabled": true,
  "llm_model": "...",
  "llm_configured": true,
  "mode": "krss_apply",
  "diagnosis_mode": "llm"
}
```

它用于控制台和运维观察，不参与诊断。这里的 `cgs_base_url` 是兼容配置展示，不表示 KRSS 写入口会回查 CGS prompt snapshot。

### 5.4 健康检查

```text
GET /health
```

返回服务是否可响应。

## 6. 状态与语义

### 6.1 写接口状态

KRSS 写接口当前只返回一种成功状态：

```text
status = applied
```

它表示：

- KRSS 已完成根因诊断。
- KRSS 已生成知识修复请求。
- Knowledge Ops apply 返回成功。
- KRSS 已保存分析记录。

它不表示：

- 知识补丁已经被验证有效。
- 下一轮 CGS 生成一定通过。
- 业务问题已经最终解决。

### 6.2 validation 状态

`validation_mode` 只有两种：

| 取值 | 含义 |
| --- | --- |
| `disabled` | 未执行 lightweight validation |
| `lightweight` | 执行了类型级启发式筛选 |

`used_experiments = true` 表示执行了 lightweight validation。这里的 experiments 是历史命名，不代表真实重生成或真实对照实验。

### 6.3 knowledge type 语义

| 类型 | 含义 |
| --- | --- |
| `cypher_syntax` | Cypher 语法、只读约束、输出格式相关知识 |
| `few_shot` | 示例覆盖不足，模型缺少相似问题的正确模式 |
| `system_prompt` | 系统级约束、输出契约或生成规则不清晰 |
| `business_knowledge` | 业务术语、实体关系、领域映射或图谱语义知识不足 |

这些类型用于指导 Knowledge Ops 选择修复位置，不等同于最终业务根因裁决。

## 7. 持久化与可追踪性

### 7.1 分析记录主键

KRSS 使用：

```text
analysis_id = analysis-{ticket_id}
```

原因：

- `id` 表示 QA 样本。
- `ticket_id` 表示一次具体失败事件。
- 同一个 `id` 可以有多轮 attempt，每一轮失败都应有独立分析记录。

### 7.2 证据留存

KRSS 会在 `KRSSAnalysisRecord` 中保留：

- prompt snapshot。
- 知识修复请求。
- Knowledge Ops 响应。
- 诊断置信度。
- LLM rationale。
- lightweight validation 结果。
- 诊断上下文摘要。

这些字段构成后续 RCA、回放、控制台展示和外部审计的依据。

### 7.3 prompt snapshot 留存

`KRSSAnalysisRecord.prompt_snapshot` 保存的是 KRSS 实际用于诊断的 prompt。

当前来源：

```text
IssueTicket.generation_evidence.input_prompt_snapshot
  -> IssueTicket.input_prompt_snapshot
```

它不是 KRSS 从 CGS 在线查询得到的。

## 8. 错误处理原则

### 8.1 输入证据缺失

如果 `generation_evidence` 不存在，KRSS 会回退到兼容字段 `input_prompt_snapshot`。

如果 prompt 为空，KRSS 不会伪造 prompt；诊断上下文中的 prompt evidence 为空，LLM 仍基于其他失败证据进行诊断。后续可以把“缺失 prompt evidence”升级为显式输入契约错误。

### 8.2 诊断失败

如果 LLM 诊断、JSON 解析或上下文处理失败，KRSS 不生成半结构化假请求，异常向上抛出。

### 8.3 Knowledge Ops apply 失败

如果 apply 失败：

- transport error 可重试。
- 5xx、202、204 等非 200 响应按可重试路径处理。
- 4xx 直接终止。
- 不保存“已应用”的分析记录。

这保证了 `KRSSIssueTicketResponse(status=applied)` 与真正的 apply 成功严格一致。

### 8.4 幂等记录已存在

如果 `analysis-{ticket_id}` 已存在，KRSS 直接返回历史记录。

当前实现是读后判断，不是强并发原子 claim。并发重复提交同一 ticket 时，仍可能出现重复 apply 风险。后续如果进入生产并发场景，应将 repository 扩展为原子占位或锁机制。

## 9. 测试与契约守护

KRSS 需要重点守护四类契约。

### 9.1 IssueTicket 输入契约

需要确保问题单包含：

- `ticket_id`
- `id`
- `question`
- `expected.cypher`
- `actual.generated_cypher`
- `actual.execution`
- `evaluation.dimensions`
- `evaluation.symptom`
- `evaluation.evidence`
- `generation_evidence.input_prompt_snapshot`
- `diagnostic_summary`

### 9.2 prompt evidence 契约

需要确保：

- KRSS 不从 CGS 拉 prompt snapshot。
- KRSS 优先使用 `IssueTicket.generation_evidence.input_prompt_snapshot`。
- 中文或结构化 prompt 能进入 `prompt_evidence`。
- `relevant_prompt_fragments` 只是辅助字段，不能作为唯一 prompt 证据。

### 9.3 LLM diagnosis 契约

需要确保：

- LLM 返回 JSON object。
- 允许的知识类型只有四个正式类型。
- 非法类型会被清洗或回退。
- `need_validation` 缺失时兼容旧字段 `need_experiments`。

### 9.4 Knowledge Ops apply 契约

需要确保：

- 出站 payload 只含 `id`、`suggestion`、`knowledge_types`。
- `knowledge_types` 只允许正式类型。
- 只有 HTTP 200 视为 apply 成功。
- apply 成功前不保存 applied 记录。

## 10. 一句话定义

KRSS 是一个“把 Testing Service 的失败问题单转成正式知识修复请求”的服务：它消费失败样本、评测证据和生成证据，归因到知识类型，形成最小修复建议，并在 Knowledge Ops apply 成功后保存可追踪的分析记录。
