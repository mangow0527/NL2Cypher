# testing-agent 架构与契约设计

## 1. 定位

testing-agent 是 Text2Cypher 闭环中的执行与评测服务。它接收标准答案和 cypher-generator-agent 生成结果，执行生成的 Cypher，产出可复现的评测事实，并在失败时把失败样本封装为问题单提交给 repair-agent。

一句话边界：

```text
testing-agent 证明“这次生成哪里错了”；
repair-agent 判断“是否属于 knowledge-agent 知识缺口，以及该修哪类 knowledge-agent 知识”。
```

testing-agent 提交给 repair-agent 的是失败事实和证据，不是 cypher-generator-agent 修复指令。若证据表明问题来自 cypher-generator-agent 固定生成协议、兜底解析、最小守门，或来自 testing-agent 自身评测器，这类问题应作为工程缺陷处理，不进入 repair-agent -> knowledge-agent 的业务知识修复闭环。

testing-agent 不是运行中心，不承载系统控制台、架构展示、跨服务健康聚合或 `/api/v1/runtime/*` 接口。这些能力归属 `console/runtime_console/`。

## 2. 术语与核心数据结构

本章先定义文档中反复出现的业务术语和数据结构。后续流程与责任边界都以这些对象为基础。

### 2.1 QA 样本与 `id`

`id` 是一条 QA 样本在闭环中的主键。它贯穿 QA 生成、cypher-generator-agent、testing-agent 和 repair-agent。

同一个 `id` 下会出现两类输入：

- golden：标准答案，由题库或 QA 侧提供。
- submission：cypher-generator-agent 对同一问题生成的 Cypher 提交。

testing-agent 只有在同一个 `id` 同时具备 golden 和 submission 后，才会进入评测。

### 2.2 `QAGoldenRequest`

`QAGoldenRequest` 表示标准答案输入，也就是 testing-agent 的评测基准。

它包含：

| 字段 | 含义 |
| --- | --- |
| `id` | QA 样本主键，用于和 submission 配对 |
| `cypher` | 黄金 Cypher，代表该问题的标准查询写法 |
| `answer` | 黄金答案，代表黄金 Cypher 的期望结果 |
| `difficulty` | 题目难度，取值为 `L1` 到 `L8` |

它的意义是：告诉 testing-agent“这道题什么答案算对”。

### 2.3 cypher-generator-agent -> testing-agent 契约：`EvaluationSubmissionRequest`

`EvaluationSubmissionRequest` 表示 cypher-generator-agent 提交给 testing-agent 的一次生成结果。它不是 testing-agent 单方面定义的内部对象，而是 cypher-generator-agent 与 testing-agent 之间的跨服务契约，必须与 `services/query_generator_agent/docs/Cypher_Generation_Service_Design.md` 中的“Step 8: 提交 testing-agent”保持一致。

这个契约的边界是：

- cypher-generator-agent 只提交生成结果和生成证据。
- testing-agent 负责接收、持久化、分配 `attempt_no`、执行和评测。
- cypher-generator-agent 不记录、不推断、不提交 `attempt_no`。

它包含：

| 字段 | 含义 |
| --- | --- |
| `id` | 问题标识，用于 testing-agent 与 golden answer 对齐 |
| `question` | 原始自然语言问题，供评测和 issue ticket 使用 |
| `generation_run_id` | cypher-generator-agent 本次执行标识，供问题追踪和证据串联 |
| `generated_cypher` | cypher-generator-agent 认为可提交评测的 Cypher |
| `parse_summary` | cypher-generator-agent 如何从模型输出得到 `generated_cypher`。它不参与 testing-agent 主评测打分，用于失败分析时区分“模型直接生成错误”和“解析/兜底恢复引入偏差”；如果问题来自 cypher-generator-agent 解析/兜底恢复，不应转成 knowledge-agent 知识修复建议 |
| `guardrail_summary` | cypher-generator-agent 最小守门结果。它不参与 testing-agent 主评测打分，用于判断 cypher-generator-agent 是否放行了格式、安全或只读约束问题；如果问题来自 cypher-generator-agent 守门规则本身，不应转成 knowledge-agent 知识修复建议 |
| `raw_output_snapshot` | LLM 原始输出。它不参与主评测打分，用于回放模型输出与最终 `generated_cypher` 是否一致 |
| `input_prompt_snapshot` | 最终 LLM 输入。它不参与主评测打分，主要供 repair-agent 分析 knowledge-agent 知识包、few-shot 或上下文是否诱发失败；其中 cypher-generator-agent 生成调用协议是固定系统包装，不作为 repair-agent 修复目标 |

它的意义是：告诉 testing-agent“cypher-generator-agent 这次生成了什么，以及这次生成过程留下了哪些证据”。

`attempt_no` 不属于 cypher-generator-agent 的职责。cypher-generator-agent 是单纯的生成服务，不记录“这是第几次尝试”。testing-agent 在接收 submission 后，根据同一 `id` 的历史记录分配并维护 `attempt_no`，并在后续 attempt 存储、IssueTicket 和改进评估中使用它。

### 2.4 `TuGraphExecutionResult`

`TuGraphExecutionResult` 表示 testing-agent 实际执行 `generated_cypher` 后得到的执行事实。

它包含：

| 字段 | 含义 |
| --- | --- |
| `success` | TuGraph 是否成功执行 |
| `rows` | 实际返回结果 |
| `row_count` | 返回行数 |
| `error_message` | 执行错误信息，成功时通常为空 |
| `elapsed_ms` | 执行耗时 |

它的意义是：为评测提供可复现事实。testing-agent 不只比较 Cypher 文本，也比较真实执行结果。

### 2.5 `EvaluationSummary`

`EvaluationSummary` 表示 testing-agent 对一次 `generated_cypher` 的评测结论。

它的来源不是 cypher-generator-agent，也不是 repair-agent，而是 testing-agent 在拿到 golden 与 submission 后，经过以下步骤生成：

1. 执行 `generated_cypher`，得到 `TuGraphExecutionResult`。
2. 将黄金 Cypher、黄金答案、实际 Cypher、实际执行结果交给评测引擎。
3. 评测引擎按四个维度生成 `dimensions`、`metrics`、`symptom` 和 `evidence`。
4. 如果规则评测没有通过，且 LLM 复评可用，testing-agent 可追加 LLM 语义复评结果。
5. 汇总为一个 `EvaluationSummary`，写入 IssueTicket 的 `evaluation` 字段。

它包含：

| 字段 | 含义 |
| --- | --- |
| `verdict` | 最终评测结论：`pass`、`partial_fail` 或 `fail`，由四维评测结果汇总得到 |
| `dimensions` | 四个维度的简化结论：`syntax_validity`、`schema_alignment`、`result_correctness`、`question_alignment`，每项为 `pass` 或 `fail` |
| `overall_score` | 四维加权总分，0 到 1。用于排序和观察趋势，不单独作为根因结论 |
| `metrics` | 每个维度的细粒度量化指标。这里保存分项分数、分项 verdict 和分项 evidence，是 repair-agent 理解失败现象的主要结构化信号 |
| `symptom` | 对失败现象的文字摘要。它描述“哪里没通过”，不描述“应该怎么修” |
| `evidence` | 支撑评测结论的证据列表，例如执行错误、schema mismatch、结果不匹配、结构意图不一致 |

它的意义是：把 testing-agent 已经观察到的失败事实稳定传给 repair-agent。repair-agent 可以基于它判断失败是否属于 knowledge-agent 知识包缺口，但不需要重新跑 testing-agent 的评测流程，也不把 testing-agent 评测器问题包装成知识修复建议。四个维度的具体评测方法在第 3 章展开。

### 2.6 `IssueTicket`

`IssueTicket` 表示 testing-agent 提交给 repair-agent 的失败问题单。

它只在最终 `verdict` 不是 `pass` 时生成。

它包含：

| 字段 | 含义 |
| --- | --- |
| `ticket_id` | 问题单唯一 ID |
| `id` | QA 样本主键 |
| `difficulty` | 题目难度 |
| `question` | 原始自然语言问题 |
| `expected` | 黄金 Cypher 与黄金答案 |
| `actual` | cypher-generator-agent 生成 Cypher 与实际执行结果 |
| `evaluation` | testing-agent 生成的评测结论。来源是本次评测流程中的执行结果、规则评测结果和可选 LLM 复评结果 |
| `generation_evidence` | cypher-generator-agent 生成过程证据。来源是 cypher-generator-agent 提交的 `EvaluationSubmissionRequest`，testing-agent 只负责保存、关联 attempt，并写入问题单 |
| `diagnostic_summary` | testing-agent 从 `evaluation`、执行事实和 expected/actual 差异中派生的失败现象诊断摘要。它是 repair-agent 优先消费的诊断合同 |
| `input_prompt_snapshot` | prompt 快照兼容字段 |

它的意义是：把失败样本、评测证据、生成证据和失败现象诊断摘要交给 repair-agent，用于判断是否需要修复 knowledge-agent 知识包以及该修哪类知识。若问题指向 cypher-generator-agent 协议、解析、守门或 testing-agent 评测器，IssueTicket 只提供排障证据，不应被解释为 knowledge-agent 应修复的知识缺口。`diagnostic_summary` 的完整字段定义见 [9. diagnostic_summary 契约](#9-diagnostic_summary-契约)。

### 2.7 `GenerationEvidence`

`GenerationEvidence` 表示 cypher-generator-agent 生成过程在问题单中的证据快照。

它的来源是 cypher-generator-agent 提交给 testing-agent 的 `EvaluationSubmissionRequest`。testing-agent 不重新生成这些字段，只在接收 submission 时保存，并在生成 IssueTicket 时复制到 `generation_evidence`。

它和 `evaluation` 的区别是：

- `evaluation` 是 testing-agent 对生成结果的评测产物。
- `generation_evidence` 是 cypher-generator-agent 在生成阶段留下的过程证据。
- `generation_evidence` 不参与 testing-agent 主评测打分，但会帮助 repair-agent 区分失败是否来自 knowledge-agent 知识包缺口，还是来自 cypher-generator-agent 生成链路工程问题。

它包含：

| 字段 | 含义 |
| --- | --- |
| `generation_run_id` | cypher-generator-agent 本次生成运行 ID。它标识一次 cypher-generator-agent 调用，用于把问题单和 cypher-generator-agent 日志、prompt snapshot、模型输出串起来 |
| `attempt_no` | testing-agent 记录的尝试序号。它不是 cypher-generator-agent 提交的字段，而是 testing-agent 接收 submission 后按同一 `id` 的历史记录分配 |
| `parse_summary` | cypher-generator-agent 解析摘要，说明 `generated_cypher` 是直接从模型输出得到，还是从 JSON、代码块或兜底恢复中提取。它用于分析失败是否来自解析/恢复环节；若是，则属于 cypher-generator-agent 工程缺陷，不应转成 knowledge-agent 知识修复建议；它不参与主评测打分 |
| `guardrail_summary` | cypher-generator-agent 守门摘要，说明 cypher-generator-agent 最小守门是否放行该 Cypher。它用于判断 cypher-generator-agent 是否漏放了明显格式、安全或只读约束问题；若是，则属于 cypher-generator-agent 工程缺陷，不应转成 knowledge-agent 知识修复建议；它不代表业务正确 |
| `raw_output_snapshot` | 模型原始输出快照，用于回放 LLM 实际返回内容，并和最终 `generated_cypher` 对照 |
| `input_prompt_snapshot` | prompt 快照，用于 repair-agent 分析 knowledge-agent 知识包、few-shot 和上下文是否诱发生成失败；cypher-generator-agent 固定生成协议部分不属于业务修复目标 |

它的意义是：保留一条足够完整但不臃肿的生成证据链，让 repair-agent 可以追溯失败发生前 cypher-generator-agent 到底看到了什么、提取了什么、放行了什么，并据此避免把 cypher-generator-agent 工程链路问题误判为 knowledge-agent 知识包缺口。

### 2.8 `ImprovementAssessment`

`ImprovementAssessment` 表示 testing-agent 对多轮尝试的改进评估。

它只比较同一个 `id` 下相邻两轮 attempt：当前 `attempt_no` 与 `attempt_no - 1`。它不是单次评测指标，也不进入 IssueTicket；它用于观察 repair-agent 修复后，下一轮 cypher-generator-agent 生成结果是否比上一轮更好。

它的来源是 testing-agent 已保存的前后两轮 `EvaluationSummary`。testing-agent 不调用 LLM 来判断改进，也不让 repair-agent 自评修复效果。

核心原则：`ImprovementAssessment` 不能使用一套不同于评测流程的新标准，也不输出额外的总体 `status`。它只做“同一评测标准下的前后差分”：上一轮 `EvaluationSummary` 与当前轮 `EvaluationSummary` 的四个评测维度如何变化。

它包含：

| 字段 | 含义 |
| --- | --- |
| `qa_id` | 被比较的 QA 样本 ID |
| `current_attempt_no` | 当前轮 attempt 编号，由 testing-agent 分配 |
| `previous_attempt_no` | 被比较的上一轮 attempt 编号。首轮时为空 |
| `summary_zh` | 面向控制台展示的中文摘要 |
| `dimensions` | 四个评测维度的前后变化 |
| `highlights` | 从前后两轮 evidence 差异中提取的变化摘要 |
| `evidence` | 前后两轮评测 evidence 的截断集合，最多保留 6 条 |

改进维度：

| 维度 | 比较对象 | 判定规则 |
| --- | --- | --- |
| `syntax_validity_change` | 四维评测中的 `syntax_validity` | 从 `fail` 到 `pass` 为 `improved`，从 `pass` 到 `fail` 为 `regressed`，相同为 `unchanged` |
| `schema_alignment_change` | 四维评测中的 `schema_alignment` | 从 `fail` 到 `pass` 为 `improved`，从 `pass` 到 `fail` 为 `regressed`，相同为 `unchanged` |
| `result_correctness_change` | 四维评测中的 `result_correctness` | 从 `fail` 到 `pass` 为 `improved`，从 `pass` 到 `fail` 为 `regressed`，相同为 `unchanged` |
| `question_alignment_change` | 四维评测中的 `question_alignment` | 从 `fail` 到 `pass` 为 `improved`，从 `pass` 到 `fail` 为 `regressed`，相同为 `unchanged` |

维度变化取值：

| 取值 | 含义 |
| --- | --- |
| `improved` | 该维度从 `fail` 变为 `pass` |
| `regressed` | 该维度从 `pass` 变为 `fail` |
| `unchanged` | 该维度前后状态相同 |
| `not_comparable` | 缺少上一轮或当前轮该维度的评测结果，无法比较 |

它的意义是：辅助观察修复闭环是否让后续生成变好。它不参与单次评测的 verdict，也不替代 repair-agent 根因分析。

## 3. 评测流程与指标总览

本章先讲 testing-agent 如何完成评测。读者应先理解评测流程和指标含义，再阅读后续数据结构与责任边界。

### 3.1 评测主链路

testing-agent 的评测从“同一 `id` 下 golden 与 submission 都到齐”开始。

```text
golden + submission
  -> 执行 generated_cypher
  -> 生成 TuGraphExecutionResult
  -> 运行规则评测
  -> 生成 EvaluationSummary
  -> 如果 verdict != pass，且 LLM 可用，执行 LLM 语义复评
  -> 重算 verdict
  -> pass: 标记 submission passed
  -> fail/partial_fail: 生成 IssueTicket，提交 repair-agent
```

每一步的意义：

| 步骤 | 输入 | 输出 | 意义 |
| --- | --- | --- | --- |
| 配对 | `QAGoldenRequest`、`EvaluationSubmissionRequest` | ready pair | 确保评测同时拥有标准答案和生成结果 |
| 执行 | `generated_cypher` | `TuGraphExecutionResult` | 用真实执行事实替代纯文本猜测 |
| 规则评测 | question、golden、actual、execution | dimensions、metrics、evidence | 生成可复现、可解释的基础评测 |
| LLM 复评 | 规则失败样本与语义材料 | 语义维度修正 | 处理规则可能误判的语义等价情况 |
| 失败票据 | 最终非 pass 的评测结果 | `IssueTicket` | 把失败事实交给 repair-agent 做根因分析 |

### 3.2 四维评测框架

规则评测把一次生成结果拆成四个维度。四个维度不是并列的自然语言判断，而是由执行事实、Cypher 结构和结果集比较共同产生的评测框架。

| 维度 | 要回答的问题 | 输入来源 | 输出 |
| --- | --- | --- | --- |
| `syntax_validity` | 这条 Cypher 能不能执行？ | `TuGraphExecutionResult.success`、`error_message` | score、pass/fail、执行证据 |
| `schema_alignment` | 这条 Cypher 有没有用对图谱结构？ | expected/actual Cypher 的 label、relation、property | score、pass/fail、schema 证据 |
| `result_correctness` | 执行结果是否等价于 golden answer？ | expected answer、actual rows | precision、recall、F1、pass/fail |
| `question_alignment` | 查询结构意图是否和 question/golden 对齐？ | question、expected/actual Cypher、expected/actual row shape | 子项分数、pass/fail、结构意图证据 |

当前代码字段名是 `question_alignment`。它实际更接近 `query_intent_alignment`：它检查的是实体、关系、过滤、聚合、投影、排序和 limit 等查询结构意图，而不是完整自然语言语义理解。

### 3.3 `syntax_validity` 如何评测

输入：

```text
TuGraphExecutionResult.success
TuGraphExecutionResult.error_message
```

规则：

| 条件 | score | 含义 |
| --- | ---: | --- |
| 执行成功且无错误信息 | 1.0 | Cypher 可执行 |
| 执行失败，但错误不明显是 syntax error | 0.5 | 语法可能可解析，但执行失败 |
| 错误信息包含 syntax | 0.0 | 明确语法失败 |

输出字段：

| 字段 | 含义 |
| --- | --- |
| `parse_success` | 错误信息是否不像语法错误 |
| `execution_success` | TuGraph 是否成功执行 |
| `evidence` | 执行失败或语法错误时的证据文本 |

### 3.4 `schema_alignment` 如何评测

`schema_alignment` 判断的是：actual Cypher 有没有使用和 golden Cypher 相近的图谱结构，以及有没有使用当前 schema 不存在的 label 或 relation。

这里的 schema 不是自然语言知识，而是图谱结构元素：

| 术语 | 含义 | Cypher 示例 | 抽取结果 |
| --- | --- | --- | --- |
| label | 节点类型 | `(p:Protocol)`、`(t:Tunnel)` | `Protocol`、`Tunnel` |
| relation | 关系类型 | `[:TUNNEL_PROTO]` | `TUNNEL_PROTO` |
| property | 节点或关系属性名 | `p.name`、`t.id` | `name`、`id` |

输入：

```text
expected_cypher
actual_cypher
execution.error_message
```

规则：

1. 从 expected 与 actual Cypher 中抽取 label、relation、property。
2. 分别比较 actual 集合与 expected 集合，得到 `label_match_score`、`relation_match_score`、`property_match_score`。
3. 如果 actual 使用了当前 schema 外的 label/relation，相关分数归零。
4. 如果 TuGraph 错误信息包含 schema、label、property，也记录 schema evidence。

集合比较方式：

testing-agent 把 expected 里出现的结构元素看作“应该用到的结构”，把 actual 里出现的结构元素看作“实际用到的结构”。比较时会先去重，所以同一个 label 出现多次只算一次。

```text
true_positive = actual 与 expected 的交集数量
precision = true_positive / actual 数量
recall = true_positive / expected 数量
F1 = 2 * precision * recall / (precision + recall)
```

这些术语在这里的含义是：

| 术语 | 在 schema_alignment 里的意思 |
| --- | --- |
| precision | actual 用到的结构里，有多少是 expected 也用到的。它惩罚“多用了不该用的 label/relation/property” |
| recall | expected 用到的结构里，有多少被 actual 覆盖到了。它惩罚“漏用了应该用的 label/relation/property” |
| F1 | precision 和 recall 的折中。只有“少乱用”和“少漏用”都表现好时，F1 才高 |

例子：

```text
expected labels = {Protocol, Tunnel}
actual labels   = {Protocol, Service}

交集 = {Protocol}
precision = 1 / 2 = 0.5
recall    = 1 / 2 = 0.5
F1        = 2 * 0.5 * 0.5 / (0.5 + 0.5) = 0.5
```

这表示 actual 没有完全偏离 schema，但它漏掉了 `Tunnel`，同时多用了 `Service`，所以 label 匹配分只有 0.5。

综合分：

```text
score = 0.3 * label_match_score
      + 0.4 * relation_match_score
      + 0.3 * property_match_score
```

当前 schema 合法性基于 `network_schema_v10` 的固定 label/relation 集合。后续多 schema/profile 需要把它抽成 profile 输入。

### 3.5 `result_correctness` 如何评测

输入：

```text
expected_answer
actual execution rows
question / expected_cypher 中的排序要求
```

规则：

1. 规范化 expected answer 与 actual rows。
2. 如果问题或 golden Cypher 有排序要求，按顺序比较。
3. 否则按集合计数比较，允许结果顺序不同。
4. 计算 precision、recall、F1。

规范化步骤：

testing-agent 不直接拿 Python 对象或原始 JSON 文本做字符串比较，而是先把 expected 和 actual 统一成可稳定比较的行列表。

| 步骤 | 做什么 | 目的 |
| --- | --- | --- |
| JSON 递归解析 | 如果某个字段是 JSON 字符串，例如 `"{\"id\":\"1\"}"` 或 `"[...]"`，会尝试解析成对象或数组，并递归处理里面的值 | 避免“同一个结构一个是字符串、一个是对象”导致误判 |
| dict key 排序 | 对象字段按 key 排序后再序列化 | 避免 `{a:1,b:2}` 和 `{b:2,a:1}` 因字段顺序不同被判成不同 |
| list 递归处理 | 数组里的每个元素都执行同样的规范化 | 保证嵌套结果也可比较 |
| 图实体识别 | 如果某个值是 TuGraph 风格实体，包含 `label` 且包含 `identity` 或 `properties`，会识别为 graph entity | 区分“返回了一个图节点/边”和“返回了普通标量字段” |
| 行语义规范化 | 每一行分成标量字段与图实体。标量字段保留原字段名；图实体统一放入 `__graph_entities__`，并按 canonical JSON 排序 | 减少返回别名或实体顺序差异带来的噪声 |
| canonical JSON | 每行最终序列化成 `sort_keys=true` 的 JSON 字符串 | 让后续精确匹配、Counter 计数和 evidence 输出稳定 |

例子：

```json
{
  "t": {"label": "Tunnel", "identity": 1, "properties": {"name": "T1"}},
  "protocol": "SRv6"
}
```

会被规范化成类似：

```json
{
  "protocol": "SRv6",
  "__graph_entities__": [
    "{\"identity\":1,\"label\":\"Tunnel\",\"properties\":{\"name\":\"T1\"}}"
  ]
}
```

这样做的意义是：`result_correctness` 关注“返回结果语义是否一致”，不是关注 JSON 字段顺序、对象 key 顺序、图实体在行内的排列顺序这些表现层差异。

排序处理：

- 如果问题或 golden Cypher 表明结果有顺序要求，例如包含 `ORDER BY`，或问题里出现“排序、升序、降序、前、top、最高、最低”等提示，则 `order_sensitive=true`，规范化后的行列表必须逐项同序相等。
- 如果没有顺序要求，则使用 `Counter` 比较规范化后的行集合。也就是说，行顺序可以不同，但重复行的数量仍然会被计入。

综合分：

```text
score = 0.3 * execution_match_score
      + 0.7 * result_set_f1
```

字段含义：

| 字段 | 含义 |
| --- | --- |
| `execution_match_score` | actual rows 是否与 expected answer 完全匹配 |
| `result_set_precision` | actual 返回结果中有多少属于 expected |
| `result_set_recall` | expected 结果中有多少被 actual 找到 |
| `result_set_f1` | precision 与 recall 的综合 |
| `order_sensitive` | 是否按顺序比较结果 |

### 3.6 `question_alignment` 如何评测

输入：

```text
question
expected_cypher
actual_cypher
expected_answer
actual execution rows
```

当前规则：

| 子指标 | 含义 | 来源 |
| --- | --- | --- |
| `entity_match_score` | 查询实体类型是否一致 | expected/actual label 集合 F1 |
| `relation_path_match_score` | 查询关系路径是否一致 | expected/actual relation 集合 F1 |
| `filter_match_score` | WHERE 与过滤属性是否一致 | WHERE 存在性与 property 集合 |
| `aggregation_match_score` | 聚合意图是否一致 | count/sum/avg/min/max 存在性 |
| `projection_match_score` | 返回结构是否一致 | expected answer 与 actual rows 的语义键 |
| `ordering_limit_match_score` | ORDER BY / LIMIT 是否一致 | question、expected_cypher、actual_cypher |

综合分：

```text
score = 六个子指标的平均值
```

边界：

- 这是规则化的查询结构意图对齐检查。
- 它不是完整自然语言语义理解。
- 后续契约中建议将其改名或解释为 `query_intent_alignment`。

### 3.7 dimensions、metrics、verdict 的关系

每个维度先产出 `metrics`，再由 `score` 转换为 `dimensions`。字段含义见 [5.1 verdict 与 dimensions](#51-verdict-与-dimensions)，细粒度 metrics 字段见 [5.3](#53-syntax_validity-metrics) 到 [5.6](#56-question_alignment--query_intent_alignment-metrics)。

```text
score >= 0.95 -> 该维度 pass
score < 0.95  -> 该维度 fail
```

最终 `verdict`：

```text
四个维度全 pass -> pass
syntax_validity fail -> fail
四个维度全 fail -> fail
其他 -> partial_fail
```

`overall_score` 是四维加权总分，用于表达总体质量，但不单独决定 `verdict`。权重定义见 [5.2 overall_score](#52-overall_score)。

### 3.8 LLM 语义复评在流程中的位置

LLM 复评位于规则评测之后，只在规则评测未通过且 LLM 客户端已配置时触发。

```text
规则评测 -> 如果 verdict != pass -> 可选 LLM 语义复评 -> 重算语义维度与 verdict
```

完整触发条件、输入输出和边界见 [6. LLM 语义复评](#6-llm-语义复评)。这里保留流程位置，避免和第 6 章重复。

## 4. 当前运行流程

### 4.1 总流程

```text
QAGoldenRequest
  -> 保存 golden
  -> 如果 submission 已存在，进入评测

EvaluationSubmissionRequest
  -> 保存 submission
  -> 如果 golden 已存在，进入评测

评测
  -> 执行 generated_cypher
  -> 规则评测
  -> 可选 LLM 语义复评
  -> 生成 EvaluationSummary
  -> pass: 标记 passed
  -> fail/partial_fail: 生成 IssueTicket 并投递 repair-agent
```

### 4.2 步骤 1：接收 golden

接口：

```text
POST /api/v1/qa/goldens
```

输入结构：

```json
{
  "id": "qa-001",
  "cypher": "MATCH (t:Tunnel) RETURN t LIMIT 5",
  "answer": [{"t": {"label": "Tunnel", "properties": {"id": "tun-1"}}}],
  "difficulty": "L3"
}
```

字段含义：

| 字段 | 含义 | 作用 |
| --- | --- | --- |
| `id` | QA 样本主键 | 用于和 cypher-generator-agent submission 配对 |
| `cypher` | 黄金 Cypher | 作为结构评测和 expected/actual diff 的基准 |
| `answer` | 黄金答案 | 作为结果正确性评测的基准 |
| `difficulty` | 难度，`L1` 到 `L8` | 供问题单和后续分析理解样本复杂度 |

输出：

如果 submission 尚未到达：

```json
{
  "id": "qa-001",
  "status": "received_golden_only"
}
```

如果 submission 已到达，则直接进入评测，并返回评测处理结果。

### 4.3 步骤 2：接收 submission

接口：

```text
POST /api/v1/evaluations/submissions
```

输入结构：

```json
{
  "id": "qa-001",
  "question": "查询前 5 条隧道信息",
  "generation_run_id": "gen-001",
  "generated_cypher": "MATCH (t:Tunnel) RETURN t.id, t.name LIMIT 2",
  "parse_summary": "parsed_json_field",
  "guardrail_summary": "accepted",
  "raw_output_snapshot": "{\"cypher\":\"MATCH ...\"}",
  "input_prompt_snapshot": "..."
}
```

字段含义：

| 字段 | 含义 | 作用 |
| --- | --- | --- |
| `id` | QA 样本主键 | 和 golden 按同一 `id` 配对 |
| `question` | 用户原始自然语言问题 | 供 query intent 评测和 repair-agent 分析使用 |
| `generation_run_id` | cypher-generator-agent 本轮生成 ID | 追踪 cypher-generator-agent 生成过程 |
| `generated_cypher` | cypher-generator-agent 生成的 Cypher | testing-agent 实际执行和评测的对象 |
| `parse_summary` | cypher-generator-agent 解析模型输出的摘要 | 不参与主评测打分；用于失败分析时判断 Cypher 是模型直接输出、JSON 字段解析、还是兜底恢复得到 |
| `guardrail_summary` | cypher-generator-agent 守门摘要 | 不参与主评测打分；用于失败分析时判断 cypher-generator-agent 是否漏放了明显风险或格式问题 |
| `raw_output_snapshot` | 模型原始输出快照 | 不参与主评测打分；用于追溯模型输出与最终 Cypher 是否一致 |
| `input_prompt_snapshot` | 本轮生成使用的 prompt 快照 | 不参与主评测打分；主要供 repair-agent 分析 knowledge-agent 知识包、few-shot 和上下文是否诱发失败；cypher-generator-agent 固定生成协议不属于业务修复目标 |

输出：

如果 golden 尚未到达：

```json
{
  "id": "qa-001",
  "status": "waiting_for_golden"
}
```

如果 golden 已到达，则进入评测。

接收 submission 时，testing-agent 会为该 `id` 分配当前 `attempt_no`。首个 submission 记为 1；同一 `id` 的后续生成结果按 testing-agent 已保存的 attempt 历史递增。cypher-generator-agent 不需要、也不应该判断当前是第几次尝试。

### 4.4 步骤 3：执行 generated Cypher

输入：

```text
generated_cypher
TuGraph connection settings
```

输出结构：

```json
{
  "success": true,
  "rows": [{"id": "tun-1", "name": "Tunnel 1"}],
  "row_count": 1,
  "error_message": null,
  "elapsed_ms": 12
}
```

字段含义：

| 字段 | 含义 | 作用 |
| --- | --- | --- |
| `success` | TuGraph 是否执行成功 | 决定 syntax/execution 事实 |
| `rows` | 实际返回结果 | 和 golden answer 比较 |
| `row_count` | 返回行数 | 识别空结果、少召回、多召回 |
| `error_message` | 执行错误 | 识别 syntax、schema、执行环境问题 |
| `elapsed_ms` | 执行耗时 | 当前主要是运行证据，未来可用于性能诊断 |

意义：

testing-agent 的评测不是只看 Cypher 文本，而是以真实执行结果为事实基础。执行失败不会中断评测，而是转化为评测证据。

### 4.5 步骤 4：规则评测

规则评测输入：

```text
question
expected_cypher
expected_answer
actual_cypher
execution_result
```

规则评测输出：

```json
{
  "verdict": "partial_fail",
  "dimensions": {
    "syntax_validity": "pass",
    "schema_alignment": "pass",
    "result_correctness": "fail",
    "question_alignment": "fail"
  },
  "overall_score": 0.57,
  "metrics": {},
  "symptom": "Generated Cypher is plausible but returned data inconsistent with the golden answer.",
  "evidence": ["Result mismatch: expected_rows=...; actual_rows=..."]
}
```

这个输出就是 `EvaluationSummary`。结构定义见 [2.5 EvaluationSummary](#25-evaluationsummary)，`dimensions` 与 `metrics` 字段细节见 [5. 评测指标详细字段表](#5-评测指标详细字段表)。

## 5. 评测指标详细字段表

### 5.1 verdict 与 dimensions

`dimensions` 是四个维度的 pass/fail：

| 维度 | 含义 | 当前判定方式 |
| --- | --- | --- |
| `syntax_validity` | 生成 Cypher 是否可执行 | 来自 TuGraph 执行成功与错误信息 |
| `schema_alignment` | Cypher 是否符合图谱 schema，并和 golden 使用相近结构 | 比较 label、relation、property，检查非法 label/relation |
| `result_correctness` | 执行结果是否匹配 golden answer | 比较 actual rows 与 expected answer |
| `question_alignment` | 查询结构意图是否和 question/golden 对齐 | 比较实体、关系、过滤、聚合、投影、排序/limit |

最终 `verdict` 汇总规则见 [3.7 dimensions、metrics、verdict 的关系](#37-dimensionsmetricsverdict-的关系)。

### 5.2 overall_score

`overall_score` 是四维加权总分：

| 维度 | 权重 |
| --- | ---: |
| `syntax_validity` | 0.15 |
| `schema_alignment` | 0.20 |
| `result_correctness` | 0.40 |
| `question_alignment` | 0.25 |

它用于表达总体质量，但不单独决定 `verdict`。例如语法失败会直接导致 `fail`，即使其他维度分数较高。

### 5.3 syntax_validity metrics

结构：

```json
{
  "score": 1.0,
  "verdict": "pass",
  "parse_success": true,
  "execution_success": true,
  "evidence": []
}
```

字段含义：

| 字段 | 含义 | 来源 |
| --- | --- | --- |
| `score` | 0 到 1 的语法/执行分数 | 根据 execution success 与 syntax error 计算 |
| `verdict` | `pass` / `partial` / `fail` | 由 score 转换 |
| `parse_success` | 错误信息是否不像语法错误 | `error_message` 文本判断 |
| `execution_success` | TuGraph 是否成功执行 | `execution.success` 且无错误 |
| `evidence` | 失败证据 | 执行失败或语法错误时生成 |

### 5.4 schema_alignment metrics

结构：

```json
{
  "score": 0.96,
  "verdict": "pass",
  "label_match_score": 1.0,
  "relation_match_score": 1.0,
  "property_match_score": 0.87,
  "evidence": []
}
```

字段含义：

| 字段 | 含义 | 来源 |
| --- | --- | --- |
| `label_match_score` | actual 与 expected label 集合的 F1。actual 多用了 label 会降低 precision，漏用了 expected label 会降低 recall | 从 Cypher 中抽取 `(:Label)` |
| `relation_match_score` | actual 与 expected relation 集合的 F1。actual 多用了 relation 会降低 precision，漏用了 expected relation 会降低 recall | 从 Cypher 中抽取 `[:REL]` |
| `property_match_score` | actual 与 expected property 集合的 F1。actual 多返回或多过滤属性会降低 precision，漏掉 golden 中使用的属性会降低 recall | 从 Cypher 中抽取 `alias.property` |
| `score` | schema 综合分 | `0.3 * label + 0.4 * relation + 0.3 * property` |
| `evidence` | schema 失败证据 | 非法 label/relation 或 schema error |

F1、precision、recall 的定义和示例见 [3.4 schema_alignment 如何评测](#34-schema_alignment-如何评测)。如果 actual 和 expected 都没有某类元素，例如都没有显式 property，则该类匹配分记为 1.0，表示这一类没有 schema 差异。

当前 schema 合法性约束见 [3.4 schema_alignment 如何评测](#34-schema_alignment-如何评测)。

### 5.5 result_correctness metrics

结构：

```json
{
  "score": 0.57,
  "verdict": "partial",
  "execution_match_score": 0.0,
  "result_set_precision": 1.0,
  "result_set_recall": 0.4,
  "result_set_f1": 0.57,
  "order_sensitive": false,
  "evidence": ["expected_rows=...; actual_rows=..."]
}
```

字段含义：

| 字段 | 含义 | 来源 |
| --- | --- | --- |
| `execution_match_score` | actual rows 是否与 expected answer 完全匹配 | 规范化后比较 rows |
| `result_set_precision` | actual 返回中有多少是 expected 里的结果 | rows 集合计数 |
| `result_set_recall` | expected 结果中有多少被 actual 找到 | rows 集合计数 |
| `result_set_f1` | precision 与 recall 的 F1 | 公式计算 |
| `order_sensitive` | 是否按顺序比较 | question 或 golden Cypher 有排序要求时为 true |
| `score` | 结果正确性综合分 | `0.3 * execution_match_score + 0.7 * result_set_f1` |
| `evidence` | 结果不匹配证据 | 非完全匹配时生成 |

rows 规范化、Counter 计数、顺序敏感规则和规则层边界见 [3.5 result_correctness 如何评测](#35-result_correctness-如何评测)。

意义：

这个维度回答：实际执行结果是否等价于黄金答案。它是当前权重最高的维度。

### 5.6 question_alignment / query_intent_alignment metrics

结构：

```json
{
  "score": 0.67,
  "verdict": "partial",
  "entity_match_score": 1.0,
  "relation_path_match_score": 1.0,
  "filter_match_score": 1.0,
  "aggregation_match_score": 1.0,
  "projection_match_score": 0.0,
  "ordering_limit_match_score": 0.0,
  "evidence": ["Projection shape mismatch: expected_keys=..."]
}
```

字段含义：

| 字段 | 含义 | 来源 |
| --- | --- | --- |
| `entity_match_score` | actual 与 expected 查询实体类型是否一致 | label 集合 F1 |
| `relation_path_match_score` | actual 与 expected 关系路径是否一致 | relation 集合 F1 |
| `filter_match_score` | WHERE 与过滤属性是否一致 | WHERE 存在性与 property 集合 |
| `aggregation_match_score` | 聚合意图是否一致 | count/sum/avg/min/max 存在性 |
| `projection_match_score` | 返回结构是否一致 | expected answer 与 actual rows 的语义键 |
| `ordering_limit_match_score` | 排序与 limit 是否一致 | ORDER BY / LIMIT 规则 |
| `score` | 查询意图结构对齐综合分 | 六项平均 |
| `evidence` | 结构意图偏差证据 | 关系重叠低、实体重叠低、投影形状不一致等 |

边界说明见 [3.6 question_alignment 如何评测](#36-question_alignment-如何评测)。`question_alignment` 当前不是完整自然语言语义理解，而是规则化的查询意图结构检查。

## 6. LLM 语义复评

### 6.1 触发条件

LLM 复评只在以下情况下触发：

```text
rule_based_verdict != pass
并且 llm_client 已配置
```

如果规则评测已经 `pass`，不调用 LLM。

### 6.2 输入

```json
{
  "question": "查询前 5 条隧道信息",
  "expected_cypher": "MATCH ...",
  "expected_answer": [],
  "actual_cypher": "MATCH ...",
  "actual_result": [],
  "rule_based_verdict": "partial_fail",
  "rule_based_dimensions": {
    "syntax_validity": "pass",
    "schema_alignment": "pass",
    "result_correctness": "fail",
    "question_alignment": "fail"
  }
}
```

字段含义：

| 字段 | 含义 |
| --- | --- |
| `question` | 原始问题，用于判断自然语言目标 |
| `expected_cypher` | 黄金查询 |
| `expected_answer` | 黄金答案 |
| `actual_cypher` | cypher-generator-agent 生成查询 |
| `actual_result` | 实际执行结果 |
| `rule_based_verdict` | 规则裁决 |
| `rule_based_dimensions` | 规则四维结论 |

### 6.3 输出

```json
{
  "result_correctness": "pass",
  "question_alignment": "fail",
  "reasoning": "Actual rows are semantically equivalent despite field alias differences.",
  "confidence": 0.82
}
```

字段含义：

| 字段 | 含义 | 是否影响最终评测 |
| --- | --- | --- |
| `result_correctness` | LLM 对结果语义等价的判断 | 可把该维度从 fail 修正为 pass |
| `question_alignment` | LLM 对查询是否回答问题的判断 | 可把该维度从 fail 修正为 pass |
| `reasoning` | LLM 的解释文本 | 追加到 evidence |
| `confidence` | LLM 自报置信度 | 当前只记录日志，不作为 testing-agent 自身置信度 |

边界：

- LLM 不修正 `syntax_validity`。
- LLM 不修正 `schema_alignment`。
- LLM 不生成修复建议。
- LLM 只用于语义等价复核。

## 7. Evidence 生成规则

`evaluation.evidence` 由规则评测和 LLM 复评共同产生。

规则 evidence 来源：

| 来源 | 生成条件 | 示例 |
| --- | --- | --- |
| syntax metrics | 执行失败或语法错误 | `Execution failed or syntax invalid: ...` |
| schema metrics | 非法 label/relation 或 schema error | `Actual Cypher contains labels or relations outside network_schema_v10: ...` |
| result metrics | 结果未完全匹配 | `Result mismatch: expected_rows=...; actual_rows=...` |
| question alignment metrics | 结构意图偏差 | `Projection shape mismatch: expected_keys=...` |

LLM evidence 来源：

```text
[LLM override] result_correctness flipped to pass: ...
[LLM override] question_alignment flipped to pass: ...
```

约束：

- `evidence` 是评测证据，不是修复建议。
- `evidence_preview` 如果引入，应从 `evaluation.evidence` 中截取或排序，不应由 LLM 编造。

## 8. IssueTicket 当前契约

当前 testing-agent 失败时向 repair-agent 投递 `IssueTicket`。

当前结构：

```json
{
  "ticket_id": "ticket-qa-001-attempt-1",
  "id": "qa-001",
  "difficulty": "L3",
  "question": "查询前 5 条隧道信息",
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
    "dimensions": {},
    "overall_score": 0.57,
    "metrics": {},
    "symptom": "...",
    "evidence": []
  },
  "generation_evidence": {
    "generation_run_id": "gen-001",
    "attempt_no": 1,
    "parse_summary": "parsed_json_field",
    "guardrail_summary": "accepted",
    "raw_output_snapshot": "{\"cypher\":\"MATCH ...\"}",
    "input_prompt_snapshot": "..."
  },
  "diagnostic_summary": {
    "failure_classes": ["result_correctness", "query_intent_alignment"],
    "primary_failure_class": "query_intent_alignment",
    "severity": "high",
    "dimension_signals": {},
    "failure_diff": {},
    "diagnostic_tags": ["projection_mismatch", "limit_mismatch"],
    "evidence_preview": []
  },
  "input_prompt_snapshot": "..."
}
```

字段含义：

| 字段 | 含义 | repair-agent 中的作用 |
| --- | --- | --- |
| `ticket_id` | 问题单唯一 ID | 幂等、落库、关联分析记录 |
| `id` | QA 样本 ID | 关联 cypher-generator-agent prompt snapshot 与全链路记录 |
| `difficulty` | 样本难度 | 帮助 repair-agent 判断失败是否和复杂度相关 |
| `question` | 原始问题 | 判断 actual 是否回答了用户问题 |
| `expected.cypher` | 黄金查询 | expected/actual diff 的主要参照 |
| `expected.answer` | 黄金答案 | 结果正确性与语义等价判断 |
| `actual.generated_cypher` | 实际生成查询 | repair-agent 分析失败对象 |
| `actual.execution` | 执行事实 | 判断语法、执行、结果规模问题 |
| `evaluation` | testing-agent 评测结果，包含 `verdict`、四维 `dimensions`、`overall_score`、详细 `metrics`、`symptom` 和 `evidence` | repair-agent 用它理解失败类型、失败维度和 testing-agent 已观察到的证据 |
| `generation_evidence` | cypher-generator-agent 生成过程证据，包含 `generation_run_id`、testing-agent 分配的 `attempt_no`、`parse_summary`、`guardrail_summary`、`raw_output_snapshot`、`input_prompt_snapshot` | repair-agent 用它区分 knowledge-agent 知识包缺口与 cypher-generator-agent 工程链路问题；cypher-generator-agent 协议、解析和守门问题不进入 knowledge-agent 修复建议 |
| `diagnostic_summary` | testing-agent 从评测结果、执行事实和 expected/actual 差异中派生的失败现象诊断摘要 | repair-agent 优先消费它，减少重复解析 metrics；字段定义见 [9. diagnostic_summary 契约](#9-diagnostic_summary-契约) |
| `input_prompt_snapshot` | prompt 快照兼容字段 | 历史问题单兜底证据；repair-agent 主流程优先使用 `generation_evidence.input_prompt_snapshot` |

兼容说明：

- `evaluation.metrics` 仍随 `IssueTicket` 保留，用于审计、回放和未来扩展。
- repair-agent 主流程应优先消费 `diagnostic_summary`；如果历史问题单没有该字段，repair-agent 才回退到从 `evaluation` 与 expected/actual 中派生诊断上下文。

## 9. diagnostic_summary 契约

为避免字段堆砌，testing-agent 在 `IssueTicket` 中输出 `diagnostic_summary`。这个结构表达的是“失败现象诊断”，不是修复策略。

### 9.1 生成原则

1. 每个字段必须说明生成来源。
2. 每个枚举值必须说明含义。
3. testing-agent 不输出根因置信度。
4. testing-agent 不输出修复目标 hint。
5. 没有真实存储/API 支撑前，不设计虚拟 artifact URI。
6. 完整证据链通过真实主键追溯：`id`、`attempt_no`、`generation_run_id`、`ticket_id`。

### 9.2 diagnostic_summary 结构

```json
{
  "failure_classes": ["result_correctness", "query_intent_alignment"],
  "primary_failure_class": "query_intent_alignment",
  "severity": "high",
  "dimension_signals": {},
  "failure_diff": {},
  "diagnostic_tags": ["projection_mismatch", "limit_mismatch"],
  "evidence_preview": []
}
```

字段含义：

| 字段 | 含义 | 来源 | 边界 |
| --- | --- | --- | --- |
| `failure_classes` | 失败类别列表，可同时包含多个类别 | 从 failed dimensions 与 failure_diff 派生 | 描述失败现象，不描述修复原因；不使用 `mixed` 吞掉信息 |
| `primary_failure_class` | 主失败类别，可选 | 从 `failure_classes` 中按严重性或主导信号选择 | 只用于排序、展示或摘要，不代表其他类别不存在 |
| `severity` | 失败严重度 | 从 verdict、syntax、schema、result_delta 派生 | 用于优先级，不等于 root cause |
| `dimension_signals` | 每个维度的关键指标摘要 | 从 metrics 提炼 | 不透传完整 metrics 树 |
| `failure_diff` | expected/actual 的结构差异 | 从 Cypher、rows、metrics 派生 | 机器可消费的失败事实 |
| `diagnostic_tags` | 中性诊断标签 | 从 failure_diff 派生 | 不能写修复目标 |
| `evidence_preview` | 关键证据摘要 | 从 evaluation.evidence 截取 | 不由 LLM 编造 |

### 9.3 severity 取值

| 取值 | 含义 | 示例 |
| --- | --- | --- |
| `low` | 轻微偏差，可记录但不一定自动修复 | 字段别名差异，结果基本等价 |
| `medium` | 局部失败，建议进入 repair-agent 分析 | projection 或 limit 偏差 |
| `high` | 明确失败，应进入 repair-agent | 结果错误、意图错位、schema 不对齐 |
| `critical` | 硬失败或危险失败 | 语法不可执行、危险查询、契约破坏 |

### 9.4 failure_classes 取值

`failure_classes` 是数组，不是单值枚举。一张问题单可以同时报告多个失败类别，例如同时有 `schema_alignment` 和 `result_correctness`。不要用 `mixed` 作为类别值，因为 `mixed` 只能说明“有多个问题”，却会丢掉到底是哪几个问题。

| 取值 | 含义 | 典型来源 |
| --- | --- | --- |
| `syntax_validity` | 语法或执行硬失败 | `syntax_validity=fail` |
| `schema_alignment` | schema 不对齐 | `schema_alignment=fail` |
| `result_correctness` | 查询结构可能合理但结果不对 | `result_correctness=fail` 且 intent 通过 |
| `query_intent_alignment` | 查询结构意图偏离 | 当前 `question_alignment=fail` |

生成规则：

1. 对每个 failed dimension 独立生成一个 failure class。
2. `question_alignment=fail` 映射为 `query_intent_alignment`，因为当前字段名历史上叫 question alignment，但实际评测的是查询结构意图。
3. 如果多个维度 fail，`failure_classes` 保留多个值，例如 `["schema_alignment", "result_correctness"]`。
4. 如果需要单值展示，可以从数组中派生 `primary_failure_class`；派生规则必须明确，不应替代数组本身。

### 9.5 dimension_signals 字段来源

`dimension_signals` 不应只给一个字符串，而应暴露少量关键指标。

示例：

```json
{
  "result_correctness": {
    "status": "fail",
    "score": 0.57,
    "primary_signal": "low_result_recall",
    "details": {
      "precision": 1.0,
      "recall": 0.4,
      "f1": 0.57,
      "order_sensitive": false
    }
  }
}
```

每个字段来源必须能追溯到 `EvaluationMetrics`。

### 9.6 failure_diff 字段来源

`failure_diff` 应从 expected/actual 与 metrics 派生。

建议字段：

| 字段 | 含义 | 来源 |
| --- | --- | --- |
| `entity_mismatch` | 实体类型不一致 | label 集合与 `entity_match_score` |
| `relation_mismatch` | 关系路径不一致 | relation 集合与 `relation_path_match_score` |
| `filter_mismatch` | 过滤条件不一致 | WHERE 存在性与 property 集合 |
| `aggregation_mismatch` | 聚合意图不一致 | 聚合函数存在性 |
| `projection_mismatch` | 返回结构不一致 | `projection_match_score` 与 row semantic keys |
| `ordering_mismatch` | 排序要求不一致 | ORDER BY 检查 |
| `limit_mismatch` | LIMIT 缺失或数值不一致 | LIMIT 检查 |
| `execution_error` | 执行失败 | `actual.execution.success` 和 `error_message` |
| `missing_or_wrong_clauses` | 上述问题的枚举集合 | 从 diff 字段汇总 |

### 9.7 diagnostic_tags 取值

`diagnostic_tags` 是中性诊断标签，用于快速索引失败现象。它只能来自 `failure_diff`、`dimension_signals` 或 `evaluation.evidence`，不能表达修复目标，也不能写成 `add_few_shot`、`fix_prompt` 这类策略。

一张问题单可以包含多个 tag。建议首批稳定取值：

| 取值 | 含义 | 典型来源 |
| --- | --- | --- |
| `syntax_error` | Cypher 语法或解析失败 | `syntax_validity=fail` 且 evidence 包含 syntax |
| `execution_error` | TuGraph 执行失败 | `actual.execution.success=false` 或 `failure_diff.execution_error` |
| `schema_label_mismatch` | label 使用不符合 schema 或与 golden 不一致 | `schema_alignment=fail`，label score 低或非法 label |
| `schema_relation_mismatch` | relation 使用不符合 schema 或与 golden 不一致 | `schema_alignment=fail`，relation score 低或非法 relation |
| `schema_property_mismatch` | property 使用和 golden 不一致 | `property_match_score` 低 |
| `low_result_precision` | actual 多返回了不该返回的结果 | `result_set_precision` 低 |
| `low_result_recall` | actual 漏返回 expected 结果 | `result_set_recall` 低 |
| `projection_mismatch` | 返回结构与 expected 不一致 | `failure_diff.projection_mismatch=true` 或 `projection_match_score` 低 |
| `filter_mismatch` | WHERE 或过滤属性不一致 | `failure_diff.filter_mismatch=true` |
| `aggregation_mismatch` | 聚合意图不一致 | `failure_diff.aggregation_mismatch=true` |
| `ordering_mismatch` | 排序要求不一致 | `failure_diff.ordering_mismatch=true` |
| `limit_mismatch` | LIMIT 缺失或数值不一致 | `failure_diff.limit_mismatch=true` |

生成规则：

1. 每个 tag 必须能追溯到某个 failed dimension、metric 或 diff 字段。
2. 同一类问题只保留一个 tag，避免重复堆叠。
3. tag 不排序表达优先级；优先级由 `severity` 和可选的 `primary_failure_class` 表达。
4. 如果没有稳定证据，不生成 tag，不用 `unknown` 占位。

### 9.8 primary_failure_class 派生规则

`primary_failure_class` 是可选字段，只用于展示、排序或摘要。它不能替代 `failure_classes`，也不能让 repair-agent 忽略数组里的其他失败类别。

如果需要派生单值，按以下优先级从 `failure_classes` 中选择：

| 优先级 | 类别 | 理由 |
| ---: | --- | --- |
| 1 | `syntax_validity` | 语法或执行硬失败会阻断后续结果判断 |
| 2 | `schema_alignment` | schema 错误通常会导致执行或结果失真 |
| 3 | `query_intent_alignment` | 查询结构意图偏离时，结果错误多半是下游表现 |
| 4 | `result_correctness` | 结果不匹配但结构意图可能仍接近 |

派生规则：

1. 如果 `failure_classes` 为空，不生成 `primary_failure_class`。
2. 如果只有一个类别，`primary_failure_class` 等于该类别。
3. 如果有多个类别，按上表优先级选择。
4. 如果未来新增类别，必须同时更新这张优先级表；否则该类别不能成为 primary。

## 10. 状态机

testing-agent 使用 `EvaluationState` 表达流程状态：

| 状态 | 含义 |
| --- | --- |
| `received_golden_only` | 已收到 golden，等待 submission |
| `waiting_for_golden` | 已收到 submission，等待 golden |
| `ready_to_evaluate` | golden 与 submission 已具备，可评测 |
| `repair_pending` | 已生成 issue ticket，准备投递 repair-agent |
| `repair_submission_failed` | ticket 已生成，但 repair-agent 投递失败 |
| `issue_ticket_created` | ticket 已成功提交 repair-agent |
| `passed` | 本次尝试评测通过 |

`EvaluationState` 说明流程走到哪里；`verdict` 说明评测结论是什么。

## 11. 持久化与追溯

默认数据目录：

```text
data/testing_service/
```

存储结构：

| 路径 | 内容 |
| --- | --- |
| `goldens/{id}.json` | 黄金答案 |
| `submissions/{id}.json` | 最新 submission |
| `submission_attempts/{id}__attempt_{n}.json` | 按尝试编号保存的 submission |
| `issue_tickets/{ticket_id}.json` | 问题单 |

当前系统没有正式 artifact ref 协议，因此设计文档不应虚构 `testing://` 或 `cgs://` 引用。

第一版追溯依赖真实主键：

```text
id
attempt_no
generation_run_id
ticket_id
```

其中 `attempt_no` 是 testing-agent 维护和归档的尝试序号。cypher-generator-agent 不记录尝试次数，也不向 testing-agent 声明尝试次数；testing-agent 是 attempt 历史记录的唯一权威来源。

如果未来需要跨服务拉取完整 rows、完整 metrics、完整 prompt，应新增正式 API，而不是暴露内部文件路径。

## 12. 错误处理原则

### 12.1 输入冲突

- 同一 `id` 的 golden 如果内容不同，拒绝写入。
- 同一 `id + generation_run_id` 的 submission 如果内容不同，拒绝写入；`attempt_no` 由 testing-agent 在保存时分配。

### 12.2 执行失败

TuGraph 执行失败不会中断评测，而会进入 `actual.execution`，再由评测逻辑转成 `syntax_validity`、`schema_alignment`、`evidence`。

### 12.3 repair-agent 投递失败

如果 repair-agent 不可用：

```text
IssueTicket 已保存
submission 标记 repair_submission_failed
异常向上抛出
```

这一区分了：

```text
评测失败
问题单已生成
问题单投递失败
```

后续可以考虑将 repair-agent 投递失败转成可重试状态，而不是让 API 调用表现为 500。

## 13. 后续演进清单

本节只保留代码尚未完成的工作。已经完成的文档澄清和契约实现不再列入本节。

| 事项 | 当前状态 | 实现目标 |
| --- | --- | --- |
| 将 `question_alignment` 字段逐步改名为 `query_intent_alignment` | 文档、`diagnostic_summary.failure_classes` 与 repair-agent 诊断上下文已经使用 `query_intent_alignment` 语义；核心评测模型和历史 API 字段仍保留 `question_alignment` | 在模型、API、测试与历史兼容层中做字段迁移；迁移期可同时接受旧字段。评测定义见 [3.6](#36-question_alignment-如何评测) 和 [5.6](#56-question_alignment--query_intent_alignment-metrics) |

## 14. 结论

testing-agent 的核心设计应该保持克制：

```text
它负责执行、评测、证据整理和失败现象诊断；
它不负责根因归因和修复策略生成。
```

清晰的 testing-agent -> repair-agent 契约，是后续闭环稳定性的关键。
这个契约只承载失败事实与 knowledge-agent 知识修复所需证据，不承载 cypher-generator-agent 运行协议、解析器、守门器或 testing-agent 评测器的补丁建议。
