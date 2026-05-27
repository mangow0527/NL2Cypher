# LiteralResolver v1 设计

> 日期：2026-05-27
> 状态：设计 v1
> 上游：Question Decomposer、Candidate Retriever、Semantic Binder
> 下游：Semantic Validator、Repair and Clarification Controller

## 1. 设计目标

LiteralResolver 是独立子系统，负责把自然语言中的字面值解析为 OSI 语义层和实际数据中可用的规范值。

字面值包括：

- 枚举值：`Gold`、`down`、`MPLS-TE`。
- 业务 ID：`ne-0001`、`svc-1234`。
- 名称：设备名、服务名、隧道名。
- 时间值：`最近 7 天`、`2024 年`。
- 数值过滤：`大于 100G`、`前 5 个`。

该组件不能只是 Candidate Retriever 的一条策略。网络拓扑场景中枚举值、ID 和名称高频出现，解析错误会直接导致空结果或错误结果。

## 2. 输入输出契约

输入：

```json
{
  "schema_version": "literal_resolver_request_v1",
  "raw_literal": "Gold",
  "expected_dataset": "service",
  "expected_field": "service.quality_of_service",
  "literal_kind_hint": "enum_or_name",
  "question_context": "Gold 级别的服务都用了哪些 MPLS-TE 隧道",
  "trace_id": "q-20260527-001"
}
```

输出：

```json
{
  "schema_version": "literal_resolver_result_v1",
  "raw_literal": "Gold",
  "resolved": true,
  "resolved_value": "GOLD",
  "normalized_value": "GOLD",
  "match_type": "synonym",
  "confidence": 0.98,
  "expected_dataset": "service",
  "expected_field": "service.quality_of_service",
  "evidence": [
    {
      "source": "value_synonym_registry",
      "matched": "Gold",
      "target": "GOLD"
    }
  ],
  "alternatives": [],
  "requires_user_choice": false
}
```

失败输出：

```json
{
  "schema_version": "literal_resolver_result_v1",
  "raw_literal": "GLOD",
  "resolved": false,
  "resolved_value": null,
  "normalized_value": null,
  "match_type": "unresolved",
  "confidence": 0.0,
  "expected_dataset": "service",
  "expected_field": "service.quality_of_service",
  "evidence": [],
  "alternatives": [
    {
      "value": "GOLD",
      "display": "Gold",
      "confidence": 0.82,
      "source": "distinct_value_cache"
    },
    {
      "value": "BRONZE",
      "display": "Bronze",
      "confidence": 0.61,
      "source": "distinct_value_cache"
    }
  ],
  "requires_user_choice": true
}
```

## 3. 解析流水线

解析顺序固定：

1. `exact_value_match`：对 registry 中规范值做大小写和标准化后的精确匹配。
2. `value_synonym_match`：对 OSI `ai_context.synonyms` 或 value synonym registry 做精确同义词匹配。
3. `typed_parser`：对时间、数值、容量、百分比等类型化字面值做解析。
4. `fuzzy_text_match`：对低风险名称类字段做编辑距离或 token 相似度匹配。
5. `embedding_match`：仅对名称类或描述类字段启用，默认不用于高风险枚举。
6. `distinct_value_lookup`：从缓存的 distinct values 中查找候选。
7. `db_live_lookup`：在缓存 miss 且字面值像 ID/精确名称时，打实时只读查询确认。

高风险枚举字段策略：

- 先 exact，再 synonym，再 distinct。
- 不使用 embedding 自动通过。
- fuzzy 命中只能给 alternatives，不能直接 resolved。

名称/ID 字段策略：

- 如果 raw literal 符合 ID 形态，例如 `ne-0001`，缓存 miss 后允许 live lookup。
- live lookup 命中即 `match_type=db_live_exact`。
- live lookup 未命中时可返回 alternatives，但不能把相近 ID 静默替换。

## 4. Match Type

| match_type | 可自动通过 | 说明 |
| --- | --- | --- |
| `exact` | 是 | 规范值直接匹配 |
| `synonym` | 是 | 明确同义词表匹配 |
| `typed_parse` | 是 | 时间、数值、容量等解析成功 |
| `db_live_exact` | 是 | 实时数据库精确命中 |
| `fuzzy_text` | 视置信度 | 名称类字段可高置信通过 |
| `embedding` | 视字段风险 | 不用于枚举自动通过 |
| `distinct_candidate` | 否 | 只作为 alternatives |
| `unresolved` | 否 | 进入澄清或覆盖缺失 |

置信度阈值默认：

- `>= 0.95`：可自动通过。
- `0.80 - 0.95`：如字段低风险且候选领先明显，可带 assumption 通过。
- `< 0.80`：不得自动通过。
- top-2 差距 `< 0.10`：必须反问用户。

## 5. Distinct Value Cache

配置：

```yaml
literal_resolver:
  distinct_value_cache:
    ttl_seconds: 3600
    negative_ttl_seconds: 60
    max_values_per_field: 5000
    hot_value_window_seconds: 86400
    allow_live_lookup_on_cache_miss_for_id_like_values: true
```

缓存键：

```text
semantic_model_id + dataset_id + field_id + tenant_id + data_version
```

失效策略：

- 支持 TTL 被动失效。
- 支持写入触发主动失效：CDC、write callback 或手动 refresh endpoint。
- 对 ID/名称字段，cache miss 不立即判 unresolved；若 raw literal 形态像精确 ID，先走 live lookup。
- negative cache TTL 必须短，避免新写入数据被长时间误判不存在。

热点策略：

- `max_values_per_field` 只限制完整 distinct 列表缓存。
- 另维护 hot value map，记录近期命中值和命中次数。
- 大维度字段优先缓存 hot values，再按需分页 distinct lookup。

监控指标：

- `literal_cache_hit_rate`
- `literal_cache_miss_rate`
- `literal_live_lookup_count`
- `literal_live_lookup_hit_rate`
- `literal_negative_cache_hit_count`
- `literal_unresolved_count`
- `literal_ambiguous_count`

上线后如果某字段 cache hit rate 长期偏低，需调整 TTL、主动失效或 hot value 策略。

## 6. Alternatives 生成规则

alternatives 面向用户澄清，必须简短、可选择、有证据：

```json
{
  "value": "GOLD",
  "display": "Gold",
  "confidence": 0.82,
  "source": "distinct_value_cache",
  "why": "与输入 GLOD 编辑距离最近，并且属于 service.quality_of_service 的合法值"
}
```

规则：

- 最多返回 3 个。
- 按 confidence 降序。
- 不能返回跨字段候选，例如把 `status=down` 候选给 `quality_of_service`。
- 对用户可见的 display 使用业务展示值，不暴露内部编码，除非编码本身就是用户输入对象。

## 7. 与语义校验的关系

LiteralResolver 不决定整个查询是否可生成。它只输出：

- resolved value。
- match_type。
- confidence。
- alternatives。
- evidence。

Semantic Validator 根据这些信号决策：

- 高置信 exact/synonym 可放行。
- fuzzy/embedding 需要结合字段风险和候选差距。
- unresolved 的 substantive literal 必须澄清或失败。
- 低置信高风险枚举不能自动通过。

## 8. 错误码

| 错误码 | 含义 | 默认处理 |
| --- | --- | --- |
| `literal_unresolved` | 找不到可用值 | 反问或 semantic coverage failure |
| `literal_ambiguous` | 多候选接近 | 反问用户 |
| `literal_field_mismatch` | 字面值被绑定到错误字段 | repair loop |
| `literal_cache_stale_suspected` | cache miss 但 live lookup 命中 | 记录 stale signal 并刷新缓存 |
| `literal_live_lookup_failed` | 实时查询失败 | 保留缓存结果，不静默误判 |

## 9. 测试要求

v1 实现时至少覆盖：

- `Gold` -> `GOLD` synonym。
- `GLOD` -> alternatives，不自动通过。
- 新写入 ID cache miss 后 live lookup 命中。
- 高风险枚举不因 embedding 相近被自动改写。
- top-2 候选接近时要求用户选择。
- negative cache 在短 TTL 后允许重新查询。
