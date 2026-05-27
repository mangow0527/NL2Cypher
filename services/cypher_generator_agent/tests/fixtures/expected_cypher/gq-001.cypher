MATCH (svc:Service)-[:SERVICE_USES_TUNNEL]->(tun:Tunnel)
WHERE svc.quality_of_service = $quality_of_service
RETURN tun.id AS tunnel_id
