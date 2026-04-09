NETWORK_SCHEMA_V10_CONTEXT = """
Graph: network_schema_v10

Vertex labels:
- NetworkElement(id, name, elem_type, ip_address, location, model, software_version, vendor)
- Protocol(id, name, ietf_category, standard, version)
- Tunnel(id, name, elem_type, bandwidth, latency, ietf_standard)
- Service(id, name, elem_type, bandwidth, latency, quality_of_service)
- Port(id, name, elem_type, speed, mac_address, status, vlan_id)
- Fiber(id, name, elem_type, bandwidth_capacity, length, location, wavelength)
- Link(id, name, elem_type, bandwidth, latency, mtu, admin_status, protocol, status, vlan_id)

Edge labels:
- (NetworkElement)-[:HAS_PORT]->(Port)
- (Fiber)-[:FIBER_SRC]->(Port)
- (Fiber)-[:FIBER_DST]->(Port)
- (Link)-[:LINK_SRC]->(Port)
- (Link)-[:LINK_DST]->(Port)
- (Tunnel)-[:TUNNEL_SRC]->(NetworkElement)
- (Tunnel)-[:TUNNEL_DST]->(NetworkElement)
- (Tunnel)-[:TUNNEL_PROTO]->(Protocol)
- (Tunnel)-[:PATH_THROUGH {hop_order}]->(NetworkElement)
- (Service)-[:SERVICE_USES_TUNNEL]->(Tunnel)
""".strip()


NETWORK_SCHEMA_V10_HINTS = {
    "network_element": {
        "label": "NetworkElement",
        "keywords": ["networkelement", "network element", "网络设备", "设备", "router", "节点"],
        "return_fields": ["n.id AS id", "n.name AS name", "n.ip_address AS ip_address", "n.location AS location"],
    },
    "port": {
        "label": "Port",
        "keywords": ["port", "端口", "接口"],
        "return_fields": ["p.id AS id", "p.name AS name", "p.status AS status", "p.vlan_id AS vlan_id"],
    },
    "tunnel": {
        "label": "Tunnel",
        "keywords": ["tunnel", "隧道"],
        "return_fields": ["t.id AS id", "t.name AS name", "t.bandwidth AS bandwidth", "t.latency AS latency"],
    },
    "service": {
        "label": "Service",
        "keywords": ["service", "业务", "服务"],
        "return_fields": ["s.id AS id", "s.name AS name", "s.bandwidth AS bandwidth", "s.quality_of_service AS quality_of_service"],
    },
    "protocol": {
        "label": "Protocol",
        "keywords": ["protocol", "协议"],
        "return_fields": ["p.id AS id", "p.name AS name", "p.standard AS standard", "p.version AS version"],
    },
    "fiber": {
        "label": "Fiber",
        "keywords": ["fiber", "光纤"],
        "return_fields": ["f.id AS id", "f.name AS name", "f.length AS length", "f.location AS location"],
    },
    "link": {
        "label": "Link",
        "keywords": ["link", "链路"],
        "return_fields": ["l.id AS id", "l.name AS name", "l.bandwidth AS bandwidth", "l.status AS status"],
    },
}
