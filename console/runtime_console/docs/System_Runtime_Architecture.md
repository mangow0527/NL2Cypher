# 系统运行架构（System Runtime Architecture）

## 系统概述（System Overview）

当前系统以 `testing-agent` 为执行与联调中枢，围绕五个正在运行的服务形成一条可验证的主链路：

- `cypher-generator-agent` `8000`
- `testing-agent` `8001`
- `repair-agent` `8002`
- `knowledge-agent` `8010`
- `qa-agent` `8020`

其中，`testing-agent` 负责执行与评测，`repair-agent` 负责知识修复建议，`knowledge-agent` 负责提示词与知识更新，`qa-agent` 负责题目与黄金样本生成支持。

---

## 服务清单（Service Inventory）

### cypher-generator-agent

- 端口（Port）：`8000`
- 主要职责（Primary Role）：
  - 接收 `id + question`
  - 向 `knowledge-agent` 获取提示词包（Prompt Package）
  - 调用模型生成 Cypher
  - 保存 `提示词快照（Prompt Snapshot）`
  - 向 `testing-agent` 提交 `评测提交（Evaluation Submission）`

### testing-agent

- 端口（Port）：`8001`
- 主要职责（Primary Role）：
  - 接收黄金答案（Golden）
  - 执行 TuGraph
  - 做规则评测与可选 LLM 复评
  - 在失败时生成 `问题票据（Issue Ticket）`
  - 承载 `系统联调工作台（System Integration Console）`

### repair-agent

- 端口（Port）：`8002`
- 主要职责（Primary Role）：
  - 接收 `testing-agent` 发送的问题票据
  - 读取 testing-agent 持久化的问题票据与 `KRSSAnalysisRecord` 中的 `Prompt Snapshot`
  - 进行根因分析
  - 生成 `知识修复建议（Knowledge Repair Suggestion）`
  - 向 `knowledge-agent` 提交修复建议

### knowledge-agent

- 端口（Port）：`8010`
- 主要职责（Primary Role）：
  - 对 cypher-generator-agent 提供纯文本提示词字符串（Prompt Package Response）
  - 对 repair-agent 接收知识修复建议并落地知识更新

### qa-agent

- 端口（Port）：`8020`
- 主要职责（Primary Role）：
  - 提供问题生成与黄金样本生成能力
  - 作为 `testing-agent` 上游的题目与标准答案支持组件

---

## 主链路（Primary Runtime Paths）

### 成功路径（Success Path）

`问题请求（QA Question） -> cypher-generator-agent -> testing-agent -> 通过（Pass）`

具体过程：

1. 外部请求向 cypher-generator-agent 发送 `id + question`
2. cypher-generator-agent 向 knowledge-agent 获取提示词包
3. cypher-generator-agent 生成 Cypher，并保留提示词快照
4. cypher-generator-agent 向 testing-agent 提交评测数据
5. testing-agent 执行 TuGraph 并完成评测
6. 如果评测通过，链路结束

### 失败闭环路径（Failure Closed Loop）

`问题请求（QA Question） -> cypher-generator-agent -> testing-agent -> repair-agent -> knowledge-agent`

具体过程：

1. 外部请求向 cypher-generator-agent 发送 `id + question`
2. cypher-generator-agent 向 knowledge-agent 获取提示词包并生成 Cypher
3. testing-agent 执行评测
4. 若失败，testing-agent 生成 `问题票据（Issue Ticket）`
5. testing-agent 将问题票据发送给 repair-agent
6. repair-agent 读取 testing-agent 持久化的 `Issue Ticket` / `KRSSAnalysisRecord` 中的 `Prompt Snapshot`
7. repair-agent 生成 `知识修复建议（Knowledge Repair Suggestion）`
8. repair-agent 将修复建议提交给 knowledge-agent

---

## 关键数据对象（Key Data Objects）

### 问题请求（QA Question）

- 来源（Source）：外部调用方 / qa-agent
- 去向（Destination）：cypher-generator-agent
- 含义（Meaning）：一次待生成 Cypher 的问题输入，包含 `id` 与 `question`

### 提示词快照（Prompt Snapshot）

- 来源（Source）：testing-agent
- 去向（Destination）：repair-agent
- 含义（Meaning）：由 testing-agent 在 `Issue Ticket` 中保存的失败样本输入快照，或由 repair-agent 在 `KRSSAnalysisRecord` 中保存的诊断快照；这两者构成 repair-agent 的 prompt snapshot 展示来源

### Prompt Package Response

- 来源（Source）：knowledge-agent
- 去向（Destination）：cypher-generator-agent
- 含义（Meaning）：`POST /api/knowledge/rag/prompt-package` 的正式响应体，为纯文本提示词字符串，而不是 JSON 包装对象

### 评测提交（Evaluation Submission）

- 来源（Source）：cypher-generator-agent
- 去向（Destination）：testing-agent
- 含义（Meaning）：cypher-generator-agent 向 testing-agent 提交的生成结果与生成证据

### 问题票据（Issue Ticket）

- 来源（Source）：testing-agent
- 去向（Destination）：repair-agent
- 含义（Meaning）：一条失败样本及其评测证据，用于知识根因分析

### 知识修复建议（Knowledge Repair Suggestion）

- 来源（Source）：repair-agent
- 去向（Destination）：knowledge-agent
- 含义（Meaning）：面向 `knowledge-agent` 的正式知识修复请求

---

## 服务边界（Service Boundaries）

### cypher-generator-agent 的边界

- 负责生成（Generate）
- 不负责执行（Do Not Execute TuGraph）
- 不负责最终业务裁决（Do Not Judge Final Business Correctness）

### testing-agent 的边界

- 负责执行（Execute）
- 负责评测（Evaluate）
- 负责问题票据生成（Create Issue Tickets）
- 不负责知识修复建议生成（Do Not Produce Knowledge Repair Suggestions）

### repair-agent 的边界

- 负责知识修复建议（Produce Knowledge Repair Suggestions）
- 不负责业务裁决（Do Not Judge Final Business Correctness）
- 不负责重新生成 Cypher（Do Not Regenerate Cypher）
- 不负责回头向 cypher-generator-agent 拉取 prompt snapshot（Do Not Re-fetch Prompt Snapshot from cypher-generator-agent）

### knowledge-agent 的边界

- 负责提供纯文本提示词字符串（Provide Plain-Text Prompt Package Response）
- 负责知识更新（Apply Knowledge Repairs）

---

## 联调入口（Integration Entry Points）

### 系统联调工作台（System Integration Console）

- 挂载位置：`testing-agent`
- 页面路径：`/console`
- 用途：
  - 查看运行服务状态
  - 查看正式结构图与数据流
  - 发起成功路径与失败路径联调
  - 观察 `Prompt Snapshot`、`Evaluation`、`Issue Ticket` 与 `Knowledge Repair Suggestion`

### 关键接口速查（Interface Quick Reference）

- `POST /api/v1/qa/questions`
- `GET /api/v1/questions/{id}/prompt`
- `POST /api/v1/qa/goldens`
- `POST /api/v1/evaluations/submissions`
- `POST /api/v1/issue-tickets`
- `POST /api/knowledge/rag/prompt-package`
- `POST /api/knowledge/repairs/apply`

---

## 当前默认运行认知（Current Runtime Interpretation）

当前系统的运行认知应固定为：

- `cypher-generator-agent` 是生成入口（Generation Entry）
- `testing-agent` 是执行与评测中心（Execution and Evaluation Hub）
- `repair-agent` 是知识修复建议中心（Knowledge Repair Suggestion Hub）
- `repair-agent` 的 prompt snapshot 展示源来自 testing-agent 持久化数据，而不是对 cypher-generator-agent 的在线回查
- `knowledge-agent` 是提示词和知识更新的双向知识入口（Knowledge Supply and Repair Sink）
- `qa-agent` 是问题与黄金样本生成支持组件（Question and Golden Generation Support）
