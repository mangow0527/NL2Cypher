# OSI Cypher Generation Sprint 0 Glossary

> 日期：2026-05-27
> 状态：设计 v1
> 目的：统一 OSI、图数据库、DSL 和代码内部命名

## 1. 命名原则

v1 代码内部以 OSI 术语为主，以图数据库术语为物理实现补充。

原因：

- OSI 原生 schema 使用 `dataset`、`relationship`、`field`、`metric`。
- DSL、Validator、Trace 应尽量靠近 OSI，减少模型交换时的翻译成本。
- TuGraph 编译层可以使用 `vertex`、`edge`、`property`，但这些属于 physical binding，不应反向污染语义层。

## 2. 标准术语表

| 标准术语 | 可出现别名 | 代码内部用法 | 说明 |
| --- | --- | --- | --- |
| `relationship` | edge | 语义层、DSL、Validator 统一用 `relationship` | 表示 OSI datasets 之间的可连接关系；编译到 TuGraph 时才映射到 edge label |
| `edge` | relationship | 仅 physical graph binding 和 compiler 输出使用 | 表示 TuGraph 中实际边类型 |
| `dataset` | vertex、node、table | OSI registry 和 DSL 统一用 `dataset` | 表示业务实体、事实表或逻辑视图 |
| `vertex` | node | 仅 graph binding 和 compiler 使用 | 表示 TuGraph 中实际点类型 |
| `node` | vertex | 避免作为代码字段名 | 只在解释图概念时使用，避免和 runtime node/process 混淆 |
| `field` | property、column | 语义层、DSL、Validator 统一用 `field` | 表示可过滤、投影、分组或表达式引用的语义字段 |
| `property` | field | 仅 graph binding 和 compiler 使用 | 表示 TuGraph vertex/edge property |
| `column` | field | 仅 OSI source 或 SQL dialect expression 使用 | 表示物理表列或表达式列 |
| `metric` | measure | OSI registry 使用 `metric` | 表示可复用的业务指标定义 |
| `measure` | metric | DSL 聚合操作内部使用 `measure` | 表示本次查询中的聚合输出，可能来自 OSI metric，也可能是受限 ad hoc aggregate |
| `path_pattern` | path template | DSL 和 registry 统一用 `path_pattern` | 表示命名图路径模板 |
| `role_ref` | role | DSL 引用 pattern role 时使用 `role_ref` | 必须带命名空间，如 `tunnel_full_path.transit_device` |

## 3. 代码命名约定

推荐：

- `RelationshipBinding`
- `DatasetBinding`
- `FieldBinding`
- `MetricBinding`
- `MeasureExpression`
- `GraphEdgeBinding`
- `GraphVertexBinding`
- `PathPatternRegistry`

避免：

- 在 semantic 层使用 `EdgeBinding`。
- 在 DSL schema 中混用 `edge_id` 和 `relationship_id`。
- 在同一个对象中同时出现 `field` 和 `property` 指向同一概念。
- 把 OSI metric 和 DSL measure 都命名为 `metric`。

## 4. 文档写法

文档第一次提到跨域概念时可以双写：

- relationship / graph edge
- dataset / graph vertex
- field / graph property
- metric / query measure

字段名、JSON Schema、DSL 示例必须只使用标准术语。

## 5. 迁移约束

如果上游 OSI extension 或历史 TuGraph YAML 已经使用 `edges`：

- loader 可以接受 `edges` 作为输入兼容字段。
- registry normalization 必须转换为 `relationships`。
- trace 中记录原始来源字段，但 normalized 输出只暴露 `relationship`。
- DSL 不接受 `edge` 字段。
