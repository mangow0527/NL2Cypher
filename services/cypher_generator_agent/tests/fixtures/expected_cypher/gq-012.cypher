MATCH path = (tun:Tunnel)-[:PATH_THROUGH*1..8]->(ne:NetworkElement)
WHERE ne.id = $id
RETURN tun.id AS tunnel_id
