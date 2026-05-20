# Cypher 生成设计简版

本文是 `cypher-generation-design-based-on-ontology.md` 的简洁版，只说明整体流程和每一步做什么，不展开中间结构、提示词、规则细节和工程接口。

## 整体流程

```text
上游预处理产出 core_question
  -> Step 1 词法层 Lexer
  -> Step 2 逻辑规划 Logical Planner
  -> Step 3 语义校验 Semantic Validator
  -> Step 4 物理编译 Physical Compiler
  -> 执行 Cypher / 返回结果
```

核心思想是把“自然语言到 Cypher”拆成四层：

1. 先把问题切成可处理的 mention 和线索。
2. 再把 mention 规划成本体级 logical plan。
3. 再检查 logical plan 是否符合业务语义。
4. 最后把本体级计划编译成具体 Cypher。

## Step 1：词法层 Lexer

Step 1 负责把标准化后的 `core_question` 转成 mention 序列和词法线索。

它主要做：

- 用词典扫描业务对象、关系、属性、属性值和操作词。
- 识别没有被词典覆盖的残片，并对残片做向量召回。
- 处理重叠命中，例如“源网元”覆盖“源”和“网元”。
- 保留候选族，例如“名称”可能对应服务名称、隧道名称、网元名称。
- 抽取上下文线索和答案形态线索，例如“返回”后面的字段区域。

输出是 mention 序列、候选集合、未解释片段、`context_signals` 和 `shape_signals`。

## Step 2：逻辑规划 Logical Planner

Step 2 负责把 Step 1 的 mention 和线索转换成本体级 logical plan。它不关心物理图库字段，只使用本体对象、关系、属性和值。

### 2.0 意图分类与初始 Shape

判断用户问题属于哪类查询，以及预期返回形态是什么。

它主要做：

- 识别用户是要查记录、查路径、统计、对比，还是其他类型问题。
- 生成初始 `shape`，例如是否需要投影字段、是否需要路径解析、是否需要聚合。
- 如果无法识别 intent，输出澄清请求。
- 规则和召回不能稳定判断时，可进入 LLM 兜底；澄清请求进入统一澄清反问通道。

### 2.1 对象提取与角色标注

从 mention 序列里提取后续规划真正需要关注的对象，并标注这些对象可能承担的角色。

它主要做：

- 根据用户问题、intent 说明和 mention 片段，筛选关键对象。
- 给对象标注角色，例如过滤主体、路径主体、投影主体、返回主体。
- 保留 LLM 的原始选择文本，结构化结果由服务层生成。
- 对象不足或角色不明时，输出结构化澄清原因，交给统一澄清反问通道。

### 2.2 Mention 映射到本体

把 mention 映射到本体概念。

它主要做：

- 把对象 mention 映射为本体 class。
- 把关系 mention 映射为本体 relation 或 relation role。
- 把属性 mention 映射为本体 attribute 或属性候选族。
- 把值 mention 映射为 enum value、literal value 或过滤值线索。
- 保留候选族，不在本阶段做属性绑定或路径选择。

### 2.3 本体路径选择

为对象之间的连接选择本体路径。

它主要做：

- 根据 2.2 的本体映射生成路径选择任务。
- 从本体关系图里枚举候选路径。
- 单候选路径由服务层自动接受。
- 多候选路径交给 LLM 在候选中选择。
- 输出最终 `selected_paths`，并回填路径相关 shape 信息。
- 路径无法安全选择时，输出结构化澄清原因，交给统一澄清反问通道。

### 2.4 指代消解

判断多个本体对象记录是否指向同一个业务对象，并合并成最终语义节点。

它主要做：

- 为可能同指的对象记录生成候选对。
- 没有同指候选对时，不调用 LLM，直接把对象记录作为独立语义节点输出。
- 利用原文位置、返回字段区域、区分词和已接受路径作为判断证据。
- 调用 LLM 判断“同一个对象 / 不同对象 / 需要澄清”。
- 输出合并后的语义节点。
- 同指关系无法判断时，输出结构化澄清原因，交给统一澄清反问通道。

### 2.5 属性、值与投影绑定

把过滤条件和返回字段绑定到具体语义节点上。

它主要做：

- 为每个待绑定的属性、值或运行时字面值生成绑定候选。
- 无候选时输出资料缺口或澄清请求。
- 唯一候选由服务层自动接受。
- 多候选交给 LLM 选择。
- 输出 filter 绑定、projection 绑定和相关 shape 更新。
- 字段或条件归属不明时，输出结构化澄清原因，交给统一澄清反问通道。

### 2.6 Shape 回填与结构预校验

汇总 Step 2 前面各阶段的结果，形成完整 logical plan，并在进入 Step 3 前做结构预检查。

它主要做：

- 回填最终 `hop_count`、`relation_chain_type`、`filter_level` 等 shape 字段。
- 汇总 unresolved items，判断是否需要澄清、资料补齐或工程失败。
- 检查节点、边、属性、过滤、投影和 shape 是否结构完整。
- 通过后输出本体级 logical plan。

## Step 3：语义校验 Semantic Validator

Step 3 负责检查 Step 2 产出的 logical plan 是否符合业务语义约束。

它主要做：

- 检查节点类型是否存在。
- 检查关系方向和 domain / range 是否合法。
- 检查属性是否属于对应对象。
- 检查 cardinality、必填关系、业务约束和不变量。
- 检查 logical plan 是否还能被后续物理编译安全消费。
- 可由用户补充修正的语义问题，输出结构化澄清原因，交给统一澄清反问通道。

输出是 validated logical plan；如果业务语义不明确或违反约束，则输出澄清或失败信息。

## Step 4：物理编译 Physical Compiler

Step 4 负责把通过校验的本体级 logical plan 编译成 TuGraph Cypher。

它主要做：

- 把本体 class 映射为物理 node label。
- 把本体 relation 映射为物理 edge type。
- 把本体 attribute 映射为图属性。
- 根据 logical plan 生成 `MATCH`、`WHERE`、`RETURN`、聚合、排序和分页。
- 校验映射是否能落到当前物理 schema。

输出是可执行 Cypher。Step 4 不做业务判断，也不调用 LLM。
