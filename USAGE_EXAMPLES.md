# NL2Cypher 使用示例

## 环境准备

### 1. 启动千问3.0 32B本地服务

```bash
# 使用vLLM启动
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-32B-Instruct \
    --host 0.0.0.0 \
    --port 8000 \
    --tensor-parallel-size 1 \
    --max-model-len 4096
```

### 2. 配置API Key

编辑 `src/main/resources/application.yml`：

```yaml
nl2cypher:
  strong-model:
    api-key: "sk-xxxxxxxxxxxxxxxxxxxxxxxx"  # 你的智谱API Key
```

### 3. 编译项目

```bash
mvn clean compile
```

## 示例1：简单节点查询

**查询**: "查找在阿里巴巴工作的所有员工"

**预期输出**:
```cypher
MATCH (p:Person)-[:WORKS_AT]->(c:Company {name: '阿里巴巴'})
RETURN p
```

## 示例2：条件过滤查询

**查询**: "查找年龄大于30岁的员工"

**预期输出**:
```cypher
MATCH (p:Person)
WHERE p.age > 30
RETURN p
```

## 示例3：关系查询

**查询**: "查找张三认识的所有人"

**预期输出**:
```cypher
MATCH (p1:Person {name: '张三'})-[:KNOWS]->(p2:Person)
RETURN p2
```

## 示例4：复杂过滤查询

**查询**: "查找在阿里巴巴工作超过5年且年龄大于30岁的员工"

**预期输出**:
```cypher
MATCH (p:Person)-[:WORKS_AT]->(c:Company {name: '阿里巴巴'})
WHERE p.work_years > 5 AND p.age > 30
RETURN p
```

## 示例5：聚合查询

**查询**: "统计每个公司有多少员工"

**预期输出**:
```cypher
MATCH (p:Person)-[:WORKS_AT]->(c:Company)
RETURN c.name AS company_name, count(p) AS employee_count
```

## API调用示例

### 使用curl

```bash
curl -X POST http://localhost:8080/api/nl2cypher/convert \
  -H "Content-Type: application/json" \
  -d '{
    "query": "查找在阿里巴巴工作的所有员工"
  }'
```

### 使用Java

```java
import org.springframework.web.client.RestTemplate;
import org.springframework.http.*;

public class NL2CypherClient {
    private final RestTemplate restTemplate = new RestTemplate();
    
    public String convertQuery(String query) {
        String url = "http://localhost:8080/api/nl2cypher/convert";
        
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        
        Map<String, String> requestBody = new HashMap<>();
        requestBody.put("query", query);
        
        HttpEntity<Map<String, String>> entity = new HttpEntity<>(requestBody, headers);
        ResponseEntity<String> response = restTemplate.exchange(
            url, HttpMethod.POST, entity, String.class);
        
        return response.getBody();
    }
}
```

### 使用Python

```python
import requests
import json

def convert_query(query):
    url = "http://localhost:8080/api/nl2cypher/convert"
    headers = {"Content-Type": "application/json"}
    data = {"query": query}
    
    response = requests.post(url, headers=headers, data=json.dumps(data))
    return response.json()

result = convert_query("查找在阿里巴巴工作的所有员工")
print(json.dumps(result, indent=2, ensure_ascii=False))
```

## 运行演示程序

```bash
# 运行内置演示
mvn exec:java -Dexec.mainClass="com.nl2cypher.NL2CypherDemo"
```

## 启动Web服务

```bash
# 启动Spring Boot应用
mvn spring-boot:run
```

服务将在 `http://localhost:8080` 启动。

## 健康检查

```bash
curl http://localhost:8080/api/nl2cypher/health
```

## 支持的查询模式

1. **简单节点查询**: "查找所有员工"
2. **条件查询**: "查找年龄大于30岁的员工"
3. **关系查询**: "查找张三认识的人"
4. **路径查询**: "查找从张三到李四的路径"
5. **聚合查询**: "统计每个公司的员工数量"
6. **排序查询**: "查找最年轻的员工"
7. **复杂过滤**: "查找在阿里巴巴工作超过5年且年龄大于30岁的员工"

## 响应格式

### 成功响应

```json
{
  "success": true,
  "originalQuery": "查找在阿里巴巴工作的所有员工",
  "generatedCypher": "MATCH (p:Person)-[:WORKS_AT]->(c:Company {name: '阿里巴巴'}) RETURN p",
  "reasoning": "基于查询意图，识别出员工(Person)通过WORKS_AT关系连接到公司(Company)，并过滤公司名称为'阿里巴巴'的记录",
  "confidence": 0.85,
  "validationScore": 0.78,
  "processingTimeMs": 1523,
  "validationResult": {
    "cypherValidation": {
      "syntaxCheck": {
        "status": "passed",
        "errors": [],
        "suggestions": []
      },
      "semanticCheck": {
        "schemaCompatibility": "valid",
        "typeSafety": "valid",
        "relationDirection": "correct",
        "issues": []
      },
      "intentMatch": {
        "originalIntent": "查找特定公司的员工",
        "cypherIntent": "查询满足公司条件的Person节点",
        "matchScore": 0.95,
        "assessment": "高度匹配"
      },
      "performanceAnalysis": {
        "estimatedComplexity": "simple",
        "suggestedIndexes": ["CREATE INDEX ON :Company(name)"],
        "optimizationTips": ["如果数据量大，考虑添加LIMIT子句"]
      }
    },
    "queryExplanation": {
      "naturalLanguageExplanation": "这个查询会返回所有在阿里巴巴工作的员工信息。",
      "executionSteps": [
        "1. 找到所有Person节点",
        "2. 筛选出通过WORKS_AT关系连接到名为'阿里巴巴'的Company节点的Person",
        "3. 返回符合条件的Person节点"
      ],
      "equivalentQueries": [],
      "optimizationSuggestions": {
        "immediate": ["添加索引以提升查询性能"],
        "longTerm": ["考虑数据分区策略"]
      }
    },
    "overallScore": {
      "totalScore": 0.78,
      "syntaxScore": 0.8,
      "semanticScore": 0.75,
      "intentScore": 0.95,
      "performanceScore": 0.6,
      "passedThreshold": true,
      "threshold": 0.7
    }
  }
}
```

### 错误响应

```json
{
  "success": false,
  "originalQuery": "查找在阿里巴巴工作的所有员工",
  "errorMessage": "API调用失败: 超时",
  "processingTimeMs": 32100
}
```

## 故障排除

### 问题：千问服务连接失败

**解决方案**:
1. 确认千问服务已启动: `curl http://localhost:8000/v1/models`
2. 检查配置文件中的API URL是否正确
3. 确认防火墙设置

### 问题：智谱API调用失败

**解决方案**:
1. 检查API Key是否正确
2. 确认API Key有足够的额度
3. 检查网络连接和代理设置

### 问题：生成的Cypher语法错误

**解决方案**:
1. 查看系统日志中的错误信息
2. 调整模型参数（temperature等）
3. 检查Schema配置是否正确

## 性能调优

### 1. 降低temperature值

```yaml
nl2cypher:
  weak-model:
    temperature: 0.5  # 从0.7降低到0.5
```

### 2. 增加重试次数

```yaml
nl2cypher:
  validation:
    max-retries: 5  # 从3增加到5
```

### 3. 调整token限制

```yaml
nl2cypher:
  strong-model:
    max-tokens: 4096  # 从2048增加到4096
```

## 扩展开发

### 添加新的查询类型

1. 在`SemanticUnderstandingService`中添加意图识别
2. 在`IntentExtractionService`中添加蓝图构建逻辑
3. 更新示例数据

### 自定义Schema

修改`SchemaMappingService`中的`createDefaultSchema()`方法，添加你的节点和关系定义。
