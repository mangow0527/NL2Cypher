MATCH (svc:Service)-[:SERVICE_USES_TUNNEL]->(tun:Tunnel)
WHERE svc.id = $id
RETURN tun.id AS tunnel_id
