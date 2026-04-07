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
public class QueryBlueprint {
    private String queryType;
    private String complexity;
    private QueryComponents components;

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class QueryComponents {
        private MatchPattern matchPattern;
        private List<WhereCondition> whereConditions;
        private ReturnStatement returnStatement;
        private List<OptionalClause> optionalClauses;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class MatchPattern {
        private NodeInfo mainNode;
        private List<RelatedNodeInfo> relatedNodes;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class NodeInfo {
        private String variable;
        private String label;
        private String alias;
        private List<NodeCondition> conditions;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class RelatedNodeInfo {
        private String variable;
        private String label;
        private RelationInfo relation;
        private List<NodeCondition> conditions;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class RelationInfo {
        private String type;
        private String direction;
        private String pattern;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class NodeCondition {
        private String field;
        private String operator;
        private Object value;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class WhereCondition {
        private String nodeVariable;
        private List<ConditionDetail> conditions;
        private String logicalOperator;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class ConditionDetail {
        private String field;
        private String operator;
        private Object value;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class ReturnStatement {
        private List<String> variables;
        private String description;
        private List<String> aggregations;
        private List<String> orderBy;
        private Integer limit;
    }

    @Data
    @Builder
    @AllArgsConstructor
    @NoArgsConstructor
    public static class OptionalClause {
        private String type;
        private Map<String, Object> parameters;
    }
}
