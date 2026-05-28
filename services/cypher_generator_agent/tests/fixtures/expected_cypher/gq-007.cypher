MATCH (port:Port)
WHERE port.status = $status
RETURN port.id AS port_id
