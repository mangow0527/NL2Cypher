# Cypher Generation Service 正式服务定义草案（修订版）

## Summary

本文档将 `Cypher Generation Service`（Cypher 生成服务）定义为一个**负责接收问题、主动获取正式提示词、调用大语言模型生成 Cypher，并将生成结果提交给测试服务的生成执行服务**。

它的核心使命是：

**输入任务标识（Task ID，任务标识）和问题原文（Question Text，问题原文），向外部知识运营服务获取当前可用的生成提示词（Generation Prompt，生成提示词），调用大语言模型（LLM，Large Language Model，大语言模型）生成 Cypher，并输出结构化的生成结果。**

它不是提示词设计服务，不是图查询执行服务，也不是最终评测服务。  
它只负责“生成阶段”的完整执行，不负责“业务结果”的最终裁决。

本文档同时定义：
- 服务职责边界
- 输入输出对象
- 内部工作流程
- 生成阶段状态定义
- 与知识运营服务、测试服务的边界关系
- 用于长期稳定维护的测试与契约守护方式

---

## 一、服务定义

### 1.1 服务名称

**Cypher Generation Service（Cypher 生成服务）**

### 1.2 服务中文定义

Cypher 生成服务是一个**生成执行服务**。  
它接收问题生成请求，自主获取外部正式提示词，调用模型生成 Cypher，并把生成产物与生成证据交给测试服务。

### 1.3 服务本质

它不是“业务理解中心”，而是“生成执行节点”。  
它负责：

- 接收生成任务
- 获取提示词
- 调用模型
- 解析输出
- 做最小守门
- 保存生成证据
- 提交测试服务

### 1.4 服务目标

服务目标有四项：

1. **生成链路完整**
   - 能独立完成从问题输入到生成产物提交的整段流程。

2. **输出稳定可消费**
   - 生成结果必须能够被测试服务稳定接收与执行。

3. **输入输出可追踪**
   - 必须能回溯本轮问题、本轮提示词、本轮原始输出和最终生成结果。

4. **边界长期稳定**
   - 后续实现变更不能把提示词设计、图执行、最终评测重新塞回本服务。

### 1.5 非目标

本服务明确**不承担**以下职责：

- 不设计 Prompt（提示词）
- 不优化 Prompt（提示词）
- 不执行 TuGraph 查询
- 不做标准答案比对
- 不判断业务问题是否答对
- 不做根因分析
- 不做修复策略制定

---

## 二、职责边界

## 2.1 对外入口职责

本服务对外提供一个问题提交入口，供外部服务发送：

- `id`（任务标识）
- `question`（问题原文）

这部分入口职责延续此前已设计的模式。

## 2.2 对知识运营服务的依赖职责

本服务在接收到任务后，应**主动向外部知识运营服务发起提示词查询请求**，获取当前可用的正式生成提示词。

当前明确约定的接口为：

- 方法：`POST`
- 路径：`/api/knowledge/rag/prompt-package`
- 请求体：`{id, question}`
- 响应体：一个 `string` 类型的提示词原文

边界原则：
- 本服务负责“获取提示词”
- 知识运营服务负责“提供提示词”
- 本服务不负责“生成提示词”

## 2.3 对测试服务的边界职责

本服务在生成完成后，将生成产物提交给测试服务。  
测试服务负责：

- 执行 TuGraph 查询
- 获取执行结果
- 与标准答案对比
- 进行评测
- 生成问题单

边界原则：
- 本服务只负责“生成阶段处理状态”
- 测试服务负责“业务评测结果状态”

---

## 三、成功定义与状态语义

这是本服务边界中最重要的一条。

## 3.1 本服务不判断“业务成功”

本服务**不判断**以下问题：
- 这条 Cypher 是否真正答对了问题
- 执行结果是否与标准答案一致
- 是否需要生成问题单

这些判断全部属于测试服务。

## 3.2 本服务只判断“生成阶段处理状态”

本服务只维护：

**Generation Processing Status（生成处理状态）**

它描述的是：
**本服务这一段流程是否完成，以及完成到了哪一步。**

### 建议状态值

- `received`（已接收）
- `prompt_fetch_failed`（提示词获取失败）
- `prompt_ready`（提示词已就绪）
- `model_invocation_failed`（模型调用失败）
- `output_parsing_failed`（输出解析失败）
- `guardrail_rejected`（守门拒绝）
- `submitted_to_testing`（已提交测试）
- `failed`（生成阶段失败）

### 关键原则

`submitted_to_testing`（已提交测试）并不等于：
- `passed`（通过）
- `succeeded_in_business`（业务成功）

真正的业务通过/失败，必须由测试服务给出。

---

## 四、输入与输出定义

## 4.1 输入对象

正式输入对象命名为：

`CypherGenerationTask`（Cypher 生成任务）

### 字段定义

- `id`（任务标识）
  - 业务含义：本次问答或生成任务的唯一 ID

- `question`（问题原文）
  - 业务含义：用户提出的自然语言问题
  - 说明：本服务接收并传递该问题，但不负责完整业务语义解释

### 当前输入约束

当前阶段不额外引入：
- 提示词版本
- 知识修订版本
- 模型覆写
- 生成策略字段

当前外部正式入口只保留最小输入集合：
- 任务标识
- 问题原文

## 4.2 对知识运营服务的接口请求体

知识运营服务接口请求体字段固定为：

- `id`（任务标识）
  - 业务含义：对应当前生成任务

- `question`（问题原文）
  - 业务含义：用于请求知识运营服务返回当前可用提示词

## 4.3 来自知识运营服务的接口响应体

知识运营服务接口响应体不再定义为 JSON 对象。  
当前约定响应体就是：

- `prompt string`（提示词字符串）
  - 业务含义：当前知识运营服务提供的正式 Prompt 原文

### 设计说明

Cypher Generation Service 获取到该字符串后，直接将其作为本轮模型调用使用的 `input_prompt_snapshot`（输入提示词快照）来源。  
当前接口不要求知识运营服务返回：
- `prompt_version`（提示词版本）
- `knowledge_package_id`（知识包标识）
- `knowledge_revision`（知识修订版本）

如果未来需要扩展为结构化返回，必须单独做架构评审，并先更新本正式定义文档。

## 4.4 输出对象

正式输出对象命名为：

`CypherGenerationResult`（Cypher 生成结果）

### 字段定义

- `id`（任务标识）
  - 业务含义：对应输入任务 ID

- `generation_run_id`（生成运行标识）
  - 业务含义：本次服务内部生成流程的唯一运行 ID

- `generation_status`（生成处理状态）
  - 业务含义：本次生成流程当前结果
  - 说明：这是生成阶段状态，不是业务评测结果

- `generated_cypher`（生成的 Cypher）
  - 业务含义：本轮生成得到的最终 Cypher 语句
  - 失败时可为空

- `parse_summary`（解析摘要）
  - 业务含义：模型原始输出如何被转换为最终 Cypher 的摘要说明

- `guardrail_summary`（守门摘要）
  - 业务含义：最小守门阶段的检查结果摘要

- `raw_output_snapshot`（原始输出快照）
  - 业务含义：模型原始输出的受控留存，用于排障与根因分析

- `failure_stage`（失败阶段，可选）
  - 业务含义：失败发生在哪个处理步骤
  - 示例：
    - `prompt_fetch`
    - `prompt_readiness_check`
    - `model_invocation`
    - `output_parsing`
    - `guardrail_check`

- `failure_reason_summary`（失败原因概要，可选）
  - 业务含义：失败的简要概括说明

- `input_prompt_snapshot`（输入提示词快照）
  - 业务含义：本轮生成实际使用的提示词原文留存
  - 说明：必须保留，用于后续根因分析

### 关键说明

`input_prompt_snapshot`（输入提示词快照）是正式输出的一部分，  
也是正式持久化记录的一部分，不能只保留摘要。

---

## 五、内部工作流程

本服务内部流程固定为 7 步。

### Step 1: Task Intake（任务接收）
**中文名：任务接收**

输入：
- `CypherGenerationTask`（Cypher 生成任务）

输出：
- `ReceivedTask`（已接收任务）

职责：
- 接收任务
- 校验任务标识和问题原文是否存在
- 生成 `generation_run_id`（生成运行标识）
- 建立初始处理记录

不做的事：
- 不构造提示词
- 不规划查询
- 不判断业务正确性

### Step 2: Prompt Fetch（提示词获取）
**中文名：提示词获取**

输入：
- `ReceivedTask`（已接收任务）

输出：
- `FetchedPromptPayload`（已获取提示词载荷）

职责：
- 向知识运营服务发送提示词获取请求
- 获取本轮正式提示词
- 记录是否成功获取
- 留存本轮实际获取到的提示词原文

失败时：
- 将 `generation_status`（生成处理状态）标记为 `prompt_fetch_failed`（提示词获取失败）

### Step 3: Prompt Readiness Check（提示词就绪检查）
**中文名：提示词就绪检查**

输入：
- `FetchedPromptPayload`（已获取提示词载荷）

输出：
- `ReadyPromptPayload`（可调用提示载荷）

职责：
- 检查提示词是否为空
- 检查提示词是否超出允许长度
- 检查问题原文与提示词是否均满足调用前提

不依赖 LLM。  
不评价提示词质量，只判断是否可调用。

### Step 4: Model Invocation（模型调用）
**中文名：模型调用**

输入：
- `ReadyPromptPayload`（可调用提示载荷）

输出：
- `RawModelResponse`（模型原始响应）

职责：
- 调用目标大语言模型
- 控制超时
- 控制必要的失败重试
- 记录调用耗时和响应状态

失败时：
- 标记 `generation_status`（生成处理状态）为 `model_invocation_failed`（模型调用失败）

### Step 5: Output Parsing（输出解析）
**中文名：输出解析**

输入：
- `RawModelResponse`（模型原始响应）

输出：
- `ParsedCypherCandidate`（已解析 Cypher 候选）

职责：
- 提取 Cypher
- 兼容：
  - JSON 输出
  - Markdown 代码块输出
  - 纯文本输出
- 生成解析摘要
- 保留原始输出快照

不依赖 LLM。  
必须使用确定性解析规则。

失败时：
- 标记 `generation_status`（生成处理状态）为 `output_parsing_failed`（输出解析失败）

### Step 6: Minimal Guardrail Check（最小守门检查）
**中文名：最小守门检查**

输入：
- `ParsedCypherCandidate`（已解析 Cypher 候选）

输出：
- `GuardedCypherResult`（守门后的 Cypher 结果）

职责：
- 做最低限度的可提交性检查
- 判断生成结果是否可提交测试服务

建议仅检查：
- 是否非空
- 是否可识别
- 是否具有明显 Cypher 起始结构
- 是否满足最小输出协议

失败时：
- 标记 `generation_status`（生成处理状态）为 `guardrail_rejected`（守门拒绝）

### Step 7: Persist And Submit（持久化并提交）
**中文名：持久化并提交**

输入：
- `GuardedCypherResult`（守门后的 Cypher 结果）

输出：
- `CypherGenerationResult`（Cypher 生成结果）

职责：
- 保存完整生成记录
- 保存输入提示词快照
- 保存原始输出快照
- 形成正式输出对象
- 向测试服务提交生成产物

成功时：
- 标记 `generation_status`（生成处理状态）为 `submitted_to_testing`（已提交测试）

---

## 六、对外接口与内部接口设计

## 6.1 对外主入口接口

建议沿用此前已设计入口：

`POST /api/v1/qa/questions`

### 请求体

- `id`（任务标识）
- `question`（问题原文）

### 响应体

返回：
- `CypherGenerationResult`（Cypher 生成结果）

说明：
- 这里返回的是生成阶段结果
- 不是最终业务评测结果

### 接口职责说明

该接口面向外部业务服务使用，职责是：
- 提交一条新的 Cypher 生成任务
- 触发本服务主动向知识运营服务获取提示词
- 完成一次完整的生成阶段处理
- 返回本轮生成阶段结果

### 请求示例

```bash
curl -X POST http://127.0.0.1:8000/api/v1/qa/questions \
  -H "Content-Type: application/json" \
  -d '{
    "id": "qa-001",
    "question": "查询网络设备名称"
  }'
```

### 响应示例

```json
{
  "id": "qa-001",
  "generation_run_id": "run-001",
  "generation_status": "submitted_to_testing",
  "generated_cypher": "MATCH (n:NetworkElement) RETURN n.name AS name LIMIT 5",
  "parse_summary": "parsed_json",
  "guardrail_summary": "accepted",
  "raw_output_snapshot": "{\"cypher\":\"MATCH (n:NetworkElement) RETURN n.name AS name LIMIT 5\"}",
  "failure_stage": null,
  "failure_reason_summary": null,
  "input_prompt_snapshot": "请仅返回 JSON，其中包含 cypher 字段。问题：查询网络设备名称"
}
```

## 6.1.1 对外提示词快照查询接口

为了支持后续测试服务、修复服务或其他根因分析服务回溯“本轮任务到底使用了什么提示词”，本服务应提供一个只读接口，用于按任务标识查询提示词快照。

建议接口：

`GET /api/v1/questions/{id}/prompt`

### 响应体

- `id`（任务标识）
- `input_prompt_snapshot`（输入提示词快照）

### 接口职责说明

该接口只负责读取本服务已留存的提示词快照，不触发重新生成，不调用知识运营服务，不修改任何状态。

### 请求示例

```bash
curl http://127.0.0.1:8000/api/v1/questions/qa-001/prompt
```

### 响应示例

```json
{
  "id": "qa-001",
  "input_prompt_snapshot": "请仅返回 JSON，其中包含 cypher 字段。问题：查询网络设备名称"
}
```

## 6.2 对知识运营服务的内部调用接口

建议由知识运营服务提供如下接口：

`POST /api/knowledge/rag/prompt-package`

### 请求体
- `id`（任务标识，string）
- `question`（问题原文，string）

### 响应体
- 一个 `string` 类型的提示词原文

### 设计原则
- 获取由 Cypher Generation Service 主动发起
- 提供由知识运营服务负责
- 内容责任归属知识运营服务
- 调用责任归属 Cypher Generation Service
- Cypher Generation Service 不对返回体做二次语义解释，只直接读取该提示词字符串

### 请求示例

```bash
curl -X POST http://127.0.0.1:8003/api/knowledge/rag/prompt-package \
  -H "Content-Type: application/json" \
  -d '{
    "id": "qa-001",
    "question": "查询网络设备名称"
  }'
```

### 响应示例

```text
请仅返回 JSON，其中包含 cypher 字段。问题：查询网络设备名称
```

## 6.3 向测试服务的提交对象

建议下游提交对象命名为：

`GeneratedCypherSubmission`（生成 Cypher 提交对象）

### 建议字段

- `id`（任务标识）
- `generation_run_id`（生成运行标识）
- `question`（问题原文）
- `generated_cypher`（生成的 Cypher）
- `input_prompt_snapshot`（输入提示词快照）
- `parse_summary`（解析摘要）
- `guardrail_summary`（守门摘要）
- `raw_output_snapshot`（原始输出快照）

说明：
- 让测试服务或后续分析服务拿到完整生成证据
- 但不在本服务内做业务裁决

### 提交示例

```json
{
  "id": "qa-001",
  "generation_run_id": "run-001",
  "question": "查询网络设备名称",
  "generated_cypher": "MATCH (n:NetworkElement) RETURN n.name AS name LIMIT 5",
  "input_prompt_snapshot": "请仅返回 JSON，其中包含 cypher 字段。问题：查询网络设备名称",
  "parse_summary": "parsed_json",
  "guardrail_summary": "accepted",
  "raw_output_snapshot": "{\"cypher\":\"MATCH (n:NetworkElement) RETURN n.name AS name LIMIT 5\"}"
}
```

---

## 七、数据结构附录

### A. `CypherGenerationTask`（Cypher 生成任务）
表示一次外部发起的生成请求。  
字段固定为：
- 任务标识
- 问题原文

### B. `PromptFetchRequest`（提示词获取请求）
表示 Cypher 生成服务向知识运营服务发出的 HTTP 请求体。  
字段固定为：
- `id`
- `question`

### C. `PromptFetchResponse`（提示词获取响应）
表示知识运营服务返回的正式提示词字符串，而不是 JSON 对象。

### D. `ReceivedTask`（已接收任务）
表示已通过最初始接收校验的任务。

### E. `FetchedPromptPayload`（已获取提示词载荷）
表示已成功从知识运营服务获取到提示词的任务上下文。

### F. `ReadyPromptPayload`（可调用提示载荷）
表示已通过调用前检查、可以发往模型的提示词载荷。

### G. `RawModelResponse`（模型原始响应）
表示模型返回的原始输出及调用信息。

### H. `ParsedCypherCandidate`（已解析 Cypher 候选）
表示从模型输出中解析得到的 Cypher 候选结果。

### I. `GuardedCypherResult`（守门后的 Cypher 结果）
表示通过最小守门后、允许提交下游的生成结果。

### J. `CypherGenerationResult`（Cypher 生成结果）
表示本服务正式对外返回的结果对象。

### K. `GeneratedCypherSubmission`（生成 Cypher 提交对象）
表示发送给测试服务的提交对象。

### N. `PromptSnapshotResponse`（提示词快照响应）
表示本服务对外暴露的按任务标识查询提示词快照的只读响应对象。

### L. `InputPromptSnapshot`（输入提示词快照）
表示本轮实际使用的提示词原文留存。

### M. `RawOutputSnapshot`（原始输出快照）
表示本轮模型原始输出的受控留存。

---

## 八、最小守门规则

为了避免服务职责膨胀，守门规则必须保持固定、克制、有限。

### 必选守门规则

1. `非空规则`
   - 必须解析出非空 Cypher 文本

2. `可识别规则`
   - 输出必须可被确定性解析器识别

3. `最小结构规则`
   - 文本需具备明显查询语句起始结构
   - 例如 `MATCH`、`WITH`、`CALL`

4. `协议一致性规则`
   - 若模型被要求返回 JSON，则必须能从 JSON 或容错解析中取出目标字段

### 明确禁止纳入的守门能力

- 不允许把业务正确性判断纳入守门
- 不允许把 TuGraph 执行纳入守门
- 不允许把 Golden 对比纳入守门
- 不允许把 LLM 二次判定纳入守门
- 不允许把复杂查询规划纳入守门

---

## 九、服务稳定性维护构想

为了让本服务在多次迭代中不漂移，建议建立 4 层守护。

## 9.1 契约测试（Contract Tests，契约测试）
目标：
- 守住输入输出字段与业务含义

重点断言：
- 对外输入只包含 `id`（任务标识）和 `question`（问题原文）
- 输出必须包含：
  - 任务标识
  - 生成运行标识
  - 生成处理状态
  - 生成的 Cypher
  - 解析摘要
  - 守门摘要
  - 原始输出快照
  - 失败阶段
  - 失败原因概要
  - 输入提示词快照

## 9.2 流程测试（Workflow Tests，流程测试）
目标：
- 守住 7 步固定流程

重点场景：
- 正常获取提示词并正常生成
- 提示词获取失败
- 模型调用超时
- 输出解析失败
- 守门拒绝
- 成功提交测试服务

## 9.3 守门规则测试（Guardrail Tests，守门规则测试）
目标：
- 守住“最小守门”边界

重点断言：
- 可以挡住空输出
- 可以挡住无法解析输出
- 不要求执行结果才能放行
- 不会把业务评测逻辑塞进本服务

## 9.4 设计回归测试（Design Regression Tests，设计回归测试）
目标：
- 守住服务定位不膨胀

重点断言：
- 本服务代码路径中不得要求 Golden Answer
- 本服务输出中不得包含 TuGraph 执行结果
- 本服务内部不得新增 Prompt 组装职责
- 本服务必须保留输入提示词快照
- 本服务只输出生成阶段状态，不输出业务评测通过/失败

---

## 十、长期维护机制建议

### 10.1 文档优先变更
以下变更必须先修改本服务定义文档，再改代码：
- 对外输入对象
- 输出对象
- 生成阶段状态
- 内部固定流程
- 守门规则
- 输入提示词留存规则

### 10.2 术语统一表
本文档应长期维护术语表，所有英文术语均需有中文翻译。

### 10.3 版本化管理
建议文档显式带版本：
- `Service Definition Version`（服务定义版本）
- `Effective Date`（生效日期）

### 10.4 架构变更准入规则
未来若有人希望把以下能力重新放入 Cypher Generation Service，必须单独做架构评审：
- Prompt 设计
- Prompt 优化
- TuGraph 执行
- Golden 对比
- 业务评测
- 根因分析
- 修复策略制定

---

## Assumptions And Defaults

- 对外主入口保持为“任务标识 + 问题原文”。
- 提示词由 Cypher Generation Service 主动向知识运营服务获取。
- 知识运营服务接口固定为 `POST /api/knowledge/rag/prompt-package`，请求体为 `{id, question}`，响应体为 `string prompt`。
- 获取提示词是本服务职责，设计提示词不是本服务职责。
- 本服务输出的是生成阶段处理状态，不是业务评测结果。
- 测试服务负责执行 TuGraph 并完成最终评测。
- 输入提示词快照必须保留，用于后续根因分析。
- 输出解析、提示词就绪检查、最小守门检查均默认不依赖 LLM。
- 本服务应保持为薄服务，避免重新膨胀为知识组织、执行、评测一体服务。
