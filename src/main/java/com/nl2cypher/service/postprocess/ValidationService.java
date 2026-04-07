package com.nl2cypher.service.postprocess;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.nl2cypher.model.representation.CypherGenerationResult;
import com.nl2cypher.model.representation.QueryBlueprint;
import com.nl2cypher.model.representation.SchemaMappingResult;
import com.nl2cypher.model.representation.ValidationResult;
import com.nl2cypher.service.llm.GLMClient;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import java.io.IOException;

@Slf4j
@Service
public class ValidationService {
    private final GLMClient glmClient;
    private final Gson gson;

    private static final String SYSTEM_PROMPT = """
        你是一个专业的Cypher查询验证专家，专门负责对生成的Cypher语句进行深度验证和智能纠错。
        你的任务是验证Cypher语句的正确性、语义一致性、意图匹配度，并提供优化建议。
        
        请按照以下JSON格式输出验证结果：
        {
          "cypher_validation": {
            "syntax_check": {
              "status": "passed/failed",
              "errors": ["错误信息列表"],
              "suggestions": ["改进建议列表"]
            },
            "semantic_check": {
              "schema_compatibility": "valid/invalid",
              "type_safety": "valid/invalid", 
              "relation_direction": "correct/incorrect",
              "issues": ["问题列表"]
            },
            "intent_match": {
              "original_intent": "原始意图描述",
              "cypher_intent": "Cypher查询意图描述",
              "match_score": 0.95,
              "assessment": "评估结果"
            },
            "performance_analysis": {
              "estimated_complexity": "simple/medium/complex",
              "suggested_indexes": ["索引建议列表"],
              "optimization_tips": ["优化建议列表"]
            }
          },
          "query_explanation": {
            "natural_language_explanation": "查询的自然语言解释",
            "execution_steps": ["执行步骤列表"],
            "equivalent_queries": [
              {
                "query": "等效的Cypher查询",
                "advantage": "优势说明"
              }
            ],
            "optimization_suggestions": {
              "immediate": ["立即可以实施的优化"],
              "long_term": ["长期优化建议"]
            }
          }
        }
        
        请只输出JSON格式的结果，不要添加任何解释。
        """;

    public ValidationService(GLMClient glmClient) {
        this.glmClient = glmClient;
        this.gson = new Gson();
    }

    public ValidationResult validate(String originalQuery, CypherGenerationResult generationResult, 
                                     QueryBlueprint blueprint, SchemaMappingResult schemaMapping) throws IOException {
        log.info("开始验证Cypher语句: {}", generationResult.getFormattedCypher());

        String userPrompt = buildPrompt(originalQuery, generationResult, blueprint, schemaMapping);

        String response = glmClient.chat(SYSTEM_PROMPT, userPrompt);
        log.debug("验证原始响应: {}", response);

        try {
            JsonObject jsonResult = JsonParser.parseString(response).getAsJsonObject();
            ValidationResult validationResult = gson.fromJson(jsonResult, ValidationResult.class);

            ValidationResult.OverallScore overallScore = calculateOverallScore(validationResult, generationResult);
            validationResult.setOverallScore(overallScore);

            log.info("验证完成，总分: {}, 是否通过阈值: {}", 
                overallScore.getTotalScore(), overallScore.isPassedThreshold());

            return validationResult;

        } catch (Exception e) {
            log.error("解析验证结果失败: {}", e.getMessage());
            throw new IOException("解析验证结果失败: " + e.getMessage(), e);
        }
    }

    private String buildPrompt(String originalQuery, CypherGenerationResult generationResult, 
                               QueryBlueprint blueprint, SchemaMappingResult schemaMapping) {
        StringBuilder prompt = new StringBuilder();
        
        prompt.append("请验证以下Cypher查询的正确性并提供优化建议：\n\n");
        
        prompt.append("原始查询：\"").append(originalQuery).append("\"\n\n");
        
        prompt.append("生成的Cypher：\n");
        prompt.append(generationResult.getFormattedCypher()).append("\n\n");
        
        prompt.append("生成置信度：").append(generationResult.getConfidence()).append("\n\n");
        
        prompt.append("查询蓝图：\n");
        prompt.append(gson.toJson(blueprint)).append("\n\n");
        
        prompt.append("Schema映射结果：\n");
        prompt.append(gson.toJson(schemaMapping.getMappingResult())).append("\n\n");
        
        prompt.append("请按照要求的JSON格式输出验证结果。");
        
        return prompt.toString();
    }

    private ValidationResult.OverallScore calculateOverallScore(ValidationResult validationResult, 
                                                                 CypherGenerationResult generationResult) {
        double syntaxScore = calculateSyntaxScore(validationResult);
        double semanticScore = calculateSemanticScore(validationResult);
        double intentScore = calculateIntentScore(validationResult);
        double performanceScore = calculatePerformanceScore(validationResult);

        double totalScore = (syntaxScore * 0.3 + semanticScore * 0.25 + 
                           intentScore * 0.25 + performanceScore * 0.2);

        boolean passedThreshold = totalScore >= 0.7;

        return ValidationResult.OverallScore.builder()
            .totalScore(totalScore)
            .syntaxScore(syntaxScore)
            .semanticScore(semanticScore)
            .intentScore(intentScore)
            .performanceScore(performanceScore)
            .passedThreshold(passedThreshold)
            .threshold(0.7)
            .build();
    }

    private double calculateSyntaxScore(ValidationResult validationResult) {
        if (validationResult.getCypherValidation() == null) {
            return 0.5;
        }

        ValidationResult.SyntaxCheck syntaxCheck = validationResult.getCypherValidation().getSyntaxCheck();
        if (syntaxCheck == null) {
            return 0.5;
        }

        double score = 0.5;
        
        if ("passed".equals(syntaxCheck.getStatus())) {
            score += 0.3;
        }
        
        if (syntaxCheck.getErrors() == null || syntaxCheck.getErrors().isEmpty()) {
            score += 0.2;
        }

        return Math.min(score, 1.0);
    }

    private double calculateSemanticScore(ValidationResult validationResult) {
        if (validationResult.getCypherValidation() == null) {
            return 0.5;
        }

        ValidationResult.SemanticCheck semanticCheck = validationResult.getCypherValidation().getSemanticCheck();
        if (semanticCheck == null) {
            return 0.5;
        }

        double score = 0.3;

        if ("valid".equals(semanticCheck.getSchemaCompatibility())) {
            score += 0.3;
        }

        if ("valid".equals(semanticCheck.getTypeSafety())) {
            score += 0.2;
        }

        if ("correct".equals(semanticCheck.getRelationDirection())) {
            score += 0.2;
        }

        return Math.min(score, 1.0);
    }

    private double calculateIntentScore(ValidationResult validationResult) {
        if (validationResult.getCypherValidation() == null) {
            return 0.5;
        }

        ValidationResult.IntentMatch intentMatch = validationResult.getCypherValidation().getIntentMatch();
        if (intentMatch == null) {
            return 0.5;
        }

        return Math.min(intentMatch.getMatchScore(), 1.0);
    }

    private double calculatePerformanceScore(ValidationResult validationResult) {
        if (validationResult.getCypherValidation() == null) {
            return 0.5;
        }

        ValidationResult.PerformanceAnalysis performanceAnalysis = 
            validationResult.getCypherValidation().getPerformanceAnalysis();
        if (performanceAnalysis == null) {
            return 0.5;
        }

        double score = 0.6;

        String complexity = performanceAnalysis.getEstimatedComplexity();
        if ("simple".equals(complexity)) {
            score += 0.4;
        } else if ("medium".equals(complexity)) {
            score += 0.2;
        }

        return Math.min(score, 1.0);
    }
}
