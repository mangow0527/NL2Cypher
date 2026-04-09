# network_schema_v10 Schema Profile

这份画像来自真实 TuGraph `network_schema_v10` 的在线探测结果。

## Vertex Labels

- `NetworkElement`
  - 主键：`id`
  - 属性：`elem_type`, `id`, `ip_address`, `location`, `model`, `name`, `software_version`, `vendor`
- `Protocol`
  - 主键：`id`
  - 属性：`id`, `ietf_category`, `name`, `standard`, `version`
- `Tunnel`
  - 主键：`id`
  - 属性：`bandwidth`, `latency`, `elem_type`, `id`, `ietf_standard`, `name`
- `Service`
  - 主键：`id`
  - 属性：`bandwidth`, `latency`, `elem_type`, `id`, `name`, `quality_of_service`
- `Port`
  - 主键：`id`
  - 属性：`speed`, `elem_type`, `id`, `mac_address`, `name`, `status`, `vlan_id`
- `Fiber`
  - 主键：`id`
  - 属性：`bandwidth_capacity`, `length`, `elem_type`, `id`, `location`, `name`, `wavelength`
- `Link`
  - 主键：`id`
  - 属性：`bandwidth`, `latency`, `mtu`, `admin_status`, `elem_type`, `id`, `name`, `protocol`, `status`, `vlan_id`

## Edge Labels

- `(:NetworkElement)-[:HAS_PORT]->(:Port)`
- `(:Fiber)-[:FIBER_SRC]->(:Port)`
- `(:Fiber)-[:FIBER_DST]->(:Port)`
- `(:Link)-[:LINK_SRC]->(:Port)`
- `(:Link)-[:LINK_DST]->(:Port)`
- `(:Tunnel)-[:TUNNEL_SRC]->(:NetworkElement)`
- `(:Tunnel)-[:TUNNEL_DST]->(:NetworkElement)`
- `(:Tunnel)-[:TUNNEL_PROTO]->(:Protocol)`
- `(:Tunnel)-[:PATH_THROUGH {hop_order}]->(:NetworkElement)`
- `(:Service)-[:SERVICE_USES_TUNNEL]->(:Tunnel)`

## Data Sample Notes

我还额外验证了一条真实查询：

```cypher
MATCH (n) RETURN n LIMIT 1
```

返回样本节点是：
- label: `NetworkElement`
- name: `NetworkElement_001`
- ip: `10.0.0.1`

## 当前生成器的启发式映射

查询语句生成服务已经开始用这份 schema 画像做轻量启发式生成：

- 问“设备/网络设备/router” -> `NetworkElement`
- 问“端口/接口” -> `Port`
- 问“隧道” -> `Tunnel`
- 问“服务/业务” -> `Service`
- 问“协议” -> `Protocol`
- 问“光纤” -> `Fiber`
- 问“链路” -> `Link`
- 问“设备及其端口” -> `HAS_PORT`
- 问“服务使用哪些隧道” -> `SERVICE_USES_TUNNEL`
- 问“隧道使用什么协议” -> `TUNNEL_PROTO`
- 问“隧道经过哪些设备” -> `PATH_THROUGH`
