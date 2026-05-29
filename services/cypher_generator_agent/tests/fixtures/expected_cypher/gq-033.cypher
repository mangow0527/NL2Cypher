MATCH (svc:Service)
WHERE svc.quality_of_service = $quality_of_service
RETURN svc.id AS service_id, svc.name AS service_name, svc.bandwidth AS service_bandwidth
