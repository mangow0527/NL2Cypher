# Projection Coverage Fix IR

> 日期：2026-05-28
> 状态：待审核 IR v0
> 适用分支：`cypher-generation-osi`
> 触发样本：`qa_9cfa692813d5`
> IR 含义：Implementation Roadmap / Implementation Requirements

## 1. 背景

本 IR 针对 OSI 重写后的 CGA 在多字段投影场景中出现的语义窄化问题。

触发问题：

```text
查询所有服务的ID、名称、元素类型、服务质量等级、带宽和时延。
```

期望语义：

```text
MATCH (svc:Service)
RETURN
  svc.id,
  svc.name,
  svc.elem_type,
  svc.quality_of_service,
  svc.bandwidth,
  svc.latency
```

实际生成：

```cypher
MATCH (svc:Service)
RETURN svc.id AS service_id
```

trace 显示 `question_decomposer` 已经识别出 `服务、ID、名称、元素类型、服务质量等级、带宽、时延`，但 `grounded_understanding` 输出：

```json
{
  "selected_vertices": ["Service"],
  "selected_properties": [],
  "projection": [{"semantic_type": "vertex", "name": "Service"}]
}
```

随后 DSL builder 将裸 `vertex` projection 静默降级为 `Service.id`。semantic validator 和 self-validation 只验证了生成出来的 `Service.id` 合法，没有检查用户要求的 6 个返回字段是否齐全。

## 2. 精确归因

这是一个多层防御同时失效的问题。

| 层级 | 失效点 | 影响 |
| --- | --- | --- |
| 主因：grounded understanding | 多个返回字段被塌缩成一个裸 `Service` vertex projection。 | `selected_properties=[]`，字段信息从 binding plan 中消失。 |
| 防线 1：DSL builder | 裸 `vertex` projection 被静默编译成 id property。 | “返回节点/对象”被无依据窄化为“返回 ID”。 |
| 防线 2：semantic validator | 只检查已有 projection 合法，不检查用户要求字段是否进入 projection。 | projection coverage gap 没有被拦截。 |
| 防线 3：self-validation | 只检查 Cypher 语法、只读、schema reference、RETURN shape 等静态合法性。 | `RETURN svc.id` 合法，因此继续放行。 |

关键问题不是单个 prompt 漏了示例，而是当前 coverage 只覆盖了“概念是否被引用”，没有覆盖“实义词是否进入了正确语义槽位”。本次漏的是 `projection` 槽位。后续同类风险还可能出现在 `filter`、`group_by`、`order_by`、`path`、`limit` 等槽位。

## 3. 目标

目标：

- 将用户显式要求的返回字段落成确定性 property-level projection。
- 禁止 DSL builder 静默把模糊 vertex projection 降级成 ID。
- 在 semantic validator 中增加 projection coverage 防线。
- 将本 bug 转化为 golden regression 和单元测试，避免未来回归。
- 保持 CGA 不连接数据库、不执行 Cypher 的边界。
- 保持 LLM 只做结构化填空和候选内选择，字段投影绑定由工程代码兜底。

非目标：

- 本 IR 不扩展新的复杂 query shape。
- 本 IR 不要求解决所有路径、聚合、Top-N 问题。
- 本 IR 不引入 raw Cypher fallback。
- 本 IR 不要求 runtime console 展示改版；只在必要时补 trace 字段。

## 4. 设计原则

1. **投影是独立语义槽位**：字段词被召回到候选不等于已覆盖，必须进入最终 DSL `projection.items` 才算 projection covered。
2. **工程代码负责确定性绑定**：`ID/名称/带宽/时延` 这类字段词应由 registry/candidate evidence 绑定到 property，不依赖 LLM 自由发挥。
3. **DSL builder 不猜语义**：builder 只能编译明确 projection，遇到模糊裸 vertex projection 应报错或要求上游显式声明。
4. **validator 做纵深防御**：即使 grounded understanding 丢字段，semantic validator 也必须拦截 projection coverage 缺失。
5. **self-validation 只做末端静态防御**：不能把用户意图覆盖全部压给 Cypher self-validation，但可以补充 shape 一致性检查。

## 5. IR 总览

| IR | 名称 | 优先级 | 估算 | 角色 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| IR-PC-00 | Regression Fixture and Baseline | P0 | S | QA/backend | 无 |
| IR-PC-01 | Projection Slot Resolver | P0 | M | backend | IR-PC-00 |
| IR-PC-02 | Grounded Understanding Projection Contract | P1 | M | backend/LLM | IR-PC-01 |
| IR-PC-03 | Projection Coverage Validator | P0 | M | backend | IR-PC-01 |
| IR-PC-04 | DSL Builder No Silent ID Downgrade | P0 | S | backend | IR-PC-02、IR-PC-03 |
| IR-PC-05 | Self-Validation Shape Guard Extension | P2 | S | backend | IR-PC-04 |
| IR-PC-06 | Trace and Error Contract for Projection Coverage | P1 | S | backend/infra | IR-PC-03 |
| IR-PC-07 | Regression Matrix Integration | P0 | S | QA/infra | IR-PC-00 到 IR-PC-06 |

推荐落地顺序：

```text
IR-PC-00 -> IR-PC-01 -> IR-PC-03 -> IR-PC-04 -> IR-PC-02 -> IR-PC-06 -> IR-PC-05 -> IR-PC-07
```

如果只能先做一项，优先做 `IR-PC-03 Projection Coverage Validator`，因为它是通用防线，可以拦住整类“看起来合法但漏返回字段”的问题。

## 6. IR 详细清单

### IR-PC-00 Regression Fixture and Baseline

目标：把 `qa_9cfa692813d5` 和同类多字段投影样本固化为回归基线。

依赖：无。

建议文件：

```text
services/cypher_generator_agent/tests/fixtures/golden_questions.yaml
services/cypher_generator_agent/tests/integration/test_golden_regression_matrix.py
services/cypher_generator_agent/tests/validation/test_projection_coverage.py
services/cypher_generator_agent/tests/dsl/test_builder_projection.py
```

开发内容：

- 将 `qa_9cfa692813d5` 纳入 active regression scope。
- 补至少 3 个同类多字段 projection case：
  - 单 vertex 多字段：`Service.id/name/elem_type/quality_of_service/bandwidth/latency`
  - 单跳终点多字段：`Tunnel.id/name/bandwidth`
  - 带过滤的多字段：`quality_of_service=Gold` 且返回 `Service.id/name/bandwidth`
- golden 断言必须检查 DSL projection，不只检查最终 Cypher 字符串。

验收：

- 当前实现下新增测试应能暴露 `projection.items` 不完整的问题。
- golden fixture 中每个多字段样本都明确列出 expected projection properties。
- 测试描述中区分“字段投影缺失”和“路径/过滤/执行失败”。

### IR-PC-01 Projection Slot Resolver

目标：新增确定性的 projection slot 解析能力，把用户要求的字段词绑定成 property-level projection。

依赖：IR-PC-00。

建议文件：

```text
services/cypher_generator_agent/app/binding/projection_resolver.py
services/cypher_generator_agent/app/binding/models.py
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/tests/binding/test_projection_resolver.py
```

开发内容：

- 新增 `ProjectionResolver`，输入：
  - `QuestionDecomposition`
  - `CandidateRetrievalResult`
  - 已选 vertex / edge / path role
  - optional literal/filter context
- 输出 property-level projection items：

```json
[
  {"semantic_type": "property", "owner": "Service", "name": "id", "alias": "service_id"},
  {"semantic_type": "property", "owner": "Service", "name": "name", "alias": "service_name"}
]
```

- 解析规则：
  - 字段词只能从 semantic model registry 的 property 和候选 evidence 中选择。
  - 在单 vertex 查询中，字段词默认绑定到唯一 vertex。
  - 在 single-hop/path 查询中，字段词必须根据局部修饰词绑定到 source/end/path role，例如“隧道的名称”绑定到 `Tunnel.name`。
  - `ID/编号/名称/类型/元素类型/服务质量等级/带宽/时延/状态/厂商` 等字段词应走 deterministic alias/synonym 规则。
  - 如果字段词可绑定到多个 owner 且上下文无法消歧，返回 ambiguity，不静默选择。
- `_deterministic_grounding_from_slots` 不再只从 filter 中提取 selected properties，应合并：

```text
filter_properties + projection_properties
```

验收：

- `qa_9cfa692813d5` 的 resolver 输出 6 个 `Service` property projection。
- `qa_c80a82efe561` 的 resolver 输出 3 个 `Tunnel` property projection。
- `qa_c2508f2c0bac` 的 resolver 同时保留 filter property `Service.quality_of_service` 和 projection properties `Service.id/name/bandwidth`。
- ambiguous owner 场景返回 structured ambiguity，不产生猜测 projection。

### IR-PC-02 Grounded Understanding Projection Contract

目标：收紧 grounded understanding 的 projection contract，避免“裸 vertex”表达混淆。

依赖：IR-PC-01。

建议文件：

```text
services/cypher_generator_agent/app/understanding/models.py
services/cypher_generator_agent/app/understanding/prompt.py
services/cypher_generator_agent/app/understanding/grounded_understanding.py
services/cypher_generator_agent/tests/understanding/test_grounded_understanding_projection_contract.py
```

开发内容：

- 区分 projection item 类型：
  - `property`：明确返回某个 property。
  - `vertex_full`：明确返回整个节点。
  - 禁止模糊的裸 `vertex` projection 进入常规路径。
- grounded understanding prompt 增加 projection 落地规则：
  - 如果 decomposition 中存在具体字段词，必须输出 property-level projection。
  - 不能用单个 vertex 概括多个字段。
  - 只有用户明确说“详情/完整节点/节点信息”时才允许 `vertex_full`。
- few-shot 示例必须包含 `qa_9cfa692813d5` 这类多字段投影。
- LLM 输出违反 projection contract 时触发 schema retry；重试后仍失败则进入 `grounded_understanding_schema_invalid` 或 repair path。

验收：

- schema 不再接受 `{ "semantic_type": "vertex", "name": "Service" }` 作为模糊 projection。
- `vertex_full` 必须有明确 intent evidence，例如 `详情/信息/节点`。
- LLM fallback path 对多字段 projection 输出 property items。
- 现有 detail query 样本不被错误改成 property-only projection。

### IR-PC-03 Projection Coverage Validator

目标：在 semantic validator 中补 projection coverage 硬约束，作为通用防线。

依赖：IR-PC-01。

建议文件：

```text
services/cypher_generator_agent/app/validation/semantic_validator.py
services/cypher_generator_agent/app/validation/coverage.py
services/cypher_generator_agent/app/core/errors.py
services/cypher_generator_agent/tests/validation/test_projection_coverage.py
```

开发内容：

- 定义 projection coverage input：
  - decomposition 中被判定为“返回字段”的 substantive/target concept。
  - final binding plan / DSL projection。
- coverage 判定从“词被候选引用”升级为“词进入正确槽位”：

```text
字段词作为返回字段出现 -> 必须进入 projection
字段词作为过滤条件出现 -> 必须进入 filter
字段词作为分组维度出现 -> 必须进入 group_by
字段词作为排序依据出现 -> 必须进入 sort/order_by
```

- 本 IR v1 先实现 projection slot；其他 slot 只预留结构。
- 新增错误码：

```text
projection_coverage_missing
projection_slot_mismatch
projection_owner_ambiguous
```

- 对 `qa_9cfa692813d5` 当前错误 plan，validator 应返回 error：

```json
{
  "code": "projection_coverage_missing",
  "missing_terms": ["名称", "元素类型", "服务质量等级", "带宽", "时延"],
  "expected_owner": "Service"
}
```

验收：

- 如果 decomposition 要求 6 个字段但 projection 只有 `Service.id`，validator fail。
- 如果 projection 中包含全部字段，validator pass。
- 如果字段词只在 selected_properties 中出现但没有进入 DSL projection，validator fail。
- coverage error 会进入 repair / generation_failed，不会继续编译 Cypher。

### IR-PC-04 DSL Builder No Silent ID Downgrade

目标：取消 DSL builder 对模糊 vertex projection 的静默 ID 降级。

依赖：IR-PC-02、IR-PC-03。

建议文件：

```text
services/cypher_generator_agent/app/dsl/builder.py
services/cypher_generator_agent/app/dsl/models.py
services/cypher_generator_agent/app/dsl/parser.py
services/cypher_generator_agent/tests/dsl/test_builder_projection.py
```

开发内容：

- builder 接收 projection 时遵循：
  - property projection -> 编译成 property RETURN。
  - `vertex_full` -> 编译成完整节点 RETURN。
  - 模糊裸 vertex -> 抛出 `unsupported_projection_shape` 或 `ambiguous_projection`.
- 删除或限制当前 “如果 projection 为空则补 ID” 的行为：
  - 仅当 query shape 明确允许 default projection 且 decomposition 没有显式字段词时，才允许补 ID。
  - 一旦存在 projection coverage requirements，禁止默认补 ID。
- 对 detail query 保留显式整节点路径，不使用隐式 ID 降级。

验收：

- 喂入 `{semantic_type: "vertex", name: "Service"}` 的 projection，builder 不再生成 `Service.id`。
- 空 projection + 无显式字段需求的简单 list 可以按产品约定返回默认 ID。
- 空 projection + 有显式字段需求必须失败。
- `vertex_full` 能稳定编译成 `RETURN svc AS service` 或 DSL 中约定的整节点表达。

### IR-PC-05 Self-Validation Shape Guard Extension

目标：补充末端 shape guard，验证 Cypher RETURN aliases 与 DSL projection 一致；不承担自然语言 coverage 判断。

依赖：IR-PC-04。

建议文件：

```text
services/cypher_generator_agent/app/cypher_validation/shape.py
services/cypher_generator_agent/tests/cypher_validation/test_shape_projection.py
```

开发内容：

- 确认 self-validation shape check 比较的是 DSL projection 和 compiler output：
  - RETURN alias 集合/顺序是否和 DSL expected aliases 一致。
  - 参数化 projection 不影响 alias check。
- 不在 self-validation 中直接读取 natural language terms，避免职责漂移。
- 如果 DSL projection 有 6 项，Cypher RETURN 只有 1 项，则 self-validation fail。

验收：

- DSL 6 projection -> Cypher 1 RETURN 的人工 case fail。
- DSL 1 projection -> Cypher 1 RETURN pass。
- self-validation 不误报 detail node return。

### IR-PC-06 Trace and Error Contract for Projection Coverage

目标：让 projection coverage 失败在 trace、运行中心和 repair 输入中可诊断。

依赖：IR-PC-03。

建议文件：

```text
services/cypher_generator_agent/app/observability/trace.py
services/cypher_generator_agent/app/observability/stages.py
services/cypher_generator_agent/app/repair/models.py
services/cypher_generator_agent/tests/observability/test_projection_coverage_trace.py
```

开发内容：

- 在 trace 的 `semantic_validator` stage 输出：

```json
{
  "coverage": {
    "projection": {
      "required_terms": ["ID", "名称", "带宽"],
      "covered_terms": ["ID"],
      "missing_terms": ["名称", "带宽"],
      "slot": "projection"
    }
  }
}
```

- repair controller 输入保留：
  - missing term
  - expected owner
  - candidate properties
  - final projection items
- user-visible clarification 不应把 projection coverage 缺失表达成“某个值未解析”。这是系统绑定缺失，优先进入 repair/generation_failed。

验收：

- `projection_coverage_missing` 在 trace 中能定位到 missing terms。
- Runtime Center 可显示该错误的阶段、原因码、缺失字段。
- repair-agent 能拿到足够上下文判断“缺 projection”而不是误判为 literal 问题。

### IR-PC-07 Regression Matrix Integration

目标：把本 IR 的测试纳入 IR-20 regression matrix，防止后续 prompt / binder / builder 改动回归。

依赖：IR-PC-00 到 IR-PC-06。

建议文件：

```text
services/cypher_generator_agent/tests/fixtures/golden_questions.yaml
services/cypher_generator_agent/tests/integration/test_golden_regression_matrix.py
docs/experiments/2026-05-28-runtime-center-cga-job-analysis.md
```

开发内容：

- 将本轮 8 样本中的以下 case 标记为 projection / slot coverage 回归：
  - `qa_9cfa692813d5`
  - `qa_c80a82efe561`
  - `qa_c2508f2c0bac`
  - `qa_a5f4b0253af3`
- 将 `qa_526d49332ed1`、`qa_c3e83dd7ad32`、`qa_6494b2085699` 保留在相邻 regression scope，但不强行并入 projection coverage IR：
  - `所有` 属于 literal cleanup / control term。
  - `前3` 属于 top_n / limit slot。
  - `IP地址` 属于 property owner binding。
- CI 或本地 regression 命令必须能单独跑 projection coverage slice。

验收：

- projection coverage slice 可独立执行。
- `qa_9cfa692813d5` 修复后不能只靠最终 Cypher 字符串通过，必须 DSL projection 与 expected projection 同时通过。
- 新增 regression case 失败时，错误能指向 projection slot，而不是泛化 testing mismatch。

## 7. 风险与边界

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| 误把 detail query 改成字段投影 | “服务信息/详情”可能需要返回节点，不是字段列表。 | 引入显式 `vertex_full`，只有 detail evidence 时允许。 |
| 多 owner 字段歧义 | `名称/ID/状态` 在多个 vertex 上都存在。 | projection resolver 必须结合局部修饰词、路径 role 和 owner 约束；无法消歧时返回 ambiguity。 |
| prompt 修复过拟合 | few-shot 只让当前样本过，其他字段仍漏。 | 以 resolver + validator 为主，prompt 只作为 schema 契约说明。 |
| builder 改动破坏旧默认行为 | 旧样本可能依赖“默认返回 id”。 | 只在无显式 projection requirement 时保留 default id；有字段需求时禁止 fallback。 |
| coverage 规则过严 | 礼貌词、泛化词、重复词可能被误判 missing。 | projection coverage 只消费已分类为 field-like 的 terms，不消费 stopword/modality。 |

## 8. 审核问题

需要在实施前确认：

1. `vertex_full` 是否作为新的 projection item 类型进入 DSL v1，还是只作为 builder 内部 normalized form？
2. 默认 list 查询在没有显式字段时，是否仍返回 ID？例如“查询所有服务”应返回 `Service.id` 还是完整 `Service` 节点？
3. projection coverage 的 failure 应进入 repair loop，还是直接 generation_failed？
4. 多 owner 字段歧义时，是否允许系统按路径最近对象自动选择，还是必须反问/repair？
5. `schema_version` 是否保持 `grounded_understanding_v1` / `restricted_query_dsl_v1`，还是因为 projection item 类型收紧而升版？

