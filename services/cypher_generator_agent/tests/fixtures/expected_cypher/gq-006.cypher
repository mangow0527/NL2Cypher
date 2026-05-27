MATCH (ne:NetworkElement)-[:HAS_PORT]->(port:Port)
WHERE ne.id = $id
RETURN port.id AS port_id
