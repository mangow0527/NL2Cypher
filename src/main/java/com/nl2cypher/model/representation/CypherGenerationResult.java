package com.nl2cypher.model.representation;

import lombok.Data;
import lombok.Builder;
import lombok.AllArgsConstructor;
import lombok.NoArgsConstructor;

@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
public class CypherGenerationResult {
    private String cypher;
    private String formattedCypher;
    private String reasoning;
    private double confidence;
    private List<String> syntaxErrors;
    private List<String> warnings;
}
