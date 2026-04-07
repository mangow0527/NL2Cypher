package com.nl2cypher.service.preprocess;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.nl2cypher.model.representation.QueryBlueprint;
import com.nl2cypher.model.representation.SchemaMappingResult;
import com.nl2cypher.service.llm.GLMClient;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import java.io.IOException;
import java.util.*;

@Slf4j
@Service
public class SchemaMappingService {
    private final GLMClient glmClient;
    private final Gson gson;

    private static final String SYSTEM_PROMPT = """
        你是一个专业的数据库Schema映射专家，专门负责将查询蓝图与具体的数据库Schema进行精确映射。
        你的任务是基于查询蓝图和数据库Schema，验证映射的正确性并提供优化建议。
        
        请按照以下JSON格式输出映射结果：
        {
          "database_schema": {
            "nodes": {
              "Person": {
                "label": "Person",
                "properties": {
                  "name": "String",
                  "age": "Integer",
                  "work_years": "Integer",
                  "gender": "String"
                },
                "indexes": ["name", "age"]
              },
              "Company": {
                "label": "Company",
                "properties": {
                  "name": "String",
                  "industry": "String",
                  "founded": "Integer"
                },
                "indexes": ["name"]
              }
            },
            "relationships": {
              "WORKS_AT": {
                "type": "WORKS_AT",
                "from_node": "Person",
                "to_node": "Company",
                "properties": {}
              }
            }
          },
          "mapping_result": {
            "validated": true,
            "type_checking": {
              "field_validations": {
                "p.age": "Integer - valid",
                "c.name": "String - valid"
              }
            },
            "relation_validation": {
              "(p)-[:WORKS_AT]->(c)": "valid"
            },
            "index_suggestions": [
              "CREATE INDEX ON :Company(name)",
              "CREATE INDEX ON :Person(work_years)"
            ],
            "validation_errors": []
          }
        }
        
        请只输出JSON格式的结果，不要添加任何解释。
        """;

    private final SchemaMappingResult.DatabaseSchema defaultSchema;

    public SchemaMappingService(GLMClient glmClient) {
        this.glmClient = glmClient;
        this.gson = new Gson();
        this.defaultSchema = createDefaultSchema();
    }

    private SchemaMappingResult.DatabaseSchema createDefaultSchema() {
        Map<String, SchemaMappingResult.NodeSchema> nodes = new HashMap<>();
        
        Map<String, String> personProps = new HashMap<>();
        personProps.put("name", "String");
        personProps.put("age", "Integer");
        personProps.put("work_years", "Integer");
        personProps.put("gender", "String");
        nodes.put("Person", SchemaMappingResult.NodeSchema.builder()
            .label("Person")
            .properties(personProps)
            .indexes(Arrays.asList("name", "age"))
            .build());

        Map<String, String> companyProps = new HashMap<>();
        companyProps.put("name", "String");
        companyProps.put("industry", "String");
        companyProps.put("founded", "Integer");
        nodes.put("Company", SchemaMappingResult.NodeSchema.builder()
            .label("Company")
            .properties(companyProps)
            .indexes(Arrays.asList("name"))
            .build());

        Map<String, SchemaMappingResult.RelationSchema> relationships = new HashMap<>();
        relationships.put("WORKS_AT", SchemaMappingResult.RelationSchema.builder()
            .type("WORKS_AT")
            .fromNode("Person")
            .toNode("Company")
            .properties(new HashMap<>())
            .build());

        return SchemaMappingResult.DatabaseSchema.builder()
            .nodes(nodes)
            .relationships(relationships)
            .build();
    }

    public SchemaMappingResult mapSchema(String query, QueryBlueprint blueprint) throws IOException {
        log.info("开始Schema映射: {}", query);

        String userPrompt = String.format(
            "基于以下查询蓝图，进行Schema映射和验证：\n\n" +
            "查询：\"%s\"\n\n" +
            "查询蓝图：\n%s\n\n" +
            "请验证查询蓝图与数据库Schema的兼容性，并提供映射结果和优化建议。",
            query,
            gson.toJson(blueprint)
        );

        String response = glmClient.chat(SYSTEM_PROMPT, userPrompt);
        log.debug("Schema映射原始响应: {}", response);

        try {
            JsonObject jsonResult = JsonParser.parseString(response).getAsJsonObject();
            SchemaMappingResult mappingResult = gson.fromJson(jsonResult, SchemaMappingResult.class);

            log.info("Schema映射完成，验证结果: {}", mappingResult.getMappingResult().isValidated());
            return mappingResult;

        } catch (Exception e) {
            log.error("解析Schema映射结果失败: {}", e.getMessage());
            throw new IOException("解析Schema映射结果失败: " + e.getMessage(), e);
        }
    }

    public SchemaMappingResult.DatabaseSchema getDatabaseSchema() {
        return defaultSchema;
    }
}
