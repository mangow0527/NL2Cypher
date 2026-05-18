好的，我把整套流程从头到尾、按最终设计形态完整画一遍。这次不再夹杂讨论，只给清晰的"现在我们到底要做一个什么样的系统"。

我会用那句"查询金牌服务经过的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址"作为主线，每一步都明确：**输入是什么、产出是什么、用到哪些资产、LLM 是否介入、出错怎么办**。

## 整体架构

```
                    [自然语言问句]
                          ↓
                  ┌───────────────┐
                  │ Step 1: Lexer │  词法层
                  └───────────────┘
                          ↓
                    [mention 序列]
                          ↓
                  ┌───────────────────────┐
                  │ Step 2: Logical       │  逻辑规划
                  │       Planner         │
                  └───────────────────────┘
                          ↓
                [ontology-level logical plan]
                          ↓
                  ┌──────────────────────┐
                  │ Step 3: Semantic     │  语义校验
                  │       Validator      │
                  └──────────────────────┘
                          ↓
                [validated logical plan]
                          ↓
                  ┌──────────────────────┐
                  │ Step 4: Physical     │  物理编译
                  │       Compiler       │
                  └──────────────────────┘
                          ↓
                       [Cypher]
                          ↓
                      [执行/结果]


离线资产(被运行时各步消费):
  lexicon/*.yaml                      ← Step 1
  mention_to_ontology.yaml            ← Step 2
  domain_ontology.yaml                ← Step 2, Step 3
  semantic_objects.yaml               ← Step 2
  constraints.yaml                    ← Step 3
  cypher_mapping.yaml                 ← Step 4
  physical_graph_schema.yaml          ← Step 4(校验用)
```

**四个步骤的核心定位**：

- **Step 1 Lexer**：自然语言串 → 离散的、带类型的符号序列
- **Step 2 Logical Planner**：符号序列 → 结构化的、本体级的查询计划
- **Step 3 Semantic Validator**：检查计划是否符合业务约束
- **Step 4 Physical Compiler**：本体级计划 → 具体后端的查询语言

每一步的产物是确定的中间表示，每一步的职责互不重叠。

## Step 1：词法层（Lexer）

### 目标

把自然语言串切成离散的、带类型的、带 canonical_id 的 mention 序列。

### 输入

- 用户原始问句：`"查询金牌服务经过的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址"`
- 资产：`lexicon/*.yaml`（六本词典）+ 向量索引

### 内部过程

**1.1 预处理**：全角转半角、规范化标点、必要时分句。

**1.2 AC 自动机扫描**：一遍扫描，找出所有精确命中。

**1.3 重叠消解**：最长匹配优先 + 词典优先级。"源网元"命中后不再让"网元"单独命中。

**1.4 残片识别**：把没被命中覆盖的字符段标出来。

**1.5 向量召回（仅对残片）**：
- 类型一致性约束：召回结果必须和残片的预期 mention_type 一致
- 必须在已注册的词典里
- 相似度 ≥ 0.85 → 自动采用
- 相似度 0.6–0.85 → 进 LLM 选择（见下）
- 相似度 < 0.6 → 标为真正未命中，走澄清出口

**1.6 LLM 介入（仅在歧义场景）**：
- AC 命中多候选 + 规则无法消歧 + 上下文信号充分时
- 向量召回中等相似度时
- LLM 必须从候选列表中选，必须引用原句 span + 上下文信号
- 输出 confidence 由规则组合多源证据计算，不是 LLM 自报
- LLM 不可用或低组合置信度 → 走澄清出口

**1.7 信号抽取**：在 mention 序列上抽出结构化上下文信号（邻近修饰、单一对象上下文、关系路径上下文、操作意图、角色词、显式限定词），附加到 mention 上备用。

### 产出

```yaml
mentions:
  - {mention_id: MEN_OP_QUERY,        surface: "查询",     span: [0, 2],   type: OPERATION}
  - {mention_id: MEN_GOLD,            surface: "金牌",     span: [2, 4],   type: VALUE}
  - {mention_id: MEN_SERVICE,         surface: "服务",     span: [4, 6],   type: OBJECT}
  - {mention_id: MEN_TRAVERSE,        surface: "经过",     span: [6, 8],   type: RELATION}
  - {mention_id: MEN_TUNNEL,          surface: "隧道",     span: [9, 11],  type: OBJECT}
  - {mention_id: MEN_SOURCE_NE,       surface: "源网元",   span: [13, 16], type: ROLE_OBJ}
  - {mention_id: MEN_OP_RETURN,       surface: "返回",     span: [17, 19], type: OPERATION}
  - {mention_id: MEN_TUNNEL,          surface: "隧道",     span: [19, 21], type: OBJECT}
  - {mention_id: MEN_IETF_STANDARD,   surface: "IETF标准", span: [22, 28], type: ATTRIBUTE}
  - {mention_id: MEN_SOURCE_NE,       surface: "源网元",   span: [29, 32], type: ROLE_OBJ}
  - {mention_id: MEN_IP_ADDRESS,      surface: "IP地址",   span: [33, 37], type: ATTRIBUTE}

unmatched_spans: []          # 这句话没有残片
clarification_pending: []    # 这句话不需要澄清

extracted_signals:
  - {type: PROXIMAL_MODIFIER, mention: MEN_GOLD, target: MEN_SERVICE, distance: 0}
  - {type: PROXIMAL_MODIFIER, mention: MEN_IETF_STANDARD, target: MEN_TUNNEL, distance: 1}
  - {type: PROXIMAL_MODIFIER, mention: MEN_IP_ADDRESS, target: MEN_SOURCE_NE, distance: 1}
  - {type: OPERATION_INTENT, marker: MEN_OP_QUERY, intent: SELECT}
  - {type: OPERATION_INTENT, marker: MEN_OP_RETURN, intent: PROJECT_MARKER}
```

### 失败处理

- 真未命中 → 澄清反问"系统不认识这个词"
- 不可消歧的歧义 → 澄清反问"这个词有多种含义"
- LLM 调用失败 → 自动降级到规则版本

## Step 2：逻辑规划（Logical Planner）

### 目标

把扁平的 mention 序列**结构化**为一张完整的、本体级的查询计划（语义图）。

这是整个系统的**核心步骤**，对应到 MetricFlow 那种 planner/compiler 思路里的 logical planning 阶段。

### 输入

- mention 序列 + 抽取出来的上下文信号
- 资产：`mention_to_ontology.yaml`、`domain_ontology.yaml`、`semantic_objects.yaml`

### 内部七个子阶段

**2.1 意图归类**

扫描 OPERATION 类 mention，决定整张计划的根操作和结构：

- `MEN_OP_QUERY` 在句首 → 根操作 = SELECT
- `MEN_OP_RETURN` 在中段 → 它是 projection 分隔符，之后的 ATTRIBUTE 进 projection 列表

产出：`root_operation = SELECT`、`projection_marker_position = 17`

**2.2 主体识别**

判断哪些 OBJECT mention 是"查询的核心"，哪些是路径中间节点。

- `MEN_SERVICE` 在 OPERATION 之后 + 紧跟过滤值 + 后面有关系跳出 → 主体之一
- `MEN_TUNNEL` 在关系之后 + 后面继续跳出 → 主体之一
- `MEN_SOURCE_NE` 在"及其"之后 + 角色化对象 → 主体之一

产出：主体列表 `[Service, Tunnel, NetworkElement]`

**2.3 拓扑骨架构建**

把 mention 升格为语义图的节点、边、过滤、投影：

通过 `mention_to_ontology.yaml` 查找每个 mention 对应的本体概念：

- `MEN_SERVICE` → 本体类 Service → 创建节点 `s1: Service`
- `MEN_TUNNEL`（两次出现）→ 本体类 Tunnel → 暂时创建两个候选节点 `t1, t2: Tunnel`，留给 2.5 消解
- `MEN_SOURCE_NE`（两次出现）→ 本体类 NetworkElement + via_relation: TUNNEL_SRC → 暂时创建两个候选节点 `n1, n2: NetworkElement`
- `MEN_TRAVERSE` → 本体关系 SERVICE_USES_TUNNEL → 待加边
- `MEN_GOLD` → ServiceQuality.GOLD + constrains Service.quality_of_service → 待绑过滤
- `MEN_IETF_STANDARD` → Tunnel.ietf_standard → 待加 projection
- `MEN_IP_ADDRESS` → NetworkElement.ip_address → 待加 projection

**如果命中 semantic_object**（这句问题没有命中，跳过此分支）：直接套用 semantic_objects 里登记的展开结果。

**2.4 路径填补**（关键步骤）

这是 planner 体现"理解结构"的地方。

检查每条 RELATION mention 和 ROLE_OBJ mention 的连接关系：

- `MEN_TRAVERSE` 的本体定义 `SERVICE_USES_TUNNEL: Service → Tunnel` → 加边 `s1 -[SERVICE_USES_TUNNEL]-> t1`
- `MEN_SOURCE_NE` 的 via_relation `TUNNEL_SRC: Tunnel → NetworkElement` → 这条边需要从 Tunnel 出发。检查语义图，最近的 Tunnel 是 `t1` → 加边 `t1 -[TUNNEL_SRC]-> n1`

**注意**：这里发生了**隐式中间节点确认**——用户说"金牌服务的源网元"时，没明说要经过隧道，但本体定义 Service 到 NetworkElement 没有直接关系，必须经过 Tunnel。planner 利用 `via_relation` 的本体定义自动接上。

**2.5 指代消解**

判断同名 mention 是同指还是不同指：

- "隧道"出现两次（`t1` 来自第一次"经过的隧道"，`t2` 来自"隧道的IETF标准"）
  - 规则判定：两次提及无区分修饰词 + 第二次紧邻"返回"投影 markers + 第一次已是路径中节点
  - 决策：**同指**，合并 `t2` → `t1`

- "源网元"出现两次（`n1` 和 `n2`）
  - 规则判定：同样无区分修饰词、同样在投影位置引用
  - 决策：**同指**，合并 `n2` → `n1`

LLM 在指代消解里只在规则模糊时介入，这句问题规则就能判定。

**2.6 属性/值绑定**

把过滤、投影、属性引用绑到具体节点上：

- `MEN_GOLD`（ServiceQuality.GOLD，constrains Service.quality_of_service）→ 找到 Service 节点 `s1` → 加 filter `s1.quality_of_service = GOLD`
- `MEN_IETF_STANDARD`（Tunnel.ietf_standard）→ 找到 Tunnel 节点 `t1` → 进 projection
- `MEN_IP_ADDRESS`（候选 NetworkElement.ip_address）→ 上下文信号 `PROXIMAL_MODIFIER` 指向 MEN_SOURCE_NE → 找到 NetworkElement 节点 `n1` → 进 projection

**2.7 结构预校验**

在交给 Step 3 之前做一遍**结构性检查**（不是业务规则校验，那是 Step 3 的事）：

- 所有边的 domain/range 是否合法
- 所有属性是否真的属于对应类
- 投影列表非空
- 没有孤立节点

通过则输出。

### 产出

```yaml
logical_plan:
  root_operation: SELECT

  nodes:
    - {id: s1, type: Service,
       filters: [{attr: quality_of_service, op: equals, value: ServiceQuality.GOLD}]}
    - {id: t1, type: Tunnel}
    - {id: n1, type: NetworkElement}

  edges:
    - {from: s1, to: t1, relation: SERVICE_USES_TUNNEL}
    - {from: t1, to: n1, relation: TUNNEL_SRC}

  projection:
    - {node: t1, attribute: ietf_standard, alias: tunnel_ietf_standard}
    - {node: n1, attribute: ip_address,    alias: source_ne_ip}
```

**关键特征**：

- 完全用本体概念表达（Service、Tunnel、NetworkElement、SERVICE_USES_TUNNEL、TUNNEL_SRC 都是本体里的 id）
- 完全脱离了原始自然语言
- 完全脱离了物理 schema（不知道表名/Label、不知道字段名）
- 这就是和 MetricFlow logical plan 同质的中间表示

### 失败处理

- 主体识别不出来 → 澄清"请明确您想查询什么"
- 路径填补失败（本体里两点不连通）→ 澄清"系统不知道 A 和 B 怎么关联"
- 指代消解低 confidence → 澄清"您提到的两个 X 是同一个还是不同的？"
- 属性绑定失败 → 澄清"X 属性应该归属哪个对象？"

## Step 3：语义校验（Semantic Validator）

### 目标

用业务约束检查 logical plan 是否合法。**不修改 plan**，只判定通过或失败。

### 输入

- Step 2 产出的 logical plan
- 资产：`domain_ontology.yaml` 里的 cardinality 和 invariants、`constraints.yaml`

### 内部过程

**3.1 类型合法性**

- 每个节点的本体类是否存在
- 每条边的 relation 是否合法、方向是否符合 domain/range
- 每个属性是否真的归属其节点的本体类

**3.2 业务约束校验**

逐条跑 `constraints.yaml` 里的规则：

- 投影属性是否在本体上合法（拦截 Service.ip_address 这类非法查询）
- 必填关系是否都连上了（Tunnel 必须有 TUNNEL_SRC）
- 业务规则是否违反（金牌业务必须冗余隧道之类的硬规则）

**3.3 cardinality 一致性**

- 单一关系的 from_side cardinality 如果是 1，过滤条件不应该让结果集大于 1
- 多对多关系是否需要 DISTINCT

这句问题全部通过——金牌业务的过滤 + 隧道 + 源网元的拓扑都在本体合法范围内。

### 产出

- 通过 → 把 logical plan 原样传给 Step 4
- 失败 → 走澄清出口

### 失败处理（关键）

校验失败不是"系统挂掉"，是"用户问了一个无效的查询"，必须友好反馈：

- 规则识别失败原因（结构化：哪个约束、哪个节点、哪个属性）
- 规则列出"用户可能的真实意图"（基于本体最短路径推断）
- LLM 把这些结构化信息转成友好的澄清话术
- 候选意图来自规则，LLM 只做措辞

例：用户问"查询金牌服务的 IP 地址"，校验失败：

> 业务本身没有 IP 地址。您可能想查询：
> (A) 业务承载的网元的 IP 地址
> (B) 业务源端网元的 IP 地址
> 请选择，或重新描述您的需求。

## Step 4：物理编译（Physical Compiler）

### 目标

把本体级 logical plan 翻译成 TuGraph Cypher。**完全规则驱动，无 LLM**。

### 输入

- Step 3 通过的 logical plan
- 资产：`cypher_mapping.yaml`、`physical_graph_schema.yaml`（用于校验 mapping 引用的物理对象都存在）

### 内部过程

**4.1 节点物化**

每个本体节点查 `cypher_mapping.yaml` 的 class_mappings：

- `s1: Service` → `(s:Service)`，alias = s
- `t1: Tunnel` → `(t:Tunnel)`，alias = t
- `n1: NetworkElement` → `(n:NetworkElement)`，alias = n

**4.2 路径物化**

每条本体边查 relation_mappings：

- `SERVICE_USES_TUNNEL` → `-[:SERVICE_USES_TUNNEL]->`
- `TUNNEL_SRC` → `-[:TUNNEL_SRC]->`

拼成 MATCH 子句：

```
MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)-[:TUNNEL_SRC]->(n:NetworkElement)
```

**4.3 过滤物化**

查 attribute_mappings 和 value_transform：

- `s1.quality_of_service = ServiceQuality.GOLD`
  - attribute → node_property: `s.quality_of_service`
  - value_transform: `GOLD → 'Gold'`
  - 产出: `s.quality_of_service = 'Gold'`

**4.4 投影物化**

每个 projection 项查 attribute_mappings：

- `t1.ietf_standard` → `t.ietf_standard AS tunnel_ietf_standard`
- `n1.ip_address` → `n.ip_address AS source_ne_ip`

**4.5 always_filter 注入**

查每个节点 mapping 的 always_filter（软删除等），自动追加到 WHERE：

（假设这套数据没有 always_filter，跳过）

**4.6 拼装**

按 Cypher 语法把 MATCH、WHERE、RETURN 拼起来。

### 产出

```cypher
MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)-[:TUNNEL_SRC]->(n:NetworkElement)
WHERE s.quality_of_service = 'Gold'
RETURN t.ietf_standard AS tunnel_ietf_standard,
       n.ip_address    AS source_ne_ip
```

### 失败处理

Step 4 不应该有"业务失败"——所有业务问题已经在 Step 3 拦掉。这里只可能有"工程失败"：

- mapping 引用的 node_label 在 physical_graph_schema 里不存在 → fail-loud，资产同步问题
- mapping 缺少某个本体属性的映射 → fail-loud，配置缺失

这些是 CI 应该提前拦截的问题，运行时遇到说明资产校验流程有漏洞。

## 各步骤一图总结

```
Step 1 Lexer
  输入: 自然语言串
  资产: lexicon/*.yaml + 向量索引
  LLM:  歧义消解(规则模糊+信号充分)、未命中召回(中相似度)
  产出: mention 序列 + 上下文信号
  失败: 澄清

       ↓

Step 2 Logical Planner
  输入: mention 序列 + 信号
  资产: mention_to_ontology + domain_ontology + semantic_objects
  LLM:  指代消解(规则模糊+信号充分,HIGH_RISK 严格阈值)
        属性绑定消歧(规则模糊+信号充分)
  子阶段:
    2.1 意图归类
    2.2 主体识别
    2.3 拓扑骨架构建
    2.4 路径填补(自动接隐式中间节点)
    2.5 指代消解
    2.6 属性/值绑定
    2.7 结构预校验
  产出: ontology-level logical plan
  失败: 澄清

       ↓

Step 3 Semantic Validator
  输入: logical plan
  资产: domain_ontology.constraints + constraints.yaml
  LLM:  仅在失败时生成友好澄清话术(候选来自规则)
  产出: validated logical plan / 澄清请求
  失败: 澄清

       ↓

Step 4 Physical Compiler
  输入: validated logical plan
  资产: cypher_mapping + physical_graph_schema
  LLM:  禁止
  产出: Cypher
  失败: fail-loud(工程错误,不是业务错误)

       ↓

执行 Cypher → 返回结果(可选 LLM 做结果摘要)
```

## 五份资产 vs 四个步骤的消费关系

把这张表打印出来贴墙上，每次有疑问对照一下：

| 资产文件 | Step 1 | Step 2 | Step 3 | Step 4 |
|---|:---:|:---:|:---:|:---:|
| lexicon/*.yaml | ✓ | | | |
| mention_to_ontology.yaml | | ✓ | | |
| domain_ontology.yaml（类、属性、关系、enum） | | ✓ | | |
| domain_ontology.yaml（cardinality、约束） | | | ✓ | |
| semantic_objects.yaml | | ✓（可选快捷） | | |
| constraints.yaml | | | ✓ | |
| cypher_mapping.yaml | | | | ✓ |
| physical_graph_schema.yaml | | | | ✓（校验用） |

**关键不变量**：

- 每份资产只被特定步骤消费，不跨步骤穿透
- 任何一份资产变化，只影响一个步骤
- 添加新后端（比如 SQL）= 加一份 `sql_mapping.yaml` + 加一个 SQL Compiler，前三步完全不动

## LLM 介入点全景（用最严格的边界）

按上一轮讨论后的最终边界，运行时 LLM 介入位置如下：

| 介入点 | 在哪一步 | 触发条件 | 风险等级 | 决策角色 |
|---|---|---|---|---|
| AC 多候选消歧 | Step 1 | 规则模糊 + 信号充分 | LOW/MEDIUM | 在候选内选择 |
| 向量召回中相似度选择 | Step 1 | 0.6 < sim < 0.85 + 类型一致 | LOW/MEDIUM | 在 top-K 内选择 |
| 候选属性绑定 | Step 2.6 | 多候选 + 句法信号充分 | MEDIUM | 在候选内选择 |
| 指代消解 | Step 2.5 | 强信号支持但有歧义 | HIGH | 在两种解读间选择 |
| 友好澄清话术 | Step 3 失败时 | 必要 | N/A | 措辞生成（候选来自规则）|
| 结果摘要 | Step 4 后 | 可选 | N/A | 措辞生成 |

**Step 4 完全没有 LLM**——这是架构红线。

**所有 LLM 介入的共同约束**：

- 只能在系统资料边界内选择
- 必须引用原句 span + 上下文信号
- 最终置信度由规则组合多源证据计算
- 按风险等级用不同阈值
- 低组合置信度 → 走澄清
- LLM 不可用 → 自动降级

## 失败/澄清作为一等公民

整套流程里，**澄清不是"出错处理"，是流程的合法分支**。任何一步都可能产出三种结果之一：

1. **继续**：产出下一步需要的中间表示
2. **澄清**：产出给用户的追问 + 候选选项
3. **拒绝**：明确告诉用户系统不支持

澄清回流到用户后，用户的下一句输入再走一次完整流程（带着上次的语义图状态作为上下文）。

这种设计确保：**任何模糊或资料缺口都会显式暴露，不会变成静默错误**。

## 和 MetricFlow 的对照

最后明确这套设计和你提的 MetricFlow 范式的对应关系：

| MetricFlow | 我们的设计 |
|---|---|
| Semantic Manifest（语义清单） | domain_ontology + semantic_objects |
| Query Parser | Step 1 + Step 2.1-2.2 |
| Logical Plan | Step 2 产出的语义图 |
| Validator | Step 3 |
| SQL Compiler | Step 4（Physical Compiler） |
| Connection / Adapter | cypher_mapping + physical_graph_schema |

**核心思想完全一致**：用一个**物理无关的中间表示**把"业务理解"和"物理生成"解耦。

差异只在两点：
- MetricFlow 服务 BI 分析，核心是指标（Metrics 是一等公民）
- 我们服务网络运维查询，核心是对象拓扑（Classes 和 Relations 是一等公民）

底层架构是同一套。**这套架构在工业界经过多年验证**（dbt Semantic Layer、Looker LookML、Cube.js 都是这个模式），是 NL2Query 系统的合理终局。

## 结尾

整套流程的本质用一句话讲完：

> **把"自然语言 → Cypher"分解为四个有清晰中间表示的步骤，每步只做一件事，每步只消费特定资产，每步可独立测试可独立替换；LLM 在严格边界内做有限决策，澄清是一等公民；本体是业务真相的载体，物理映射是后端适配，两者通过 logical plan 解耦。**

这就是完整流程。后续接 runtime 时，按这四步逐个实现即可，资产已经在前面 7 个 Phase 里准备好了。
