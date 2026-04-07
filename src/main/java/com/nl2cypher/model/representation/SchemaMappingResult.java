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
public class SchemaMappingResult {
    private DatabaseSchema databaseSchema;
    private MappingResult mappingResult;

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class DatabaseSchema {
        private Map<String, NodeSchema> nodes;
        private Map<String, RelationSchema> relationships;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class NodeSchema {
        private String label;
        private Map<String, String> properties;
        private List<String> indexes;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class RelationSchema {
        private String type;
        private String fromNode;
        private String toNode;
        private Map<String, String> properties;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class MappingResult {
        private boolean validated;
        private TypeChecking typeChecking;
        private Map<String, String> relationValidation;
        private List<String> indexSuggestions;
        private List<String> validationErrors;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class TypeChecking {
        private Map<String, String> fieldValidations;
    }
}
