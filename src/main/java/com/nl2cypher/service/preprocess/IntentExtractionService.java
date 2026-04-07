package com.nl2cypher.service.preprocess;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.nl2cypher.model.representation.QueryBlueprint;
import com.nl2cypher.model.representation.SemanticAnalysisResult;
import com.nl2cypher.service.llm.GLMClient;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import java.io.IOException;

@Slf4j
@Service
public class IntentExtractionService {
    private final GLMClient glmClient;
    private final Gson gson;

    private static final String SYSTEM_PROMPT = """
        你是一个专业的查询意图理解专家，专门将语义分析结果转换为结构化的查询蓝图。
        你的任务是基于用户的查询和语义分析，构建详细的查询蓝图。
        
        请按照以下JSON格式输出查询蓝图：
        {
          "query_type": "查询类型（如：simple_node_query, multi_filter_node_query, path_query, aggregation_query等）",
          "complexity": "复杂度（simple/medium/complex）",
          "components": {
            "match_pattern": {
              "main_node": {
                "variable": "变量名（如：p）",
                "label": "节点标签（如：Person）",
                "alias": "别名（可选）",
                "conditions": [
                  {
                    "field": "字段名",
                    "operator": "操作符",
                    "value": "值"
                  }
                ]
              },
              "related_nodes": [
                {
                  "variable": "变量名",
                  "label": "节点标签",
                  "relation": {
                    "type": "关系类型（如：WORKS_AT）",
                    "direction": "方向（incoming/outgoing/both）",
                    "pattern": "关系模式（如：(p)-[:WORKS_AT]->(c)）"
                  },
                  "conditions": [
                    {
                      "field": "字段名",
                      "operator": "操作符",
                      "value": "值"
                    }
                  ]
                }
              ]
            },
            "where_conditions": [
              {
                "node_variable": "节点变量",
                "conditions": [
                  {
                    "field": "字段名",
                    "operator": "操作符",
                    "value": "值"
                  }
                ],
                "logical_operator": "AND/OR"
              }
            ],
            "return_statement": {
              "variables": ["返回的变量列表"],
              "description": "返回描述",
              "aggregations": [],
              "order_by": [],
              "limit": null
            }
          }
        }
        
        请只输出JSON格式的结果，不要添加任何解释。
        """;

    public IntentExtractionService(GLMClient glmClient) {
        this.glmClient = glmClient;
        this.gson = new Gson();
    }

    public QueryBlueprint extractBlueprint(String query, SemanticAnalysisResult semanticAnalysis) throws IOException {
        log.info("开始提取查询蓝图: {}", query);

        String userPrompt = String.format(
            "基于以下语义分析结果，构建查询蓝图：\n\n" +
            "查询：\"%s\"\n\n" +
            "语义分析：\n%s\n\n" +
            "请按照要求的JSON格式输出查询蓝图。",
            query,
            gson.toJson(semanticAnalysis.getSemanticAnalysis())
        );

        String response = glmClient.chat(SYSTEM_PROMPT, userPrompt);
        log.debug("查询蓝图原始响应: {}", response);

        try {
            JsonObject jsonResult = JsonParser.parseString(response).getAsJsonObject();
            QueryBlueprint blueprint = gson.fromJson(jsonResult, QueryBlueprint.class);

            log.info("成功提取查询蓝图: {}, 复杂度: {}", blueprint.getQueryType(), blueprint.getComplexity());
            return blueprint;

        } catch (Exception e) {
            log.error("解析查询蓝图失败: {}", e.getMessage());
            throw new IOException("解析查询蓝图失败: " + e.getMessage(), e);
        }
    }
}
