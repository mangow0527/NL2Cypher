# 自然语言问题预处理层设计

## 1. 背景与目标

当前 cypher-generator-agent 的主链路是：

```text
自然语言问题
  -> 意图识别
  -> 语义视图匹配
  -> LogicalQueryPlan
  -> schema/path planning
  -> Cypher 生成与预检
```

这条链路假设输入已经是一个较明确的查询问题。但真实用户输入经常不是这样。即使系统只支持“一轮单查询、生成一条 Cypher”，用户仍然会在一句话里加入寒暄、背景、犹豫、自我修正和焦虑性赘述。

例如：

```text
嗯...你好，我们最近发现核心交换机故障频发，客户也在投诉，
所以我想查一下，呃，那种金牌业务，啊不对，银牌业务有多少
没有冗余隧道的，最好详细一点，谢谢
```

对下游来说，真正需要理解的是：

```text
银牌业务有多少没有冗余隧道
```

预处理层的目标是：

- 从真实用户表达中保守提取一个明确、可执行的查询问题。
- 去除或标注寒暄、礼貌语、背景叙述、填充词和焦虑性赘述。
- 识别自我修正，例如“金牌业务，不对，是银牌业务”。
- 识别无法安全进入生成链路的输入，并直接返回澄清。
- 保留原始输入和处理证据，方便运行中心回放、调试和人工审核。

预处理层不负责：

- 不识别一级/二级意图，这仍然属于意图识别层。
- 不把业务表达映射到图语义视图，这仍然属于语义视图匹配层。
- 不自动把背景中的实体、时间或地点变成查询过滤条件。
- 不拆分多个独立查询生成多条 Cypher。
- 不生成 Cypher。

## 2. 总体位置

新增问题预处理层后，主链路变为：

```text
自然语言问题
  -> 问题预处理层
  -> 意图识别层
  -> 语义视图匹配层
  -> LogicalQueryPlan
  -> schema/path planning
  -> Cypher 生成与预检
```

预处理层是第 0 层语义入口。它只回答两个问题：

```text
1. 这句话里是否存在一个明确的查询请求？
2. 如果存在，下游应该使用哪一段问题文本继续处理？
```

如果不能提取明确查询，预处理层直接输出 `clarification_required`，不继续进入意图识别。

## 3. 核心原则

### 3.1 保守处理

预处理层宁可少改，也不要错改。

如果规则无法判断“用户到底想查什么”，不要强行改写成一个看似合理的问题，而是进入澄清。

例如：

```text
Gold 服务最近有点慢，帮我看看
```

这句话虽然有业务对象 `Gold 服务`，但没有明确查询目标。系统不能擅自假设用户要查时延、隧道、路径、端口还是状态。因此应返回澄清。

### 3.2 原文永远保留

预处理得到的 `core_question` 或 `retrieval_question` 只用于下游理解。运行中心和测试留存仍必须保留原始 `original_question`。

原因：

- 用户回放时应该看到自己真实输入。
- 预处理可能出错，必须能还原现场。
- 背景里可能包含隐含提示，后续版本可以重新利用。

### 3.3 标注优先，删除谨慎

有些词看似赘述，但可能影响查询形态。

例如：

```text
完整路径
全部隧道
详细列出每个网元
```

这里的“完整”“全部”“详细”不能简单删除。预处理层应把它们标注成 hint，由 planner 或 return policy 决定是否消费。

### 3.4 背景默认不参与下游匹配

背景叙述大部分是情绪、场景和原因，不适合直接喂给意图识别或向量召回。

例如：

```text
我们这周一直在排查 NE-001 的故障，所以查一下金牌业务
```

背景中的 `NE-001` 可能相关，也可能只是上下文。第一版不应自动把它加成过滤条件，只能放入 `background_hints`。

## 4. 模块架构

建议预处理层拆成以下组件：

```text
QuestionPreprocessor
  -> TextNormalizer
  -> PhraseMatcher
  -> SpanResolver
  -> CompoundQueryDetector
  -> SelfCorrectionResolver
  -> BackgroundStripper
  -> NoiseAndHintAnnotator
  -> StructuralAnnotator
  -> ClarityGate
```

各组件职责如下：

| 组件 | 中文说明 |
| --- | --- |
| `TextNormalizer` | 做字符级清洗，例如标点、空白、停顿词，不改变业务语义。 |
| `PhraseMatcher` | 使用短语词典扫描输入，识别寒暄、礼貌语、过渡词、修正词、查询动作词、领域对象等。 |
| `SpanResolver` | 解决短语重叠，例如“帮我查”与“帮我”“查”同时命中时保留更合适的片段。 |
| `CompoundQueryDetector` | 判断是否包含多个独立查询；若超出“一问一 Cypher”范围则澄清。 |
| `SelfCorrectionResolver` | 处理“A，不对，是 B”这类自我修正。 |
| `BackgroundStripper` | 识别“背景 + 过渡词 + 核心查询”结构，提取核心问题。 |
| `NoiseAndHintAnnotator` | 标注可剥离噪声和需要保留的 hint。 |
| `StructuralAnnotator` | 提取数字、比较、否定、时间、ID、数量提示等轻量结构信号。 |
| `ClarityGate` | 最终判断能否进入意图识别，或是否需要澄清。 |

## 5. Trie 与 AC 自动机的定位

### 5.1 Trie 是什么

Trie，也叫前缀树，适合做词典匹配。它把短语按字符路径组织起来。

例如词典：

```text
你好
您好
帮我
帮我查
帮我看看
```

可以组织成：

```text
帮
 └─ 我
     ├─ 查
     └─ 看
         └─ 看
你
 └─ 好
您
 └─ 好
```

Trie 适合：

- 判断某个位置是否以词典短语开头。
- 做最长前缀匹配。
- 做简单词典分词。

但如果要在整句话任意位置查找大量短语，单纯 Trie 需要从多个位置反复尝试。

### 5.2 AC 自动机是什么

AC 自动机，全名 Aho-Corasick Automaton，可以理解为：

```text
Trie + 失败跳转
```

它可以一次从左到右扫描整段文本，同时找出所有词典短语。

例如词典：

```text
你好
帮我
查一下
不对
详细一点
谢谢
```

输入：

```text
你好，帮我查一下 Gold 服务，不对，是 Silver 服务，详细一点，谢谢
```

AC 自动机一次扫描即可命中：

```text
你好
帮我
查一下
不对
详细一点
谢谢
```

### 5.3 为什么本项目适合 AC 自动机

预处理层需要识别大量固定短语，而且这些短语可能出现在句子的任意位置。

例如：

```text
你好 ... 所以 ... 我想查 ... 不对 ... 详细一点 ... 谢谢
```

这些短语包括：

- 寒暄词
- 礼貌词
- 背景过渡词
- 自我修正 marker
- 填充词
- 焦虑性赘述
- 查询动作词
- 疑问词
- 领域对象词
- 关系词

因此完整方案中建议使用 AC 自动机作为统一短语扫描基础设施。

需要强调的是：

```text
AC 自动机只是扫描器，不是决策器。
```

它只负责告诉系统：

```text
哪个短语，在什么位置，以什么类别命中。
```

它不负责：

- 删除文本。
- 判断背景分界是否可信。
- 判断“不对”是否真的是自我修正。
- 判断问题是否需要澄清。
- 判断查询意图或生成 Cypher。

更准确的分工是：

```text
AC 自动机 = 传感器
正则 = 结构模式识别器
规则模块 = 决策器
QuestionPreprocessor = 编排器
```

## 6. 短语词典设计

短语词典不应只是字符串列表，而应包含类别、行为建议和权重。

示例：

```yaml
greeting:
  default_action: safe_to_strip
  phrases:
    - 你好
    - 您好
    - 在吗

politeness:
  default_action: safe_to_strip
  phrases:
    - 麻烦
    - 请问
    - 辛苦了
    - 谢谢

soft_query_intro:
  default_action: boundary_signal
  phrases:
    - 我想查
    - 我想看
    - 我想知道
    - 帮我查
    - 帮我看
    - 能不能
    - 可不可以

background_transition:
  default_action: boundary_signal
  phrases:
    - 所以
    - 因此
    - 具体来说
    - 我的问题是
    - 我想问的是

self_correction_marker:
  default_action: requires_rule
  phrases:
    - 不对
    - 不是
    - 等等
    - 更正一下
    - 改成
    - 应该是

filler:
  default_action: safe_to_strip
  phrases:
    - 那个
    - 这个
    - 就是说
    - 呃
    - 怎么说呢

detail_hint:
  default_action: consider_as_hint
  phrases:
    - 详细一点
    - 完整
    - 全部
    - 尽量
    - 最好

query_action:
  default_action: query_signal
  phrases:
    - 查询
    - 查看
    - 统计
    - 列出
    - 比较
    - 判断

question_word:
  default_action: query_signal
  phrases:
    - 哪些
    - 多少
    - 是否
    - 有没有
    - 谁
    - 哪个

relation_signal:
  default_action: query_signal
  phrases:
    - 使用
    - 连接
    - 承载
    - 关联
    - 经过

domain_object:
  default_action: query_signal
  phrases:
    - 服务
    - 业务
    - 隧道
    - 设备
    - 端口
    - 链路
    - 网元
```

建议的行为类型：

| 行为 | 中文说明 |
| --- | --- |
| `safe_to_strip` | 可以从检索问题中删除，例如“你好”“谢谢”。 |
| `consider_as_hint` | 不直接删除，作为提示传给下游，例如“完整”“详细”。 |
| `requires_rule` | 必须交给规则模块判断，例如“不对”“不是”。 |
| `query_signal` | 用于判断是否存在明确查询，例如“统计”“哪些”“隧道”。 |
| `boundary_signal` | 可作为背景剥离或核心问题起点的候选边界。 |

## 7. 处理流程

### 7.1 Step 1：字符清洗

输入：

```text
  嗯...你好，帮我查一下 Gold 服务？？  
```

输出：

```text
你好，帮我查一下 Gold 服务？
```

处理内容：

- 去掉首尾空白。
- 合并连续空白和换行。
- 统一中英文标点。
- 压缩重复标点。
- 去掉明显无意义的开头停顿词，例如“嗯”“呃”“额”。

注意：这一步不删除业务词，不改写实体名，不改变语义。

### 7.2 Step 2：短语扫描

使用 AC 自动机扫描 `cleaned_question`，得到短语命中列表。

示例输出：

```json
[
  {
    "start": 0,
    "end": 2,
    "text": "你好",
    "kind": "greeting",
    "suggested_action": "safe_to_strip"
  },
  {
    "start": 3,
    "end": 6,
    "text": "帮我查",
    "kind": "soft_query_intro",
    "suggested_action": "boundary_signal"
  },
  {
    "start": 15,
    "end": 17,
    "text": "服务",
    "kind": "domain_object",
    "suggested_action": "query_signal"
  }
]
```

### 7.3 Step 3：短语冲突消解

AC 自动机可能返回重叠结果。

例如：

```text
帮我查一下 Gold 服务
```

可能命中：

```text
帮我
帮我查
查一下
一下
服务
```

消解策略：

- 同类短语优先保留最长匹配。
- 不同类短语允许重叠，但要保留用途差异。
- `query_signal` 不应被 `safe_to_strip` 覆盖。
- `consider_as_hint` 不应被直接删除。

### 7.4 Step 4：复合问题检测

识别是否包含多个独立查询。

需要澄清的例子：

```text
查 Gold 服务用了哪些隧道，再统计这些隧道平均时延
```

这可能需要多个阶段或多个 Cypher，第一版不支持。

可以接受的例子：

```text
查询 Gold 服务使用的隧道名称和时延
```

这是同一查询对象下的多个返回字段，可以继续。

判断信号：

- 多个查询动作词。
- 多个疑问结构。
- “再”“然后”“同时”“另外”等连接词。
- 主对象是否一致。
- 答案形态是否一致。

如果判定为无法支持的复合问题，输出澄清：

```json
{
  "source_stage": "question_preprocessing",
  "reason_code": "compound_query_not_supported",
  "question_zh": "请一次只描述一个查询目标。"
}
```

### 7.5 Step 5：自我修正处理

处理用户临时改口：

```text
查金牌业务，不对，是银牌业务的隧道数量
```

候选 marker：

```text
不对
不是
等等
更正一下
改成
应该是
算了
```

处理原则：

- 只在高置信时采纳修正。
- 如果像复合问题，不当成修正。
- 如果前后关系复杂，进入澄清或保留原文。

高置信条件：

- marker 前后距离合理。
- marker 后半句包含查询信号或领域对象。
- 前后片段有共同领域词，或看起来是同类实体替换。
- marker 后不是另一个完整独立查询。

输出示例：

```json
{
  "applied": true,
  "marker": "不对",
  "abandoned_text": "金牌业务",
  "corrected_text": "银牌业务",
  "result_question": "查询银牌业务的隧道数量"
}
```

如果自我修正不明确：

```json
{
  "source_stage": "question_preprocessing",
  "reason_code": "self_correction_ambiguous",
  "question_zh": "请确认你最终想查询的是哪一个对象。"
}
```

### 7.6 Step 6：背景叙述剥离

识别“背景 + 过渡词 + 核心查询”结构。

例子：

```text
我们最近发现核心交换机故障频发，客户也在投诉，所以我想查一下银牌业务有多少没有冗余隧道
```

输出：

```json
{
  "background": "我们最近发现核心交换机故障频发，客户也在投诉",
  "core_question": "银牌业务有多少没有冗余隧道"
}
```

候选边界：

- `background_transition`，例如“所以”“因此”“具体来说”。
- `soft_query_intro`，例如“我想查”“帮我看”“我想知道”。

剥离策略：

- 找最后一个强边界 marker。
- 边界后必须包含查询信号。
- 边界前如果包含明显叙事表达，则更可信。
- 边界后太短则回退。
- 剥离后如果丢失唯一业务实体，则回退。

注意：

背景不丢弃，只保存到 `background`，并提取少量 `background_hints`。

### 7.7 Step 7：噪声与提示标注

根据短语命中结果，把片段分为两类。

可剥离噪声：

```text
你好
谢谢
麻烦
请问
帮我
一下
呃
就是说
```

需要保留的提示：

```text
完整
全部
详细一点
前 10
最近 7 天
```

这一阶段产出两版文本：

```text
core_question
retrieval_question
```

`core_question` 保留更多用户表达，用于 LLM fallback 或 trace。

`retrieval_question` 去掉安全噪声，用于 intent embedding 和规则匹配。

示例：

```text
core_question:
银牌业务有多少没有冗余隧道，详细一点

retrieval_question:
银牌业务有多少没有冗余隧道
```

### 7.8 Step 8：轻量结构化标注

提取结构信号，但不做完整意图识别。

识别内容：

- 数字：前 10、超过 5、最近 7 天。
- 比较：大于、小于、最高、最低、最多、最少。
- 否定：没有、未、不存在。
- 时间：今天、昨天、最近、本周。
- ID：NE-001、link-001。
- 数量提示：多少、几个、数量、总数。
- 排序提示：前 N、最高、最低、TopN。

输出示例：

```json
{
  "numbers": [],
  "comparators": [],
  "negations": ["没有"],
  "time_expressions": [],
  "identifiers": [],
  "ranking_signals": [],
  "quantifier_hint": "count"
}
```

### 7.9 Step 9：明确性判定

最后判断是否能进入意图识别。

可以进入意图识别的例子：

```text
Gold 服务用了哪些隧道
统计每个厂商的设备数量
查询状态为 down 的端口
服务 A 到端口 B 的路径
银牌业务有多少没有冗余隧道
```

需要澄清的例子：

```text
你好
帮我看看
这个业务是不是正常
最近有点慢，分析一下
客户投诉很多，帮忙处理一下
还有呢
继续查
```

接受条件：

- 存在明确查询信号。
- 存在领域对象、实体 ID 或可识别业务对象。
- 不是纯背景、纯寒暄或纯泛泛请求。
- 不是无法支持的复合查询。
- 不存在未解决的自我修正歧义。

拒绝时输出：

```json
{
  "source_stage": "question_preprocessing",
  "reason_code": "query_intent_missing",
  "question_zh": "请补充你想查询的具体对象、指标或关系。"
}
```

## 8. 输出契约

### 8.1 成功输出

```json
{
  "accepted": true,
  "original_question": "嗯...你好，我们最近发现核心交换机故障频发，客户也在投诉，所以我想查一下，呃，那种金牌业务，啊不对，银牌业务有多少没有冗余隧道的，最好详细一点，谢谢",
  "cleaned_question": "你好，我们最近发现核心交换机故障频发，客户也在投诉，所以我想查一下，呃，那种金牌业务，啊不对，银牌业务有多少没有冗余隧道的，最好详细一点，谢谢",
  "core_question": "银牌业务有多少没有冗余隧道，详细一点",
  "retrieval_question": "银牌业务有多少没有冗余隧道",
  "background": "你好，我们最近发现核心交换机故障频发，客户也在投诉",
  "self_correction": {
    "applied": true,
    "marker": "啊不对",
    "abandoned_text": "金牌业务",
    "corrected_text": "银牌业务"
  },
  "phrase_spans": [],
  "stopword_spans": [],
  "hint_spans": [],
  "structural_hints": {
    "quantifier_hint": "count",
    "negations": ["没有"]
  },
  "background_hints": {
    "domain_objects": ["核心交换机"]
  },
  "clarification": null,
  "diagnostics": {
    "compound_detection": {
      "is_compound": false
    },
    "background_strip": {
      "applied": true,
      "boundary_marker": "所以我想查"
    },
    "clarity_gate": {
      "accepted": true,
      "reason": "核心问题包含领域对象、数量疑问和否定条件。"
    }
  },
  "applied_steps": [
    "clean_text",
    "match_phrases",
    "resolve_spans",
    "detect_compound_query",
    "resolve_self_correction",
    "strip_background",
    "annotate_noise_and_hints",
    "annotate_structure",
    "clarity_gate"
  ]
}
```

### 8.2 澄清输出

```json
{
  "accepted": false,
  "original_question": "Gold 服务最近有点慢，帮我看看",
  "cleaned_question": "Gold 服务最近有点慢，帮我看看",
  "core_question": null,
  "retrieval_question": null,
  "background": "Gold 服务最近有点慢",
  "self_correction": null,
  "phrase_spans": [],
  "stopword_spans": [],
  "hint_spans": [],
  "structural_hints": {},
  "background_hints": {
    "domain_objects": ["服务"]
  },
  "clarification": {
    "source_stage": "question_preprocessing",
    "reason_code": "query_intent_missing",
    "question_zh": "请补充你想查询的具体对象、指标或关系。"
  },
  "diagnostics": {
    "clarity_gate": {
      "accepted": false,
      "reason": "输入包含业务对象和背景状态，但缺少明确查询目标。"
    }
  },
  "applied_steps": [
    "clean_text",
    "match_phrases",
    "strip_background",
    "annotate_structure",
    "clarity_gate"
  ]
}
```

## 9. 下游如何使用

预处理成功后，下游建议这样消费：

| 下游阶段 | 使用字段 | 说明 |
| --- | --- | --- |
| 意图识别规则阶段 | `retrieval_question` 或 `core_question` | 优先用去噪后的文本，减少寒暄和背景干扰。 |
| 意图识别 embedding 阶段 | `retrieval_question` | 向量召回最怕噪声，使用更短更干净的文本。 |
| 意图识别 LLM 阶段 | `core_question` + selected hints | 保留更多表达，但不要默认喂背景全文。 |
| 语义视图匹配 | `core_question` + `structural_hints` | 识别实体、属性、路径和值。 |
| planner | `core_question` + `hint_spans` + `structural_hints` | 可消费“完整”“全部”“详细”等返回策略提示。 |
| 运行中心展示 | `original_question` + preprocessing trace | 用户回放和问题定位必须看原文与处理证据。 |

如果预处理返回澄清，服务直接输出 `clarification_required`，不进入意图识别。

## 10. 澄清原因枚举

第一版建议支持以下 `reason_code`：

| reason_code | 中文说明 |
| --- | --- |
| `query_intent_missing` | 缺少明确查询目标，例如“帮我看看”。 |
| `background_only` | 只有背景描述，没有查询请求。 |
| `dependent_multi_step_query` | 输入包含依赖式多步查询，需要先执行一步查询得到结果，再把结果用于下一步查询。 |
| `parallel_compound_query` | 输入包含多个并列独立查询，当前单 Cypher 链路不支持。 |
| `compound_query_not_supported` | 复合查询兜底原因；无法明确归入依赖式或并列式，但已超出单 Cypher 范围。 |
| `self_correction_ambiguous` | 自我修正不清楚，无法判断最终对象。 |
| `multi_turn_self_correction_ambiguous` | 多轮自我否定或反复切换对象，无法判断最终查询对象。 |
| `choice_ambiguous` | 用户给出多个候选对象或条件，但没有说明选哪个。 |
| `background_filter_ambiguous` | 背景中出现实体、时间或范围，但无法判断是否应作为查询过滤条件。 |
| `core_query_too_vague` | 有疑似核心问题，但过于泛化。 |
| `followup_without_context` | 像多轮追问，但当前没有可用上下文，例如“继续查”。 |

后续可以把 `question_zh` 做得更细，但第一版可以先统一成较保守的澄清文本。

## 11. 预处理层澄清反问链路

预处理层的澄清不应该只是“拒绝继续处理”，而应该尽量给出可执行的反问结构。也就是说，预处理层发现问题不能直接进入单 Cypher 链路时，应同时输出：

- 为什么不能继续。
- 系统识别到了哪些候选查询、候选对象或候选条件。
- 用户需要确认什么。
- 如果能给选项，给出结构化选项。

澄清输出建议统一使用以下结构：

```json
{
  "source_stage": "question_preprocessing",
  "reason_code": "...",
  "question_zh": "...",
  "expected_answer_type": "single_choice|multi_choice|free_text|confirm_split",
  "options": [],
  "detected_items": {},
  "suggested_rewrites": []
}
```

字段说明：

| 字段 | 中文说明 |
| --- | --- |
| `source_stage` | 固定为 `question_preprocessing`，方便运行中心定位。 |
| `reason_code` | 澄清原因枚举。 |
| `question_zh` | 给用户展示的中文反问。 |
| `expected_answer_type` | 期望用户怎么回答，例如单选、多选、自由文本或确认拆分。 |
| `options` | 可选项；如果系统能识别候选对象或候选拆分，应尽量给出。 |
| `detected_items` | 预处理层识别到的内部证据，例如候选对象、候选查询、依赖关系。 |
| `suggested_rewrites` | 系统建议拆成的单查询问题。 |

### 11.1 依赖式多步查询

依赖式多步查询指的是：第二步查询依赖第一步查询的结果。它通常不是一条静态 Cypher 能稳定表达的自然语言问题，至少不适合当前“一问一 Cypher”的生成链路直接处理。

例子：

```text
你先查一下名称为 A 的服务的当前状态，再根据这个状态去查询系统里状态相同的服务
```

这里包含两个步骤：

```text
1. 查询名称为 A 的服务的当前状态。
2. 使用第 1 步得到的状态值，查询系统中状态相同的服务。
```

第二步里的 `XX` 不是用户直接给出的常量，而是第一步查询结果。因此预处理层应返回澄清，而不是把它强塞给意图识别。

澄清输出示例：

```json
{
  "source_stage": "question_preprocessing",
  "reason_code": "dependent_multi_step_query",
  "question_zh": "这个问题需要先查询服务 A 的当前状态，再用该状态查询其它服务。是否要拆成两个问题处理？",
  "expected_answer_type": "confirm_split",
  "options": [
    {
      "id": "split",
      "label": "拆成两个问题",
      "description": "先查询名称为 A 的服务当前状态；再查询状态相同的所有服务。"
    },
    {
      "id": "first_only",
      "label": "只查第一步",
      "description": "只查询名称为 A 的服务当前状态。"
    },
    {
      "id": "rewrite",
      "label": "我重新描述",
      "description": "用户重新输入一个单步查询。"
    }
  ],
  "detected_items": {
    "dependency_type": "value_from_previous_query",
    "first_query": "查询名称为 A 的服务的当前状态",
    "second_query_template": "查询状态为 <第一步状态值> 的所有服务"
  },
  "suggested_rewrites": [
    "查询名称为 A 的服务的当前状态",
    "查询状态为 XX 的所有服务"
  ]
}
```

识别信号：

- 出现“先...再...”“先...然后...”“根据这个/该结果/这个状态/上述值...”。
- 第二个查询片段引用了第一步结果，例如“这个状态”“该数量”“同样的类型”“上一步结果”。
- 第二步缺少显式过滤值，必须依赖第一步执行结果。

处理原则：

- 不自动生成两个 Cypher。
- 不自动把第一步结果变量化。
- 不进入意图识别。
- 给用户一个确认拆分的反问。

### 11.2 并列独立复合查询

并列独立复合查询指的是：一句话里包含两个或多个互不依赖的查询。

例子：

```text
查一下 Gold 服务用了哪些隧道，再统计状态为 down 的端口数量
```

这两个查询没有依赖关系，但答案形态和查询对象不同。当前单 Cypher 链路不应强行合并。

澄清输出示例：

```json
{
  "source_stage": "question_preprocessing",
  "reason_code": "parallel_compound_query",
  "question_zh": "你这句话里包含多个查询目标。请确认要先处理哪一个，或拆成多个问题。",
  "expected_answer_type": "single_choice",
  "options": [
    {
      "id": "query_1",
      "label": "查询 Gold 服务使用的隧道",
      "description": "查询 Gold 服务用了哪些隧道。"
    },
    {
      "id": "query_2",
      "label": "统计 down 端口数量",
      "description": "统计状态为 down 的端口数量。"
    },
    {
      "id": "both",
      "label": "两者都要",
      "description": "请拆成两个问题依次处理。"
    }
  ],
  "detected_items": {
    "query_segments": [
      "查询 Gold 服务用了哪些隧道",
      "统计状态为 down 的端口数量"
    ]
  },
  "suggested_rewrites": [
    "查询 Gold 服务用了哪些隧道",
    "统计状态为 down 的端口数量"
  ]
}
```

识别信号：

- 出现“再”“然后”“另外”“同时”“顺便”“还要”等并列连接词。
- 多个查询动作词对应不同对象或不同答案形态。
- 片段之间没有“根据这个结果”之类的依赖引用。

需要注意：不是所有并列结构都要澄清。下面仍然可以看作单查询：

```text
查询 Gold 服务使用的隧道名称和时延
```

它只是同一查询对象下的多个返回字段，不是多个独立查询。

### 11.3 多轮自我否定或反复切换

单次自我修正可以处理：

```text
查金牌业务，不对，是银牌业务的隧道数量
```

但多轮切换容易失真：

```text
查金牌业务，不对，看银牌的，啊还是金牌吧，看一下数量
```

如果系统无法高置信判断最终对象，应澄清，而不是按最后一个对象或第一个对象武断选择。

澄清输出示例：

```json
{
  "source_stage": "question_preprocessing",
  "reason_code": "multi_turn_self_correction_ambiguous",
  "question_zh": "你在金牌业务和银牌业务之间有切换，请确认要查哪个。",
  "expected_answer_type": "single_choice",
  "options": [
    {
      "id": "gold",
      "label": "金牌业务",
      "description": "查询金牌业务的数量。"
    },
    {
      "id": "silver",
      "label": "银牌业务",
      "description": "查询银牌业务的数量。"
    },
    {
      "id": "both",
      "label": "两者都要",
      "description": "查询金牌业务和银牌业务的数量。"
    }
  ],
  "detected_items": {
    "candidate_objects": ["金牌业务", "银牌业务"],
    "final_query_tail": "看一下数量",
    "correction_markers": ["不对", "啊还是"]
  },
  "suggested_rewrites": [
    "查询金牌业务数量",
    "查询银牌业务数量",
    "分别查询金牌业务和银牌业务数量"
  ]
}
```

识别信号：

- 多个自我修正 marker。
- 同一槽位中出现多个候选对象，例如业务等级从金牌切到银牌又切回金牌。
- 最终查询尾部是泛化表达，例如“看一下数量”，需要依赖前文对象。

处理原则：

- 如果只有一次明确修正，可以直接采用修正后对象。
- 如果发生多轮切换，除非最后表达非常明确，否则澄清。
- 选项应尽量把候选对象列出来，并允许“两者都要”。

### 11.4 候选对象或条件并列但选择不明

有些输入不是复合查询，而是同一个查询槽位里出现多个候选值，但用户没有说明是并集、交集还是二选一。

例子：

```text
查 Gold 或 Silver 服务用了哪些隧道
```

这里可能表示：

```text
1. Gold 和 Silver 都查。
2. 只查其中一个，但用户还没确定。
3. 查满足 Gold 或 Silver 任一条件的服务。
```

如果当前语义视图和 planner 不能稳定处理这种集合条件，预处理层可以先澄清。

澄清输出示例：

```json
{
  "source_stage": "question_preprocessing",
  "reason_code": "choice_ambiguous",
  "question_zh": "你提到了 Gold 和 Silver，请确认查询范围。",
  "expected_answer_type": "single_choice",
  "options": [
    {"id": "gold", "label": "只查 Gold 服务"},
    {"id": "silver", "label": "只查 Silver 服务"},
    {"id": "both", "label": "Gold 和 Silver 都查"}
  ],
  "detected_items": {
    "candidate_values": ["Gold", "Silver"],
    "slot": "service_level"
  }
}
```

### 11.5 背景中的过滤条件是否生效不明确

背景里可能出现实体、时间、范围，但用户的核心查询没有明确说要把它作为过滤条件。

例子：

```text
我们这周一直在排查 NE-001 的故障，所以查一下金牌业务数量
```

这里的 `NE-001` 是否要限定查询范围并不明确。第一版默认不自动加入过滤条件。如果系统认为这个背景 hint 很可能影响答案，也可以澄清。

澄清输出示例：

```json
{
  "source_stage": "question_preprocessing",
  "reason_code": "background_filter_ambiguous",
  "question_zh": "你提到了 NE-001。查询金牌业务数量时，是否需要限定在 NE-001 相关范围内？",
  "expected_answer_type": "single_choice",
  "options": [
    {"id": "with_filter", "label": "限定在 NE-001 相关范围内"},
    {"id": "without_filter", "label": "不限定，查询全系统"},
    {"id": "rewrite", "label": "我重新描述"}
  ],
  "detected_items": {
    "background_identifiers": ["NE-001"],
    "core_query": "查询金牌业务数量"
  }
}
```

是否在预处理层触发这类澄清，需要谨慎。第一版建议默认只落 `background_hints`，不主动澄清；只有当核心问题本身包含“这里/这个/该设备/相关”等指代词时，再触发澄清。

### 11.6 泛化诊断请求

用户经常会说：

```text
这个业务是不是正常
Gold 服务最近有点慢，帮我分析一下
客户投诉很多，帮忙处理一下
```

这类问题不是明确的数据查询，而是诊断任务。当前 cypher-generator-agent 不负责诊断编排，预处理层应澄清用户想查询哪个具体对象、指标或关系。

澄清输出示例：

```json
{
  "source_stage": "question_preprocessing",
  "reason_code": "query_intent_missing",
  "question_zh": "请补充你想查询的具体对象、指标或关系，例如服务状态、使用的隧道、端口状态或路径信息。",
  "expected_answer_type": "free_text",
  "options": [
    {"id": "service_status", "label": "查询服务状态"},
    {"id": "used_tunnels", "label": "查询服务使用的隧道"},
    {"id": "path_info", "label": "查询服务路径"}
  ],
  "detected_items": {
    "generic_diagnostic_terms": ["正常", "分析"]
  }
}
```

### 11.7 无上下文追问

如果当前服务没有多轮会话上下文，下面的问题不能直接处理：

```text
继续查
还有呢
那它的状态呢
同样的条件再查一下端口
```

澄清输出示例：

```json
{
  "source_stage": "question_preprocessing",
  "reason_code": "followup_without_context",
  "question_zh": "当前没有可用的上一轮查询上下文，请完整描述你想查询的对象、条件和返回内容。",
  "expected_answer_type": "free_text",
  "options": []
}
```

### 11.8 澄清场景优先级

一个输入可能同时命中多个澄清原因。建议优先级如下：

```text
1. dependent_multi_step_query
2. parallel_compound_query
3. multi_turn_self_correction_ambiguous
4. self_correction_ambiguous
5. followup_without_context
6. choice_ambiguous
7. background_filter_ambiguous
8. background_only
9. query_intent_missing
10. core_query_too_vague
```

优先级的含义是：越靠前越容易导致错误执行或错误拆分，应优先澄清。

## 12. 规则与算法边界

### 12.1 AC 自动机适合做什么

适合：

- 固定短语扫描。
- 大量短语统一匹配。
- 输出短语位置、类别、建议动作。

不适合：

- 判断语义关系。
- 判断是否删除。
- 判断用户真正意图。
- 处理数值、ID、比较结构。

### 12.2 正则适合做什么

适合：

- 数字和单位。
- ID 模式。
- 比较条件。
- 自我修正句式骨架。
- 时间表达。

例如：

```text
前 10 个
最近 7 天
大于 5
NE-001
A，不对，是 B
```

### 12.3 规则模块适合做什么

适合：

- 判断是否复合查询。
- 判断背景剥离是否安全。
- 判断自我修正是否可信。
- 判断是否需要澄清。
- 决定哪些 span 从 `retrieval_question` 中删除。

## 13. 暂不引入 LLM 改写

本设计第一版不建议默认引入 LLM 改写。

原因：

- 当前目标是输入降噪，不是复杂语义推理。
- 大量场景可由短语词典、正则和保守规则覆盖。
- LLM 改写有可能过度解释用户背景，生成用户没说过的查询。
- 纯规则更容易测试、复现和在运行中心解释。

后续如果真实数据表明规则覆盖不足，可以增加受控 LLM 改写，但触发条件要严格。

可能触发条件：

- `core_question` 很长且包含多个限定子句。
- 自我修正出现多次。
- 背景剥离失败但查询信号明显。
- 名词短语很多但缺少主干关系。
- 出现“或者”等并列表达，但复合检测无法判断。

LLM 只能输出：

```json
{
  "decision": "accept|clarify",
  "normalized_question": "...",
  "reason_code": "...",
  "reason": "..."
}
```

并且必须遵守：

- 不补充用户没说的业务事实。
- 不自动使用背景作为过滤条件。
- 多个独立查询时返回澄清。
- 只有背景或泛泛请求时返回澄清。

## 14. 测试建议

建议建立一组预处理测试集，覆盖以下类型：

1. 纯查询。
2. 寒暄 + 查询。
3. 背景 + 查询。
4. 自我修正。
5. 犹豫/填充 + 查询。
6. 焦虑性赘述 + 查询。
7. 只有背景。
8. 只有泛泛请求。
9. 复合查询。
10. 背景中包含实体但不应自动作为过滤条件。
11. 依赖式多步查询。
12. 并列独立复合查询。
13. 多轮自我否定。
14. 候选对象并列但选择不明。
15. 无上下文追问。

示例：

```text
你好，帮我查一下 Gold 服务用了哪些隧道
=> accepted, retrieval_question = Gold 服务用了哪些隧道

Gold 服务最近有点慢，帮我看看
=> clarification_required, reason_code = query_intent_missing

查金牌业务，不对，是银牌业务的隧道数量
=> accepted, retrieval_question = 银牌业务的隧道数量

查 Gold 服务用了哪些隧道，再统计这些隧道的平均时延
=> clarification_required, reason_code = parallel_compound_query

先查名称为 A 的服务当前状态，再根据这个状态查询系统里状态相同的服务
=> clarification_required, reason_code = dependent_multi_step_query

查金牌业务，不对，看银牌的，啊还是金牌吧，看一下数量
=> clarification_required, reason_code = multi_turn_self_correction_ambiguous

我们这周一直在排查 NE-001 的故障，所以查一下金牌业务
=> accepted, background_hints contains NE-001, but retrieval_question 不自动加入 NE-001
```

## 15. 待审核问题

以下问题建议在实现前继续确认：

1. 复合查询的边界：哪些“多个返回字段”仍算单查询，哪些必须澄清？
2. `detail_hint` 是否要在第一版传给 planner，还是只落 trace？
3. 背景中的时间表达是否可以比实体更积极地传给下游？
4. `retrieval_question` 是否同时用于规则阶段和 embedding 阶段，还是规则阶段保留 `core_question`？
5. 运行中心是否需要单独展示“原始问题 -> 核心问题 -> 检索问题”的对照卡片？
6. 预处理层是否只返回澄清建议，还是也负责在用户确认后生成新的单查询输入？
7. “两者都要”这类选项在当前一问一 Cypher 范围内，是提示用户拆分，还是允许进入集合查询？
