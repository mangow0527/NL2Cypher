MATCH (t:Tunnel {id: $tunnel_id})-[p:PATH_THROUGH]->(ne:NetworkElement)
RETURN ne AS device, p.hop_order AS hop
ORDER BY p.hop_order ASC
