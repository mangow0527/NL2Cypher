# NL2Cypher 自然语言转Cypher系统

基于强辅助弱模型架构的自然语言到Cypher查询转换系统。

## 系统架构

本系统采用**强辅助弱模型**架构：
- **强模型（GLM-4）**：负责深度语义理解、意图识别、智能验证
- **弱模型（千问3.0 32B）**：负责Cypher语法生成

## 快速开始

### 前置要求

1. **Java 17+**
2. **Maven 3.6+**
3. **千问3.0 32B本地部署**
4. **智谱AI API Key**

### 千问3.0 32B本地部署

#### 方案1: 使用vLLM（推荐）

```bash
pip install vllm

python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-32B-Instruct \
    --host 0.0.0.0 \
    --port 8000 \
    --tensor-parallel-size 1 \
    --max-model-len 4096
```

#### 方案2: 使用Ollama

```bash
ollama pull qwen2.5:32b
ollama serve
```

### 智谱AI API Key获取

1. 访问 https://open.bigmodel.cn/
2. 注册账号并完成实名认证
3. 进入"API Key管理"创建新的API Key

### 配置应用

编辑 `src/main/resources/application.yml`：

```yaml
nl2cypher:
  strong-model:
    api-key: "your-zhipu-api-key"  # 替换为你的智谱API Key
    model: glm-4-plus
    
  weak-model:
    api-url: "http://localhost:8000/v1/chat/completions"  # 千问本地API地址
```

### 构建和运行

```bash
# 构建
mvn clean package

# 运行演示
mvn exec:java -Dexec.mainClass="com.nl2cypher.NL2CypherDemo"

# 或启动Web服务
mvn spring-boot:run
```

### API使用

启动服务后，可以通过以下方式调用：

```bash
curl -X POST http://localhost:8080/api/nl2cypher/convert \
  -H "Content-Type: application/json" \
  -d '{"query": "查找在阿里巴巴工作的所有员工"}'
```

## 系统流程

```
用户查询 
  ↓
[阶段1] 深度语义理解（GLM-4）
  ↓
[阶段2] 意图与结构提取（GLM-4）
  ↓
[阶段3] Schema智能映射（GLM-4）
  ↓
[阶段4] Cypher生成（千问3.0 32B）
  ↓
[阶段5] 智能验证与纠错（GLM-4）
  ↓
最终结果
```

## 支持的查询类型

- 简单节点查询
- 关系查询
- 路径查询
- 聚合查询
- 复杂过滤查询
- 多跳关系查询

## 示例

```java
String query = "查找在阿里巴巴工作超过5年且年龄大于30岁的员工";

NL2CypherResult result = orchestrator.convert(query);

if (result.isSuccess()) {
    System.out.println("生成的Cypher:");
    System.out.println(result.getGeneratedCypher());
    
    System.out.println("置信度: " + result.getConfidence());
    System.out.println("验证分数: " + 
        result.getValidationResult().getOverallScore().getTotalScore());
}
```

## 技术栈

- **框架**: Spring Boot 3.1.5
- **构建工具**: Maven
- **HTTP客户端**: OkHttp
- **JSON处理**: Gson
- **日志**: SLF4J + Logback

## 项目结构

```
nl2cypher-system/
├── src/
│   ├── main/
│   │   ├── java/com/nl2cypher/
│   │   │   ├── config/              # 配置类
│   │   │   ├── controller/          # REST控制器
│   │   │   ├── model/              # 数据模型
│   │   │   │   └── representation/ # 中间表示
│   │   │   ├── service/
│   │   │   │   ├── llm/           # LLM客户端
│   │   │   │   ├── preprocess/    # 预处理服务
│   │   │   │   ├── generation/    # 生成服务
│   │   │   │   ├── postprocess/   # 后处理服务
│   │   │   │   └── orchestration/ # 流程编排
│   │   │   └── NL2CypherApplication.java
│   │   └── resources/
│   │       └── application.yml
│   └── test/
│       └── java/com/nl2cypher/
│           └── NL2CypherDemo.java
├── pom.xml
└── README.md
```

## 配置说明

### 强模型配置

```yaml
nl2cypher:
  strong-model:
    provider: zhipu
    api-key: ${ZHIPU_API_KEY}
    model: glm-4-plus
    temperature: 0.3
    max-tokens: 2048
    timeout: 30000
```

### 弱模型配置

```yaml
nl2cypher:
  weak-model:
    provider: local-qwen
    api-url: ${QWEN_API_URL}
    model: Qwen/Qwen2.5-32B-Instruct
    temperature: 0.7
    max-tokens: 1024
    timeout: 60000
```

### 验证配置

```yaml
nl2cypher:
  validation:
    max-retries: 3
    confidence-threshold: 0.7
```

## 故障排除

### 千问模型连接失败
- 确认千问服务已启动
- 检查API URL配置是否正确
- 确认网络连接正常

### 智谱API调用失败
- 检查API Key是否正确
- 确认API Key有足够的额度
- 检查网络连接

## 性能优化建议

1. **启用缓存**: 对相似查询结果进行缓存
2. **并发处理**: 对独立处理阶段进行并发优化
3. **模型选择**: 根据查询复杂度动态选择模型
4. **批量处理**: 支持批量查询处理

## 贡献指南

欢迎提交Issue和Pull Request！

## 许可证

MIT License

## 联系方式

如有问题或建议，请提交Issue。
