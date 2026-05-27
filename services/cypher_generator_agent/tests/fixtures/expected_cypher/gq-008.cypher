MATCH (ne:NetworkElement)
WHERE ne.elem_type = $elem_type
RETURN count(ne) AS device_count
