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
public class SemanticAnalysisResult {
    private String originalQuery;
    private SemanticAnalysis semanticAnalysis;

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class SemanticAnalysis {
        private String mainIntent;
        private List<String> subIntents;
        private EntityInfo entities;
        private List<String> relations;
        private List<ConditionInfo> conditions;
        private Map<String, String> ambiguityResolution;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class EntityInfo {
        private List<String> explicit;
        private List<String> implicit;
        private Map<String, String> typeMapping;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class ConditionInfo {
        private String type;
        private String field;
        private String operator;
        private Object value;
    }
}
