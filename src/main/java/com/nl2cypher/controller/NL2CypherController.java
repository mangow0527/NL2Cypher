package com.nl2cypher.controller;

import com.nl2cypher.model.representation.NL2CypherResult;
import com.nl2cypher.service.orchestration.NL2CypherOrchestrator;
import lombok.Data;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@Slf4j
@RestController
@RequestMapping("/api/nl2cypher")
public class NL2CypherController {

    private final NL2CypherOrchestrator orchestrator;

    public NL2CypherController(NL2CypherOrchestrator orchestrator) {
        this.orchestrator = orchestrator;
    }

    @PostMapping("/convert")
    public ResponseEntity<ConversionResponse> convert(@RequestBody ConversionRequest request) {
        log.info("收到NL2Cypher转换请求: {}", request.getQuery());

        try {
            NL2CypherResult result = orchestrator.convert(request.getQuery());

            if (result.isSuccess()) {
                return ResponseEntity.ok(ConversionResponse.builder()
                    .success(true)
                    .originalQuery(result.getOriginalQuery())
                    .generatedCypher(result.getGeneratedCypher())
                    .reasoning(result.getReasoning())
                    .confidence(result.getConfidence())
                    .validationScore(result.getMetadata() != null ? 
                        (Double) result.getMetadata().get("validationScore") : 0.0)
                    .processingTimeMs(result.getProcessingTimeMs())
                    .validationResult(result.getValidationResult())
                    .build());
            } else {
                return ResponseEntity.badRequest().body(ConversionResponse.builder()
                    .success(false)
                    .originalQuery(result.getOriginalQuery())
                    .errorMessage(result.getErrorMessage())
                    .processingTimeMs(result.getProcessingTimeMs())
                    .build());
            }

        } catch (Exception e) {
            log.error("转换过程中发生错误: {}", e.getMessage(), e);
            return ResponseEntity.internalServerError().body(ConversionResponse.builder()
                .success(false)
                .errorMessage("系统错误: " + e.getMessage())
                .build());
        }
    }

    @GetMapping("/health")
    public ResponseEntity<HealthResponse> health() {
        return ResponseEntity.ok(new HealthResponse("UP", "NL2Cypher系统运行正常"));
    }

    @Data
    public static class ConversionRequest {
        private String query;
    }

    @Data
    @lombok.Builder
    public static class ConversionResponse {
        private boolean success;
        private String originalQuery;
        private String generatedCypher;
        private String reasoning;
        private double confidence;
        private double validationScore;
        private long processingTimeMs;
        private String errorMessage;
        private com.nl2cypher.model.representation.ValidationResult validationResult;
    }

    @Data
    @lombok.AllArgsConstructor
    public static class HealthResponse {
        private String status;
        private String message;
    }
}
