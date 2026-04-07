package com.nl2cypher.service.generation;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.nl2cypher.model.representation.CypherGenerationResult;
import com.nl2cypher.model.representation.QueryBlueprint;
import com.nl2cypher.model.representation.SchemaMappingResult;
import com.nl2cypher.service.llm.QwenLocalClient;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import java.io.IOException;
import java.util.Arrays;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Slf4j
@Service
public class CypherGenerationService {
    private final QwenLocalClient qwenClient;
    private final Gson gson;
    private final CypherSyntaxValidator syntaxValidator;

    private static final String SYSTEM_PROMPT = """
        你是一个专业的Cypher查询生成助手，擅长将结构化的查询信息转换为准确的Cypher语句。
        你的任务是基于提供的查询蓝图和Schema映射结果，生成可以在Neo4j数据库中执行的Cypher语句。
        
        请按照以下规则生成Cypher语句：
        1. MATCH子句：构建正确的节点和关系模式
        2. WHERE子句：添加必要的过滤条件
        3. RETURN子句：返回需要的节点或属性
        4. 使用标准的Cypher语法和命名规范
        5. 字符串值使用单引号括起来
        6. 数值不需要引号
        7. 布尔值使用true/false
        8. 不要添加任何解释，只输出Cypher语句
        
        请按照以下JSON格式输出：
        {
          "cypher": "生成的Cypher语句",
          "reasoning": "生成逻辑的简要说明"
        }
        
        注意：只输出JSON格式的结果，不要添加任何其他解释。
        """;

    public CypherGenerationService(QwenLocalClient qwenClient) {
        this.qwenClient = qwenClient;
        this.gson = new Gson();
        this.syntaxValidator = new CypherSyntaxValidator();
    }

    public CypherGenerationResult generate(String query, QueryBlueprint blueprint, SchemaMappingResult schemaMapping) throws IOException {
        log.info("开始生成Cypher语句: {}", query);

        String userPrompt = buildPrompt(query, blueprint, schemaMapping);

        String response = qwenClient.chat(SYSTEM_PROMPT, userPrompt);
        log.debug("Cypher生成原始响应: {}", response);

        try {
            JsonObject jsonResult = JsonParser.parseString(response).getAsJsonObject();
            String cypher = jsonResult.get("cypher").getAsString();
            String reasoning = jsonResult.has("reasoning") ? jsonResult.get("reasoning").getAsString() : "";

            String formattedCypher = formatCypher(cypher);
            var syntaxValidation = syntaxValidator.validate(formattedCypher);

            double confidence = calculateConfidence(syntaxValidation, blueprint);

            return CypherGenerationResult.builder()
                .cypher(cypher)
                .formattedCypher(formattedCypher)
                .reasoning(reasoning)
                .confidence(confidence)
                .syntaxErrors(syntaxValidation.errors())
                .warnings(syntaxValidation.warnings())
                .build();

        } catch (Exception e) {
            log.error("解析Cypher生成结果失败: {}", e.getMessage());
            throw new IOException("解析Cypher生成结果失败: " + e.getMessage(), e);
        }
    }

    private String buildPrompt(String query, QueryBlueprint blueprint, SchemaMappingResult schemaMapping) {
        StringBuilder prompt = new StringBuilder();
        
        prompt.append("基于以下结构化信息生成Cypher语句：\n\n");
        
        prompt.append("原始查询：\"").append(query).append("\"\n\n");
        
        prompt.append("查询蓝图：\n");
        prompt.append(gson.toJson(blueprint)).append("\n\n");
        
        prompt.append("Schema映射结果：\n");
        prompt.append(gson.toJson(schemaMapping.getMappingResult())).append("\n\n");
        
        prompt.append("请按照要求的JSON格式输出结果。");
        
        return prompt.toString();
    }

    private String formatCypher(String cypher) {
        String formatted = cypher.trim();
        
        formatted = formatted.replaceAll("\\s+", " ");
        
        formatted = formatted.replaceAll("MATCH", "\nMATCH");
        formatted = formatted.replaceAll("WHERE", "\nWHERE");
        formatted = formatted.replaceAll("RETURN", "\nRETURN");
        formatted = formatted.replaceAll("ORDER BY", "\nORDER BY");
        formatted = formatted.replaceAll("LIMIT", "\nLIMIT");
        
        formatted = formatted.replaceAll("(MATCH|WHERE|RETURN|ORDER BY|LIMIT)\\s+", "$1 ");
        
        formatted = formatted.replaceAll("AND\\s+", "AND ");
        formatted = formatted.replaceAll("OR\\s+", "OR ");
        
        formatted = formatted.replaceAll("(MATCH|WHERE|RETURN|ORDER BY|LIMIT)", "\n$1");
        
        return formatted.trim();
    }

    private double calculateConfidence(CypherSyntaxValidator.ValidationResult validation, QueryBlueprint blueprint) {
        double baseConfidence = 0.8;
        
        if (validation.isValid()) {
            baseConfidence += 0.1;
        }
        
        if (validation.errors().isEmpty()) {
            baseConfidence += 0.05;
        }
        
        String complexity = blueprint.getComplexity();
        if ("simple".equals(complexity)) {
            baseConfidence += 0.05;
        } else if ("complex".equals(complexity)) {
            baseConfidence -= 0.1;
        }
        
        return Math.min(Math.max(baseConfidence, 0.0), 1.0);
    }
}

class CypherSyntaxValidator {
    
    public ValidationResult validate(String cypher) {
        java.util.List<String> errors = new java.util.ArrayList<>();
        java.util.List<String> warnings = new java.util.ArrayList<>();
        
        if (cypher == null || cypher.trim().isEmpty()) {
            errors.add("Cypher语句为空");
            return new ValidationResult(false, errors, warnings);
        }
        
        checkParentheses(cypher, errors);
        checkKeywords(cypher, errors);
        checkStringLiterals(cypher, errors, warnings);
        checkClauses(cypher, errors, warnings);
        
        boolean isValid = errors.isEmpty();
        return new ValidationResult(isValid, errors, warnings);
    }
    
    private void checkParentheses(String cypher, java.util.List<String> errors) {
        int count = cypher.chars().filter(ch -> ch == '(').count();
        int countClose = cypher.chars().filter(ch -> ch == ')').count();
        
        if (count != countClose) {
            errors.add("括号不匹配：开括号 " + count + " 个，闭括号 " + countClose + " 个");
        }
    }
    
    private void checkKeywords(String cypher, java.util.List<String> errors) {
        String[] requiredClauses = {"MATCH", "RETURN"};
        
        for (String clause : requiredClauses) {
            if (!cypher.toUpperCase().contains(clause)) {
                errors.add("缺少必需的子句：" + clause);
            }
        }
    }
    
    private void checkStringLiterals(String cypher, java.util.List<String> errors, java.util.List<String> warnings) {
        Pattern pattern = Pattern.compile("'([^']*)'");
        Matcher matcher = pattern.matcher(cypher);
        
        while (matcher.find()) {
            String value = matcher.group(1);
            if (value.isEmpty()) {
                warnings.add("存在空字符串值");
            }
        }
    }
    
    private void checkClauses(String cypher, java.util.List<String> errors, java.util.List<String> warnings) {
        String[] lines = cypher.split("\n");
        boolean hasWhere = false;
        boolean hasReturn = false;
        
        for (String line : lines) {
            if (line.trim().toUpperCase().startsWith("WHERE")) {
                hasWhere = true;
            }
            if (line.trim().toUpperCase().startsWith("RETURN")) {
                hasReturn = true;
            }
        }
        
        if (!hasReturn) {
            errors.add("缺少RETURN子句");
        }
        
        if (hasWhere) {
            Pattern wherePattern = Pattern.compile("WHERE\\s+(.+?)(?=\\n[A-Z]|$)", Pattern.CASE_INSENSITIVE);
            Matcher matcher = wherePattern.matcher(cypher);
            if (matcher.find()) {
                String whereContent = matcher.group(1).trim();
                if (whereContent.isEmpty()) {
                    errors.add("WHERE子句内容为空");
                }
            }
        }
    }
    
    public record ValidationResult(boolean isValid, java.util.List<String> errors, java.util.List<String> warnings) {}
}
