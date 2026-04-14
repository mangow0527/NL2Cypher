# Knowledge Repair Suggestion Service（KRSS）最新架构设计

## Summary

本文档记录 `repair_service` 当前已落地的 KRSS 架构（以代码为准），并详细说明根因分析（Root Cause Analysis, RCA）的工作流与数据结构。

当前主线实现是 **LLM-first + deterministic fallback**：优先使用 LLM 诊断，LLM 不可用或配置不完整时退回到确定性规则；`experiment_runner` 只是保留的扩展点，当前 runtime 主路径尚未接入它。

KRSS 的主链路是：

1. 接收 `IssueTicket`
2. 由 `ticket_id` 派生 `analysis_id = analysis-<ticket_id>`，先查本地分析记录
3. 如果已存在该 `analysis_id` 的记录，直接返回存储的 `KRSSIssueTicketResponse`，不再重新拉取 prompt、重新诊断或重新 apply
4. 如果没有记录，通过 `IssueTicket.id` 从 CGS（Cypher Generation Service）拉取 `PromptSnapshotResponse`（包含 `input_prompt_snapshot`）
5. 运行 `KRSSAnalyzer.analyze(issue_ticket, prompt_snapshot)` 得到 `KRSSAnalysisResult`
6. 将分析结果转换为 `KnowledgeRepairSuggestionRequest`
7. 调用 Knowledge Ops：`POST /api/knowledge/repairs/apply`
8. Knowledge Ops apply 成功后，落盘一条 `KRSSAnalysisRecord` 分析记录
9. 返回 `KRSSIssueTicketResponse`（仅在首次 apply 成功后返回）

关键约束：
- KRSS 对 Knowledge Ops 的出站 payload 严格只包含 `id/suggestion/knowledge_types`，且请求体形状固定
- `few_shot` 是 KRSS/shared/outbound 的正式且唯一的 few-shot repair 值，不存在隐藏的别名或后续映射层
- Knowledge Ops 只接受 `POST /api/knowledge/repairs/apply`
- 只有 HTTP 200 计为成功；4xx 视为非重试性失败，transport errors 以及可重试的非 200 响应（例如 5xx）会重试
- 分析记录的唯一键使用 `ticket_id`（而不是 `id`）

---

## 一、运行时组件

### 1.1 Repair Service 入口（FastAPI）

文件：[main.py](file:///Users/mangowmac/Desktop/code/NL2Cypher/services/repair_service/app/main.py)

- `POST /api/v1/issue-tickets`
  - request：`IssueTicket`（共享契约）
  - response：`KRSSIssueTicketResponse`（共享契约）
- `GET /api/v1/krss-analyses/{analysis_id}`
  - response：`KRSSAnalysisRecord`（共享契约）
- `GET /api/v1/status`
  - 返回 KRSS 模式与上游配置摘要

说明：
- 旧读路径 `GET /api/v1/repair-plans/{analysis_id}` 已不再暴露（应返回 404）。

### 1.2 主编排服务（RepairService）

文件：[service.py](file:///Users/mangowmac/Desktop/code/NL2Cypher/services/repair_service/app/service.py)

主流程：`RepairService.create_issue_ticket_response(issue_ticket)`

1. `RepairRepository.get_analysis(analysis_id)` 先查是否已有记录
2. 命中则直接返回存储的 `KRSSIssueTicketResponse`
3. 未命中才 `CGSPromptSnapshotClient.fetch(issue_ticket.id)`
4. `KRSSAnalyzer.analyze(issue_ticket, prompt_snapshot)`
5. `analysis.to_request()` → `KnowledgeRepairSuggestionRequest`
6. `KnowledgeOpsRepairApplyClient.apply(request)`（仅对 transport errors 和可重试的非 200 响应重试；4xx 终止）
7. `RepairRepository.save_analysis(record)` 落盘 `KRSSAnalysisRecord`
8. 返回 `KRSSIssueTicketResponse`

### 1.3 分析器（KRSSAnalyzer）

文件：[analysis.py](file:///Users/mangowmac/Desktop/code/NL2Cypher/services/repair_service/app/analysis.py)

KRSSAnalyzer 的输入：
- `IssueTicket`
- `prompt_snapshot: str`（来自 CGS 的 `input_prompt_snapshot`）

KRSSAnalyzer 的输出：
- `KRSSAnalysisResult`（内部结构，随后转为 `KnowledgeRepairSuggestionRequest`）

运行时选择：
- 当前主线是 LLM-first：当 `REPAIR_SERVICE_LLM_ENABLED=true` 且 OpenAI-compatible 配置齐全时，使用 `OpenAICompatibleKRSSAnalyzer`
- 否则，使用 `service.py` 内置的 `_DeterministicKRSSDiagnosisClient` 作为回退
- `experiment_runner` 仍是保留的扩展点，但未接入主路径，因此默认不会执行最小补丁对照实验

### 1.4 CGS prompt 快照客户端

文件：[clients.py](file:///Users/mangowmac/Desktop/code/NL2Cypher/services/repair_service/app/clients.py)

- `CGSPromptSnapshotClient.fetch(id)`：
  - 请求：`GET {cgs_base_url}/api/v1/questions/{id}/prompt`
  - 响应：`PromptSnapshotResponse`

CGS 侧接口定义参考：[query_generator_service main.py](file:///Users/mangowmac/Desktop/code/NL2Cypher/services/query_generator_service/app/main.py#L46-L52)

### 1.5 Knowledge Ops apply 客户端（含重试语义）

文件：[clients.py](file:///Users/mangowmac/Desktop/code/NL2Cypher/services/repair_service/app/clients.py#L137-L161)

- `KnowledgeOpsRepairApplyClient.apply(payload)`：
  - 行为：循环调用 `POST /api/knowledge/repairs/apply`；只看 HTTP 状态码，只有 200 返回才算成功；响应体不参与判定；transport errors 以及可重试的非 200 响应（例如 5xx）会重试，4xx 直接终止
  - 重要：重试只发生在“投递层”，不重复调用分析器

### 1.6 分析记录仓库（落盘）

文件：[repository.py](file:///Users/mangowmac/Desktop/code/NL2Cypher/services/repair_service/app/repository.py)

- `save_analysis(record)`：写入 `<data_dir>/analyses/{analysis_id}.json`；默认 `data_dir` 为 `data/repair_service`
- `get_analysis(analysis_id)`：读取并解析为 `KRSSAnalysisRecord`

---

## 二、共享契约（shared/models.py）

KRSS 的对外输入输出契约都在共享层，以避免 testing_service 直接依赖 repair_service 内部 schema。

文件：[models.py](file:///Users/mangowmac/Desktop/code/NL2Cypher/shared/models.py)

### 2.1 IssueTicket（输入）

`IssueTicket` 关键字段：
- `ticket_id: str`
- `id: str`（用于从 CGS 拉取 prompt_snapshot）
- `question: str`
- `expected: ExpectedAnswer`
- `actual: ActualAnswer`（包含 `generated_cypher` 与 `execution`）
- `evaluation: EvaluationSummary`（包含 `dimensions/symptom/evidence`）
- `input_prompt_snapshot: str`（可为空；事实输入以 CGS prompt_snapshot 为准）

### 2.2 KnowledgeRepairSuggestionRequest（出站到 Knowledge Ops）

`few_shot` 是这里的正式写法，也是对外唯一写法；KRSS 不保留也不输出 `few-shot` 这类别名。

```json
{
  "id": "q-001",
  "suggestion": "Add business mapping and a matching few_shot example",
  "knowledge_types": ["business_knowledge", "few_shot"]
}
```

字段约束：
- `knowledge_types` 仅允许：`cypher_syntax` / `few_shot` / `system_prompt` / `business_knowledge`

### 2.3 KRSSIssueTicketResponse（KRSS 写接口响应）

```json
{
  "status": "applied",
  "analysis_id": "analysis-ticket-001",
  "id": "q-001",
  "knowledge_repair_request": {
    "id": "q-001",
    "suggestion": "Add business mapping and a matching few_shot example",
    "knowledge_types": ["business_knowledge", "few_shot"]
  },
  "knowledge_ops_response": {
    "status": "ok"
  },
  "applied": true
}
```

说明：
- `analysis_id` 使用 `ticket_id` 派生（见下文）
- 响应只在 Knowledge Ops apply 成功（HTTP 200）后返回

### 2.4 KRSSAnalysisRecord（持久化分析记录 + 读接口返回）

存储位置由 `data_dir` 配置决定，实际路径形如 `<data_dir>/analyses/{analysis_id}.json`。当前默认 `data_dir` 为 `data/repair_service`，所以默认落盘位置是 `data/repair_service/analyses/<analysis_id>.json`。

字段集合：
- `analysis_id: str`
- `ticket_id: str`
- `id: str`
- `status: "applied"`
- `prompt_snapshot: str`
- `knowledge_repair_request: KnowledgeRepairSuggestionRequest`
- `knowledge_ops_response: Optional[Dict[str, Any]]`
- `confidence: float`
- `rationale: str`
- `used_experiments: bool`
- `applied: bool`
- `created_at: str`（UTC ISO8601）
- `applied_at: str`（UTC ISO8601）

---

## 三、分析记录唯一键：为什么用 ticket_id

KRSS 分析记录的主键使用：

`analysis_id = "analysis-" + ticket_id`

原因：
- `id` 是生成链路的任务标识，可能在不同测试轮次/不同评测上下文中复用
- `ticket_id` 表示一次具体的评测失败事件，更适合作为分析记录唯一键

实现位置：[service.py](file:///Users/mangowmac/Desktop/code/NL2Cypher/services/repair_service/app/service.py#L121-L125)

---

## 四、根因分析（RCA）工作流：详细到数据结构

本节描述 KRSSAnalyzer 的实际执行逻辑（以代码为准），并给出每一步的输入输出形态。

### 4.1 输入数据：IssueTicket + PromptSnapshotResponse

1) KRSS 收到 `IssueTicket`（来自 Testing Service）：

```json
{
  "ticket_id": "ticket-001",
  "id": "q-001",
  "difficulty": "L3",
  "question": "查询协议版本对应的隧道",
  "expected": { "cypher": "MATCH ...", "answer": [] },
  "actual": {
    "generated_cypher": "MATCH ...",
    "execution": { "success": true, "rows": [], "error_message": null }
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
  }
}
```

2) KRSS 从 CGS 拉取 `PromptSnapshotResponse`：

```json
{
  "id": "q-001",
  "input_prompt_snapshot": "Original CGS prompt snapshot"
}
```

### 4.2 诊断请求：KRSSDiagnosisClient.diagnose(ticket, prompt_snapshot)

KRSSAnalyzer 依赖一个 `KRSSDiagnosisClient` 返回结构化 dict（LLM 或确定性回退）。

KRSSAnalyzer 期望诊断结果包含以下键（缺失会被降级/默认值处理）：
- `knowledge_types: list[str]`
- `confidence: float`
- `suggestion: str`（可选；缺失则退化到 `rationale` 或默认文本）
- `rationale: str`（可选）
- `need_experiments: bool`（可选）
- `candidate_patch_types: list[str]`（可选；用于实验候选类型）

LLM 版本输出示例（概念形态）：

```json
{
  "knowledge_types": ["business_knowledge", "few_shot"],
  "confidence": 0.91,
  "suggestion": "Add business mapping and a matching few_shot example",
  "rationale": "Prompt misses protocol-version mapping guidance",
  "need_experiments": false,
  "candidate_patch_types": []
}
```

确定性回退（当前实现）映射规则（见 `service.py` 中 `_DeterministicKRSSDiagnosisClient`）：
- `syntax_validity=fail` → `["cypher_syntax", "system_prompt"]`
- `question_alignment=fail` 或 `result_correctness=fail` → `["business_knowledge", "few_shot"]`
- 否则 → `["system_prompt"]`

RCA 范围说明：
- KRSS 只会围绕 Knowledge Ops 实际可验证、可接收的知识类型做诊断与建议
- 因此 `schema_alignment` 仍可作为测试输入里的失败维度被观察，但它不会再映射成 KRSS 的修复类型；RCA 最终只输出 `cypher_syntax`、`few_shot`、`system_prompt`、`business_knowledge`

### 4.3 解析与约束：KRSSAnalyzer 对诊断结果的“收敛”

文件：[analysis.py](file:///Users/mangowmac/Desktop/code/NL2Cypher/services/repair_service/app/analysis.py)

KRSSAnalyzer 会做三类收敛：

1) `knowledge_types` 过滤：
- 仅允许：`cypher_syntax` / `few_shot` / `system_prompt` / `business_knowledge`
- 去重并保持顺序

2) `confidence` 归一化：
- 非法值 → fallback（默认 0）
- 归一到 `[0, 1]`

3) `suggestion` 兜底：
- 优先用 `diagnosis["suggestion"]`
- 否则用 `diagnosis["rationale"]`
- 否则用默认 `"Review and repair the missing knowledge."`

### 4.4 是否进入实验分支（当前默认不会）

KRSSAnalyzer 的决策条件：
- 若 `confidence >= min_confidence_for_direct_return`（默认 0.8）：直接返回（不实验）
- 或 `need_experiments` 为假：直接返回（不实验）
- 否则，理论上可以进入实验分支，但当前主线 runtime 没有把 `experiment_runner` 接到执行路径上，所以不会实际运行最小补丁对照实验，`used_experiments=false`

### 4.5 输出：KRSSAnalysisResult（内部）→ KnowledgeRepairSuggestionRequest（出站）

`KRSSAnalysisResult` 字段（内部）：
- `id: str`（来自 `ticket.id`）
- `suggestion: str`
- `knowledge_types: list[KnowledgeType]`
- `confidence: float`
- `rationale: str`
- `used_experiments: bool`

随后调用 `analysis.to_request()` 得到出站 payload：

```json
{
  "id": "q-001",
  "suggestion": "Add business mapping and a matching few_shot example",
  "knowledge_types": ["business_knowledge", "few_shot"]
}
```

---

## 五、对照实验（扩展能力，当前默认未启用）

KRSSAnalyzer 支持可选对照实验能力（需要注入 `experiment_runner`）。

当实验启用时：
- 输入：`(ticket, prompt_snapshot, patch_type, diagnosis)`  
- 输出：一个 dict，KRSSAnalyzer 通过 `improved` / `score_delta` / `confidence` 等字段判断是否“更好”，并选择最佳 `patch_type`（可并列）。

实验返回结构（概念形态）：

```json
{
  "improved": true,
  "confidence": 0.92,
  "suggestion": "Prefer adding system_prompt guardrails over business knowledge for this failure",
  "score_delta": 0.1
}
```

说明：
- 是否启用实验，以及实验如何执行与评分，属于后续迭代范围；本文档只记录当前已落地的默认行为与扩展接口点

---

## 六、文档一致性说明

本文档与当前代码保持一致的关键点：
- 读接口路径为 `/api/v1/krss-analyses/{analysis_id}`，不再暴露旧的 `/api/v1/repair-plans/{analysis_id}`
- 分析记录键使用 `ticket_id` 派生的 `analysis_id`
- KRSS 响应模型位于 `shared/models.py`
- 默认运行时不执行对照实验；`experiment_runner` 仅作为扩展点存在，尚未接入主路径
