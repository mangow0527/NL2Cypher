# Restricted Query DSL v1 设计

> 日期：2026-05-27
> 状态：设计 v1
> 上游：OSI semantic registry、Question Decomposer、Semantic Binder
> 下游：DSL Parser / AST、Cypher Compiler

## 1. 设计目标

Restricted Query DSL v1 是自然语言理解结果和 Cypher 编译器之间的受限中间表示。它的目标不是重造 Cypher，而是覆盖高频、可校验、可模板化编译的查询模式。

原则：

- DSL 只引用 OSI registry 中存在的 semantic id。
- DSL 结构必须能被 JSON Schema 校验。
- DSL 不允许嵌入原生 Cypher。
- DSL 无法表达时返回 `unsupported_query_shape`，不回退到 LLM 直接生成 Cypher。
- 每个 DSL 文档都必须声明 `query_shape`，方便校验、编译和观测。

## 2. v1 覆盖的查询模式

| query_shape | 支持能力 | 示例 |
| --- | --- | --- |
| `entity_lookup` | 按实体类型和过滤条件返回实体属性 | 查询设备 `ne-0001` 的信息 |
| `single_hop_traversal` | 从一个实体经一条关系找另一类实体 | Gold 服务使用了哪些隧道 |
| `variable_path_traversal` | 固定起止类型或 through 条件的多跳遍历 | 找出所有经过设备 `ne-0001` 的隧道 |
| `named_path_pattern` | 引用 registry 中的命名路径模板 | 使用 `tunnel_full_path` 查询隧道完整路径 |
| `aggregate_group_by` | 单层聚合、分组、过滤、排序 | 按状态统计端口数量 |
| `top_n` | 排序取前 N | 端口最多的 5 台设备 |
| `two_step_aggregate` | 先聚合再过滤/排序/投影 | 先按设备统计端口，再取最多的 5 台 |

v1 不支持：

- 任意子查询嵌套。
- OPTIONAL MATCH。
- 图算法。
- 写操作。
- 未命名、无界的全图遍历。
- 原生 Cypher escape hatch。

## 3. 顶层 DSL 结构

```yaml
schema_version: restricted_query_dsl_v1
query_id: q-20260527-001
query_shape: named_path_pattern
source_question: "找出所有经过设备 ne-0001 的隧道"
bindings:
  primary_entity:
    semantic_type: dataset
    semantic_id: tunnel
operations:
  - op: use_path_pattern
    pattern_id: tunnel_full_path
    bind_as: path
    filters:
      - target:
          role_ref: tunnel_full_path.transit_device
        field:
          semantic_id: network_element.name
        operator: eq
        value:
          raw: ne-0001
          normalized: ne-0001
          resolver_match_type: exact
projection:
  items:
    - target:
        role_ref: tunnel_full_path.tunnel
      field:
        semantic_id: tunnel.name
order_by: []
limit: null
assumptions: []
```

顶层字段：

| 字段 | 必需 | 含义 |
| --- | --- | --- |
| `schema_version` | 是 | 固定为 `restricted_query_dsl_v1` |
| `query_id` | 是 | trace 内稳定 ID |
| `query_shape` | 是 | v1 支持的查询形态 |
| `source_question` | 是 | 原始自然语言问题 |
| `bindings` | 是 | 主要实体、关系、指标、字段绑定 |
| `operations` | 是 | 查询操作序列 |
| `projection` | 是 | 输出列或路径 |
| `order_by` | 否 | 排序 |
| `limit` | 否 | 限制条数 |
| `assumptions` | 否 | 高置信 fuzzy 绑定或 warning-only 解释 |

## 4. 单跳遍历

```yaml
query_shape: single_hop_traversal
bindings:
  start:
    semantic_type: dataset
    semantic_id: service
  relationship:
    semantic_type: relationship
    semantic_id: service_uses_tunnel
  end:
    semantic_type: dataset
    semantic_id: tunnel
operations:
  - op: traverse
    from: start
    relationship: relationship
    to: end
    direction: forward
filters:
  - target: start
    field:
      semantic_id: service.quality_of_service
    operator: eq
    value:
      raw: Gold
      normalized: GOLD
      resolver_match_type: synonym
projection:
  items:
    - target: end
      field:
        semantic_id: tunnel.name
```

校验规则：

- `relationship.from` 必须匹配 `from` dataset。
- `relationship.to` 必须匹配 `to` dataset。
- `direction` 只能是 `forward` 或 `backward`，不能靠编译器猜。
- filter field 必须属于对应 target 的 dataset 或可达 metric context。

## 5. 变长路径

变长路径用 `variable_path` 表达，必须有 hop 范围和边类型白名单。

```yaml
query_shape: variable_path_traversal
bindings:
  start:
    semantic_type: dataset
    semantic_id: tunnel
  through:
    semantic_type: dataset
    semantic_id: network_element
operations:
  - op: variable_path
    bind_as: path
    start: start
    through:
      dataset_ref: through
      filters:
        - field:
            semantic_id: network_element.name
          operator: eq
          value:
            raw: ne-0001
            normalized: ne-0001
            resolver_match_type: exact
    allowed_relationships:
      - tunnel_traverses_link
      - link_connects_network_element
    min_hops: 1
    max_hops: 8
projection:
  items:
    - target: start
      field:
        semantic_id: tunnel.name
```

校验规则：

- `max_hops` 必须存在，系统默认上限为 8，可由配置降低。
- `allowed_relationships` 必须非空。
- `through` 节点必须在路径节点类型集合内。
- 如果用户没有给 hop 上限，Semantic Binder 可以使用 path pattern 默认上限；若无默认上限则反问或拒绝。

## 6. 命名 path pattern

path pattern 由 OSI `custom_extensions` 或独立 registry 声明。DSL 通过 `pattern_id` 引用，不内联展开规则。

```yaml
query_shape: named_path_pattern
operations:
  - op: use_path_pattern
    pattern_id: tunnel_full_path
    bind_as: path
    filters:
      - target:
          role_ref: tunnel_full_path.transit_device
        field:
          semantic_id: network_element.name
        operator: eq
        value:
          raw: ne-0001
          normalized: ne-0001
```

pattern registry 示例：

```yaml
pattern_id: tunnel_full_path
root_dataset: tunnel
exports:
  tunnel: tunnel
  source_device: tunnel_endpoint.source_device
  destination_device: tunnel_endpoint.destination_device
  transit_device: transit_chain.any_device
max_hops: 12
relationships:
  - tunnel_endpoint
  - tunnel_traverses_link
  - link_connects_network_element
```

## 7. Path Pattern 角色绑定边界

角色命名空间规则：

- DSL 中的 role 必须写成 `pattern_id.role_name`。
- 嵌套 pattern 的内部 role 不自动暴露。
- 父 pattern 必须通过 `exports` 显式暴露可被过滤、投影、排序的 role。
- 若多个 pattern 嵌套导出同名 role，父 pattern 必须重命名，避免 `device` 这类泛名冲突。

嵌套示例：

```yaml
pattern_id: tunnel_full_path
includes:
  - pattern_id: tunnel_transit_chain
    as: transit_chain
exports:
  transit_device: transit_chain.any_device
  second_hop_device: transit_chain.hop_2_device
```

fallback 规则：

- 如果用户要过滤的语义正好匹配已导出的 role，使用 `role_ref`。
- 如果用户要求“第二跳设备名”，但 pattern 没有导出 `second_hop_device`，系统先检查能否安全降级为 `variable_path` 且保留 hop index 约束。
- 如果无法安全降级，返回 `unsupported_query_shape` 或触发澄清，提示该 path pattern 未暴露所需角色。
- 不允许编译器临时探入 pattern 内部结构并绕过 registry role 边界。

## 8. 聚合、Top-N 与两步聚合

单层聚合：

```yaml
query_shape: aggregate_group_by
operations:
  - op: aggregate
    group_by:
      - target: port
        field:
          semantic_id: port.status
    measures:
      - alias: port_count
        function: count
        target: port
        field:
          semantic_id: port.id
projection:
  items:
    - alias: status
      source: group_by[0]
    - alias: port_count
      source: measure.port_count
```

Top-N：

```yaml
query_shape: top_n
operations:
  - op: aggregate
    group_by:
      - target: device
        field:
          semantic_id: network_element.name
    measures:
      - alias: port_count
        function: count
        target: port
        field:
          semantic_id: port.id
  - op: sort
    by:
      - source: measure.port_count
        direction: desc
  - op: limit
    value: 5
```

两步聚合：

```yaml
query_shape: two_step_aggregate
operations:
  - op: subquery
    bind_as: device_port_counts
    query_shape: aggregate_group_by
    group_by:
      - target: device
        field:
          semantic_id: network_element.id
    measures:
      - alias: port_count
        function: count
        target: port
        field:
          semantic_id: port.id
  - op: filter_subquery
    source: device_port_counts
    predicate:
      field: port_count
      operator: gt
      value: 10
  - op: sort
    by:
      - source: device_port_counts.port_count
        direction: desc
  - op: limit
    value: 5
```

v1 的 `subquery` 只允许包裹 `aggregate_group_by`，不能任意嵌套。

## 9. DSL 不支持时的产品策略

不支持分三类处理：

| 类型 | 示例 | 返回 |
| --- | --- | --- |
| 可拆解 | “先找经过 A 的隧道，再看这些隧道的端口数” | clarification，建议拆成两个支持查询 |
| 超出 v1 能力 | shortest path、connected components、OPTIONAL MATCH | `unsupported_query_shape` |
| 语义层缺失 | 用户问增长率但 OSI 无增长 metric 或时间字段 | semantic coverage failure |

明确禁止：

- 不允许 fallback 到 LLM 直接生成 Cypher。
- 不允许 DSL 中出现 `raw_cypher`、`cypher_fragment`、`where_text`。
- 不允许用字符串拼接绕过 AST。

## 10. 编译前校验

DSL Parser 必须在进入 compiler 前完成：

- JSON Schema 校验。
- semantic_id 存在性校验。
- field 所属 target 校验。
- relationship endpoint 和 direction 校验。
- path pattern role export 校验。
- aggregate function 与字段类型校验。
- limit、max_hops、order_by 合法性校验。

只有 AST 通过这些校验，compiler 才能生成 Cypher。
