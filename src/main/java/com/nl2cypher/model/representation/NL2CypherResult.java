package com.nl2cypher.model.representation;

import lombok.Data;
import lombok.Builder;
import lombok.AllArgsConstructor;
import lombok.NoArgsConstructor;
import java.util.Map;

@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
public class NL2CypherResult {
    private String originalQuery;
    private String generatedCypher;
    private ValidationResult validationResult;
    private String reasoning;
    private double confidence;
    private Map<String, Object> metadata;
    private boolean success;
    private String errorMessage;
    private long processingTimeMs;
}
