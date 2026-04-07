package com.nl2cypher.service.preprocess;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.nl2cypher.model.representation.SemanticAnalysisResult;
import com.nl2cypher.service.llm.GLMClient;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import java.io.IOException;

@Slf4j
@Service
public class SemanticUnderstandingService {
    private final GLMClient glmClient;
    private final Gson gson;

    private static final String SYSTEM_PROMPT = """
        你是一个专业的自然语言理解专家，专门分析用户查询的语义信息。
        你的任务是对用户的查询进行深度的语义分析，提取关键信息。
        
        请按照以下JSON格式输出分析结果：
        {
          "main_intent": "查询类型（如：simple_node_query, simple_relation_query, path_query, aggregation_query, complex_filtering_query等）",
          "sub_intents": ["子意图列表"],
          "entities": {
            "explicit": ["明确提到的实体"],
            "implicit": ["隐含的实体"],
            "type_mapping": {"实体名称": "对应的数据库元素类型"}
          },
          "relations": ["识别的关系类型"],
          "conditions": [
            {
              "type": "条件类型",
              "field": "字段名",
              "operator": "操作符",
              "value": "值"
            }
          ],
          "ambiguity_resolution": {
            "歧义词汇": "消解结果"
          }
        }
        
        请只输出JSON格式的结果，不要添加任何解释。
        """;

    public SemanticUnderstandingService(GLMClient glmClient) {
        this.glmClient = glmClient;
        this.gson = new Gson();
    }

    public SemanticAnalysisResult analyze(String query) throws IOException {
        log.info("开始语义分析: {}", query);

        String userPrompt = String.format(
            "请分析以下查询的语义信息：\n\n查询：\"%s\"\n\n请按照要求的JSON格式输出分析结果。",
            query
        );

        String response = glmClient.chat(SYSTEM_PROMPT, userPrompt);
        log.debug("语义分析原始响应: {}", response);

        try {
            JsonObject jsonResult = JsonParser.parseString(response).getAsJsonObject();
            SemanticAnalysisResult.SemanticAnalysis analysis = gson.fromJson(
                jsonResult, 
                SemanticAnalysisResult.SemanticAnalysis.class
            );

            return SemanticAnalysisResult.builder()
                .originalQuery(query)
                .semanticAnalysis(analysis)
                .build();

        } catch (Exception e) {
            log.error("解析语义分析结果失败: {}", e.getMessage());
            throw new IOException("解析语义分析结果失败: " + e.getMessage(), e);
        }
    }
}
