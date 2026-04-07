package com.nl2cypher.model.representation;

import lombok.Data;
import lombok.Builder;
import lombok.AllArgsConstructor;
import lombok.NoArgsConstructor;
import java.util.List;
import java.util.Map;

@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
public class ValidationResult {
    private CypherValidation cypherValidation;
    private QueryExplanation queryExplanation;
    private OverallScore overallScore;

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class CypherValidation {
        private SyntaxCheck syntaxCheck;
        private SemanticCheck semanticCheck;
        private IntentMatch intentMatch;
        private PerformanceAnalysis performanceAnalysis;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class SyntaxCheck {
        private String status;
        private List<String> errors;
        private List<String> suggestions;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class SemanticCheck {
        private String schemaCompatibility;
        private String typeSafety;
        private String relationDirection;
        private List<String> issues;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class IntentMatch {
        private String originalIntent;
        private String cypherIntent;
        private double matchScore;
        private String assessment;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class PerformanceAnalysis {
        private String estimatedComplexity;
        private List<String> suggestedIndexes;
        private List<String> optimizationTips;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class QueryExplanation {
        private String naturalLanguageExplanation;
        private List<String> executionSteps;
        private List<EquivalentQuery> equivalentQueries;
        private OptimizationSuggestions optimizationSuggestions;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class EquivalentQuery {
        private String query;
        private String advantage;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class OptimizationSuggestions {
        private List<String> immediate;
        private List<String> longTerm;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class OverallScore {
        private double totalScore;
        private double syntaxScore;
        private double semanticScore;
        private double intentScore;
        private double performanceScore;
        private boolean passedThreshold;
        private double threshold;
    }
}
