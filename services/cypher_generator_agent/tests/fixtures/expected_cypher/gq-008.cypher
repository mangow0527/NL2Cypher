MATCH (ne:NetworkElement)
WHERE ne.elem_type = 'firewall'
RETURN count(ne) AS device_count
