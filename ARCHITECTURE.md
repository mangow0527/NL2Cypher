# NL2Cypher 系统架构设计

## 目录

- [概述](#概述)
- [整体架构](#整体架构)
- [核心模块设计](#核心模块设计)
- [处理流程](#处理流程)
- [架构优势](#架构优势)
- [实施路径](#实施路径)
- [核心设计原则](#核心设计原则)

---

## 概述

本文档描述了一个**分层协作式智能NL2Cypher系统架构**，该架构融合了多Agent协作的思想优点，同时避免了过度工程化的问题。

### 设计理念

- **分层清晰**：每层职责单一，易于理解和维护
- **灵活可扩展**：根据复杂度选择不同策略
- **成本可控**：平衡准确率和成本
- **质量保障**：多维度验证机制
- **持续学习**：反馈闭环优化

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户接口层                                │
│  REST API / GraphQL / SDK / Web UI                             │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    编排调度层 (Orchestrator)                     │
│  - 查询复杂度评估      - 路由决策                                │
│  - 流程编排            - 超时控制                                │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    核心处理层 (Processing)                       │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ 语义理解模块  │→│ 结构设计模块  │→│ 代码生成模块  │         │
│  │  (Analyzer)  │  │ (Architect)  │  │ (Generator)  │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│         ↓                  ↓                  ↓                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ Schema映射   │  │ 蓝图设计     │  │ Cypher生成   │         │
│  │ 实体识别     │  │ 路径规划     │  │ 优化建议     │         │
│  │ 意图分类     │  │ 约束定义     │  │ 多版本生成   │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    质量保障层 (Quality Assurance)                │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ 语法验证     │  │ 语义验证     │  │ 执行验证     │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│         ↓                  ↓                  ↓                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ 性能分析     │  │ 安全检查     │  │ 自动修复     │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    知识服务层 (Knowledge Service)                │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ Schema知识库 │  │ 示例库       │  │ 同义词词典   │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│         ↓                  ↓                  ↓                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ 业务规则库   │  │ 错误模式库   │  │ 最佳实践库   │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    模型服务层 (Model Service)                    │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ 强模型服务   │  │ 弱模型服务   │  │ 本地小模型   │         │
│  │ (GLM-4)     │  │ (千问32B)    │  │ (千问7B)     │         │
│  │             │  │             │  │             │         │
│  │ 深度理解     │  │ 代码生成     │  │ 快速分类     │         │
│  │ 智能验证     │  │ 模板填充     │  │ 意图识别     │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    反馈学习层 (Feedback Learning)                │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ 用户反馈收集 │  │ 质量分析     │  │ 知识更新     │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 核心模块设计

### 1. 编排调度层 (QueryOrchestrator)

**职责**：
- 查询复杂度评估
- 处理策略选择
- 流程编排与调度
- 超时控制与异常处理

**核心代码**：
```java
@Service
public class QueryOrchestrator {
    
    private final QueryAnalyzer analyzer;
    private final QueryArchitect architect;
    private final CypherGenerator generator;
    private final QualityValidator validator;
    private final KnowledgeService knowledgeService;
    
    public NL2CypherResult process(String query) {
        long startTime = System.currentTimeMillis();
        
        try {
            // Step 1: 复杂度评估与路由
            QueryComplexity complexity = analyzer.assessComplexity(query);
            ProcessingStrategy strategy = selectStrategy(complexity);
            
            // Step 2: 语义理解（强模型）
            SemanticContext context = analyzer.analyze(query);
            
            // Step 3: 查询结构设计（强模型）
            QueryBlueprint blueprint = architect.design(query, context);
            
            // Step 4: 知识增强
            KnowledgeContext knowledge = knowledgeService.enrich(blueprint);
            
            // Step 5: Cypher生成（根据复杂度选择模型）
            List<CypherCandidate> candidates = generator.generate(
                query, blueprint, knowledge, strategy
            );
            
            // Step 6: 质量验证与选择
            ValidatedResult result = validator.validateAndSelect(
                query, candidates, blueprint
            );
            
            // Step 7: 后处理与优化
            return postProcess(result, startTime);
            
        } catch (Exception e) {
            return handleError(query, e, startTime);
        }
    }
    
    private ProcessingStrategy selectStrategy(QueryComplexity complexity) {
        return switch (complexity) {
            case SIMPLE -> ProcessingStrategy.TEMPLATE_BASED;
            case MODERATE -> ProcessingStrategy.HYBRID;
            case COMPLEX -> ProcessingStrategy.LLM_WITH_VALIDATION;
            case VERY_COMPLEX -> ProcessingStrategy.MULTI_ROUND_REFINEMENT;
        };
    }
}
```

### 2. 语义理解模块 (QueryAnalyzer)

**职责**：
- 意图识别与分类
- 实体抽取与标准化
- 查询复杂度评估
- 歧义检测

**核心代码**：
```java
@Service
public class QueryAnalyzer {
    
    private final StrongModelClient strongModel;
    private final LocalModelClient localModel;
    private final KnowledgeService knowledgeService;
    
    public SemanticContext analyze(String query) {
        // 并行执行多个分析任务
        CompletableFuture<IntentAnalysis> intentFuture = 
            CompletableFuture.supplyAsync(() -> analyzeIntent(query));
        
        CompletableFuture<List<Entity>> entitiesFuture = 
            CompletableFuture.supplyAsync(() -> extractEntities(query));
        
        CompletableFuture<QueryComplexity> complexityFuture = 
            CompletableFuture.supplyAsync(() -> assessComplexity(query));
        
        // 等待所有分析完成
        CompletableFuture.allOf(intentFuture, entitiesFuture, complexityFuture);
        
        return SemanticContext.builder()
            .originalQuery(query)
            .intent(intentFuture.join())
            .entities(entitiesFuture.join())
            .complexity(complexityFuture.join())
            .temporalInfo(extractTemporal(query))
            .ambiguities(detectAmbiguities(query))
            .build();
    }
    
    private List<Entity> extractEntities(String query) {
        // 使用本地小模型快速识别
        List<String> rawEntities = localModel.extractEntities(query);
        
        // 通过知识库标准化
        return rawEntities.stream()
            .map(entity -> knowledgeService.normalizeEntity(entity))
            .filter(Optional::isPresent)
            .map(Optional::get)
            .collect(toList());
    }
}
```

### 3. 结构设计模块 (QueryArchitect)

**职责**：
- 查询蓝图设计
- 路径规划
- 性能约束定义
- 蓝图优化

**核心代码**：
```java
@Service
public class QueryArchitect {
    
    private final StrongModelClient strongModel;
    private final KnowledgeService knowledgeService;
    
    public QueryBlueprint design(String query, SemanticContext context) {
        // 根据意图选择蓝图模板
        BlueprintTemplate template = selectTemplate(context.getIntent());
        
        // 填充实体信息
        QueryBlueprint blueprint = template.instantiate(context.getEntities());
        
        // 使用强模型优化蓝图
        blueprint = optimizeBlueprint(query, blueprint, context);
        
        // 添加性能约束
        addPerformanceConstraints(blueprint);
        
        return blueprint;
    }
    
    private QueryBlueprint optimizeBlueprint(
        String query, 
        QueryBlueprint blueprint, 
        SemanticContext context
    ) {
        String prompt = """
            你是一个图数据库查询架构师。请优化以下查询蓝图：
            
            ## 原始查询
            %s
            
            ## 当前蓝图
            %s
            
            ## Schema信息
            %s
            
            ## 优化目标
            1. 确保查询路径最短
            2. 优先使用索引字段
            3. 避免笛卡尔积
            4. 考虑分页和限制
            
            请输出优化后的蓝图（JSON格式）。
            """.formatted(
                query, 
                blueprint.toJson(), 
                knowledgeService.getSchemaInfo()
            );
        
        String optimizedJson = strongModel.generate(prompt);
        return QueryBlueprint.fromJson(optimizedJson);
    }
}
```

### 4. 代码生成模块 (CypherGenerator)

**职责**：
- 基于模板生成（简单查询）
- 基于LLM生成（复杂查询）
- 多版本生成
- 提示词工程

**核心代码**：
```java
@Service
public class CypherGenerator {
    
    private final WeakModelClient weakModel;
    private final TemplateEngine templateEngine;
    private final KnowledgeService knowledgeService;
    
    public List<CypherCandidate> generate(
        String query,
        QueryBlueprint blueprint,
        KnowledgeContext knowledge,
        ProcessingStrategy strategy
    ) {
        List<CypherCandidate> candidates = new ArrayList<>();
        
        // 策略1: 模板生成（简单查询）
        if (strategy.useTemplate()) {
            candidates.add(generateFromTemplate(blueprint));
        }
        
        // 策略2: LLM生成（复杂查询）
        if (strategy.useLLM()) {
            // 生成多个版本
            for (int i = 0; i < strategy.getCandidateCount(); i++) {
                candidates.add(generateFromLLM(
                    query, blueprint, knowledge, 
                    0.3 + i * 0.15  // 不同温度
                ));
            }
        }
        
        return candidates;
    }
    
    private String buildPrompt(
        String query, 
        QueryBlueprint blueprint, 
        KnowledgeContext knowledge
    ) {
        // 获取相似示例
        List<CypherExample> examples = knowledgeService.findSimilarExamples(
            query, 
            topK = 3
        );
        
        return """
            你是一个Cypher查询专家。请根据以下信息生成Cypher查询。
            
            ## 自然语言查询
            %s
            
            ## 查询蓝图
            %s
            
            ## Schema信息
            %s
            
            ## 相似示例（供参考）
            %s
            
            ## 注意事项
            1. 严格按照蓝图结构生成
            2. 使用参数化查询（$param）而非硬编码
            3. 添加适当的索引提示
            4. 对于大数据集使用LIMIT
            5. 使用WITH优化复杂查询
            
            ## 输出要求
            只输出Cypher代码，不要有任何解释或注释。
            """.formatted(
                query,
                blueprint.toReadableString(),
                knowledge.getSchemaInfo(),
                formatExamples(examples)
            );
    }
}
```

### 5. 质量保障模块 (QualityValidator)

**职责**：
- 语法验证
- 语义验证
- 执行验证
- 性能分析

**核心代码**：
```java
@Service
public class QualityValidator {
    
    private final StrongModelClient strongModel;
    private final Neo4jClient testDatabase;
    private final KnowledgeService knowledgeService;
    
    @Value("${nl2cypher.validation.enable-execution-test:true}")
    private boolean enableExecutionTest;
    
    public ValidatedResult validateAndSelect(
        String query,
        List<CypherCandidate> candidates,
        QueryBlueprint blueprint
    ) {
        List<ValidationResult> results = new ArrayList<>();
        
        for (CypherCandidate candidate : candidates) {
            ValidationResult result = validateCandidate(query, candidate, blueprint);
            results.add(result);
            
            // 如果找到高质量候选，提前返回
            if (result.getScore() >= 0.9) {
                return ValidatedResult.success(candidate, result);
            }
        }
        
        // 选择最佳候选
        ValidationResult bestResult = results.stream()
            .max(Comparator.comparing(ValidationResult::getScore))
            .orElseThrow();
        
        int bestIndex = results.indexOf(bestResult);
        return ValidatedResult.success(candidates.get(bestIndex), bestResult);
    }
    
    private ValidationResult validateCandidate(
        String query,
        CypherCandidate candidate,
        QueryBlueprint blueprint
    ) {
        double totalScore = 0.0;
        List<String> issues = new ArrayList<>();
        
        // 1. 语法验证（权重20%）
        SyntaxCheckResult syntaxCheck = validateSyntax(candidate.getCypher());
        totalScore += syntaxCheck.isPassed() ? 20 : 0;
        
        // 2. 语义验证（权重30%）
        SemanticCheckResult semanticCheck = validateSemantics(
            candidate.getCypher(), 
            blueprint
        );
        totalScore += semanticCheck.getScore() * 30;
        
        // 3. 执行验证（权重30%）
        if (enableExecutionTest) {
            ExecutionCheckResult execCheck = validateExecution(candidate.getCypher());
            totalScore += execCheck.getScore() * 30;
        }
        
        // 4. 性能分析（权重20%）
        PerformanceCheckResult perfCheck = analyzePerformance(candidate.getCypher());
        totalScore += perfCheck.getScore() * 20;
        
        return ValidationResult.builder()
            .cypher(candidate.getCypher())
            .score(totalScore / 100.0)
            .issues(issues)
            .build();
    }
}
```

### 6. 知识服务层 (KnowledgeService)

**职责**：
- Schema知识库管理
- 示例库维护
- 同义词词典
- 知识缓存

**核心代码**：
```java
@Service
public class KnowledgeService {
    
    private final SchemaCache schemaCache;
    private final ExampleLibrary exampleLibrary;
    private final SynonymDictionary synonymDictionary;
    private final RedisClient redisCache;
    
    @Scheduled(cron = "0 0 2 * * ?") // 每天凌晨2点更新
    public void updateKnowledge() {
        updateSchema();
        updateExamples();
        updateSynonyms();
    }
    
    public Optional<Entity> normalizeEntity(String rawEntity) {
        // 1. 查缓存
        String cacheKey = "entity:" + rawEntity;
        Entity cached = redisCache.get(cacheKey, Entity.class);
        if (cached != null) {
            return Optional.of(cached);
        }
        
        // 2. 查同义词词典
        String normalized = synonymDictionary.normalize(rawEntity);
        if (normalized != null) {
            Entity entity = schemaCache.getEntity(normalized);
            redisCache.set(cacheKey, entity, Duration.ofHours(24));
            return Optional.of(entity);
        }
        
        return Optional.empty();
    }
    
    public List<CypherExample> findSimilarExamples(String query, int topK) {
        // 混合检索：向量 + 关键词
        List<CypherExample> vectorResults = exampleLibrary.vectorSearch(query, topK);
        List<CypherExample> keywordResults = exampleLibrary.keywordSearch(query, topK);
        
        return mergeAndDeduplicate(vectorResults, keywordResults, topK);
    }
}
```

---

## 处理流程

### 完整处理流程示例

```java
String query = "查找在阿里巴巴工作超过5年且年薪大于50万的员工，按薪资降序排列，返回前10名";

NL2CypherResult result = orchestrator.process(query);
```

**执行流程**：

#### 1. 编排层 - 复杂度评估
```
复杂度：COMPLEX（多条件+排序+分页）
策略：LLM_WITH_VALIDATION
```

#### 2. 语义理解
```
意图：查询员工信息
实体：[阿里巴巴, 员工]
条件：[work_years > 5, salary > 50万]
排序：salary DESC
限制：10条
```

#### 3. 知识增强
```
"阿里巴巴" → 标准化为 "阿里巴巴集团"
检索相似示例：3个
```

#### 4. 蓝图设计
```
Blueprint:
  Pattern: MATCH
  Nodes: [(p:Person), (c:Company)]
  Relationship: (p)-[:WORKS_AT]->(c)
  Filters: 
    - c.name = '阿里巴巴集团'
    - p.work_years > 5
    - p.salary > 500000
  Order: p.salary DESC
  Limit: 10
```

#### 5. Cypher生成
```
生成3个版本（温度：0.3, 0.45, 0.6）
```

#### 6. 质量验证
```
Candidate 1: Score 0.85
Candidate 2: Score 0.92 ✓ 最佳
Candidate 3: Score 0.78
```

#### 7. 最终结果
```cypher
MATCH (p:Person)-[:WORKS_AT]->(c:Company)
WHERE c.name = '阿里巴巴集团' 
  AND p.work_years > 5 
  AND p.salary > 500000
RETURN p
ORDER BY p.salary DESC
LIMIT 10
```

```
Confidence: 0.92
Processing Time: 3.2s
```

---

## 架构优势

### 1. 分层清晰
- ✅ 每层职责单一，易于理解和维护
- ✅ 层与层之间通过接口解耦
- ✅ 支持独立测试和部署

### 2. 灵活可扩展
- ✅ 可以根据复杂度选择不同策略
- ✅ 模块可以独立升级和替换
- ✅ 支持新功能平滑接入

### 3. 成本可控
- ✅ 简单查询使用模板/小模型
- ✅ 复杂查询才使用昂贵的LLM
- ✅ 缓存和知识库减少重复计算

### 4. 质量保障
- ✅ 多维度验证（语法、语义、执行、性能）
- ✅ 多版本生成与择优
- ✅ 自动修复和优化

### 5. 持续学习
- ✅ 用户反馈闭环
- ✅ 知识库自动更新
- ✅ 示例库不断丰富

---

## 实施路径

### Phase 1: 基础版本（2周）
- ✅ 实现核心流程（编排→分析→生成→验证）
- ✅ 建立基础Schema知识库
- ✅ 实现语法和语义验证
- ✅ 基本的REST API

### Phase 2: 增强版本（1个月）
- ✅ 添加示例库（50-100个）
- ✅ 实现执行验证
- ✅ 优化提示词模板
- ✅ 添加性能监控

### Phase 3: 生产版本（2个月）
- ✅ 添加性能分析
- ✅ 实现反馈学习
- ✅ 完善知识管理
- ✅ 高可用部署

### Phase 4: 智能版本（3个月+）
- ✅ 自适应策略选择
- ✅ 多模型协同
- ✅ 自动知识抽取
- ✅ 持续优化系统

---

## 核心设计原则

### 1. 够用就好
- 不过度设计，根据实际需求迭代
- 先保证基本功能，再优化体验

### 2. 渐进增强
- 从简单到复杂，逐步完善
- 每个阶段都可独立运行

### 3. 成本意识
- 平衡准确率和成本
- 优化LLM调用次数

### 4. 可观测性
- 每个环节都有监控和日志
- 支持问题快速定位

### 5. 可回滚
- 任何改动都可以快速回退
- 版本管理和灰度发布

---

## 弱模型服务交付方案

如果只交付基于弱模型的Cypher生成服务，需要将增强能力固化为可交付资产。

### 核心交付架构

```
NL2Cypher生成服务
├── 核心服务层
│   ├── cypher-generator-service.jar    # 核心生成服务
│   └── config/
│       ├── application.yml              # 配置文件
│       └── model-config.json            # 模型参数配置
│
├── 知识资产包
│   ├── schema-knowledge/
│   │   ├── schema-metadata.json         # Schema元数据
│   │   ├── synonym-dictionary.json      # 同义词词典
│   │   ├── business-glossary.json       # 业务术语表
│   │   └── entity-mappings.json         # 实体映射规则
│   │
│   ├── example-library/
│   │   ├── cypher-examples.json         # Cypher示例库（核心！）
│   │   ├── templates/
│   │   │   ├── simple-query.template    # 简单查询模板
│   │   │   ├── complex-query.template   # 复杂查询模板
│   │   │   └── aggregation.template     # 聚合查询模板
│   │   └── patterns.json                # 常见查询模式
│   │
│   └── prompts/
│       ├── system-prompt.txt            # 系统提示词
│       ├── few-shot-prompt.txt          # Few-shot提示词模板
│       └── optimization-hints.txt       # 优化建议提示词
│
├── 验证规则包
│   ├── validation-rules.json            # 验证规则配置
│   ├── security-policies.json           # 安全策略
│   └── performance-constraints.json     # 性能约束
│
├── 工具脚本
│   ├── schema-extractor.py              # Schema提取工具
│   ├── example-collector.py             # 示例收集工具
│   ├── knowledge-validator.py           # 知识库验证工具
│   └── deployment/
│       ├── deploy.sh                    # 部署脚本
│       └── health-check.sh              # 健康检查脚本
│
└── 文档
    ├── DEPLOYMENT.md                    # 部署指南
    ├── CONFIGURATION.md                 # 配置说明
    ├── KNOWLEDGE_UPDATE.md              # 知识库更新指南
    └── API_REFERENCE.md                 # API参考文档
```

### 关键交付参数详解

#### 1. Schema知识库 (schema-knowledge.json)

**作用**：解决用户用语和Schema不匹配问题

**核心结构**：
```json
{
  "version": "1.0.0",
  "schemaMetadata": {
    "labels": [
      {
        "name": "Person",
        "synonyms": ["员工", "职员", "工作人员", "雇员"],
        "businessMeaning": "代表公司员工，包含基本信息和工作信息",
        "properties": [
          {
            "name": "name",
            "type": "String",
            "indexed": true,
            "businessMeaning": "员工姓名",
            "synonyms": ["姓名", "名字", "称呼"]
          },
          {
            "name": "salary",
            "type": "Double",
            "indexed": false,
            "businessMeaning": "年薪（单位：万元）",
            "synonyms": ["薪资", "工资", "收入", "年薪"],
            "valueRange": {"min": 0, "max": 10000}
          }
        ]
      }
    ],
    "relationships": [
      {
        "type": "WORKS_AT",
        "synonyms": ["工作于", "就职于", "在...工作"],
        "fromLabel": "Person",
        "toLabel": "Company",
        "businessMeaning": "员工在某个公司工作"
      }
    ]
  }
}
```

**关键参数**：
- `synonyms`: 同义词列表，提高实体识别准确率
- `businessMeaning`: 业务语义，帮助模型理解字段含义
- `indexed`: 是否索引，提示模型优先使用索引字段
- `valueRange`: 数值范围约束

#### 2. Cypher示例库 (cypher-examples.json)

**这是最重要的交付资产！建议包含100-150个高质量示例**

**核心结构**：
```json
{
  "version": "1.0.0",
  "totalExamples": 150,
  "categories": {
    "simple_query": {
      "examples": [
        {
          "id": "ex_001",
          "naturalLanguage": "查找在阿里巴巴工作的所有员工",
          "cypher": "MATCH (p:Person)-[:WORKS_AT]->(c:Company {name: '阿里巴巴'})\nRETURN p",
          "keyPoints": ["MATCH语句", "关系连接", "属性过滤"],
          "difficulty": "easy",
          "tags": ["match", "relationship", "filter"]
        }
      ]
    },
    "complex_query": {
      "examples": [
        {
          "id": "ex_010",
          "naturalLanguage": "查找在阿里巴巴工作超过5年且年薪大于50万的员工",
          "cypher": "MATCH (p:Person)-[r:WORKS_AT]->(c:Company {name: '阿里巴巴'})\nWHERE r.work_years > 5 AND p.salary > 50\nRETURN p",
          "keyPoints": ["多条件AND连接", "关系属性过滤", "数值比较"],
          "difficulty": "medium",
          "tags": ["match", "multiple-conditions", "where"]
        }
      ]
    }
  },
  "selectionStrategy": {
    "method": "hybrid",
    "vectorSearch": {"enabled": true, "topK": 5},
    "keywordSearch": {"enabled": true, "topK": 5}
  }
}
```

**关键参数**：
- `keyPoints`: 标注关键技术点，帮助模型理解
- `difficulty`: 难度分级（easy/medium/hard）
- `tags`: 标签系统，支持多维度检索
- `selectionStrategy`: 示例选择策略（向量+关键词混合）

#### 3. 提示词模板 (system-prompt.txt)

**核心结构**：
```text
你是一个专业的Cypher查询生成专家。请根据以下信息生成准确的Cypher查询。

## 图数据库Schema
{{schema_info}}

## 用户查询
{{user_query}}

## 查询分析
{{query_analysis}}

## 相似示例（供参考）
{{similar_examples}}

## 生成要求
1. 严格按照Schema定义使用Label和Property名称
2. 优先使用索引字段（标记为indexed的字段）进行过滤
3. 使用参数化查询（$param）而非硬编码值
4. 对于复杂查询，使用WITH子句优化可读性
5. 对于大数据集查询，必须使用LIMIT
6. 使用适当的索引提示（USING INDEX）
7. 避免笛卡尔积（CROSS JOIN）

## 常见错误避免
- ❌ 不要使用不存在的Label或Property
- ❌ 不要在WHERE子句中对非索引字段进行范围查询（大数据集）
- ❌ 不要忘记为聚合查询添加分组条件
- ❌ 不要在多跳查询中遗漏中间节点

## 输出格式
只输出Cypher代码，不要有任何解释、注释或Markdown标记。
```

**关键参数**：
- `{{动态变量}}`: 运行时替换的实际值
- `生成要求`: 明确的代码规范和最佳实践
- `错误避免`: 列出常见错误，降低错误率

#### 4. 模型配置参数 (model-config.json)

```json
{
  "modelConfig": {
    "weakModel": {
      "provider": "qwen",
      "modelName": "Qwen/Qwen2.5-32B-Instruct",
      "apiEndpoint": "http://localhost:8000/v1/chat/completions",
      
      "generationParameters": {
        "temperature": {
          "simple": 0.3,
          "medium": 0.5,
          "complex": 0.7
        },
        "maxTokens": 2048,
        "topP": 0.9
      },
      
      "retryStrategy": {
        "maxRetries": 3,
        "retryDelay": 1000,
        "backoffMultiplier": 2.0
      },
      
      "timeout": {
        "connection": 5000,
        "read": 30000
      }
    },
    
    "promptOptimization": {
      "fewShotCount": 3,
      "maxSchemaInfoLength": 5000,
      "maxExampleLength": 2000,
      "includeKeyPoints": true,
      "includeBusinessMeaning": true
    },
    
    "validation": {
      "enableSyntaxCheck": true,
      "enableSemanticCheck": true,
      "syntaxCheckWeight": 0.2,
      "semanticCheckWeight": 0.8
    }
  }
}
```

**关键参数**：
- `temperature分级`: 根据查询复杂度动态调整
- `retryStrategy`: 重试策略，提高成功率
- `promptOptimization`: 提示词优化参数
- `validation`: 验证配置（语法+语义验证）

#### 5. 验证规则配置 (validation-rules.json)

```json
{
  "validationRules": {
    "syntax": {
      "enabled": true,
      "rules": [
        {"name": "valid_cypher_keywords", "severity": "error"},
        {"name": "balanced_parentheses", "severity": "error"},
        {"name": "valid_string_quotes", "severity": "error"}
      ]
    },
    
    "semantic": {
      "enabled": true,
      "rules": [
        {"name": "label_existence", "severity": "error"},
        {"name": "property_existence", "severity": "warning"},
        {"name": "relationship_validity", "severity": "error"},
        {"name": "index_usage_hint", "severity": "info"}
      ]
    },
    
    "security": {
      "enabled": true,
      "rules": [
        {"name": "no_write_operations", "severity": "error"},
        {"name": "no_dangerous_functions", "severity": "error"}
      ]
    },
    
    "performance": {
      "enabled": true,
      "rules": [
        {"name": "limit_required", "threshold": 10000, "severity": "warning"},
        {"name": "index_preferred", "severity": "info"},
        {"name": "avoid_cartesian_product", "severity": "warning"}
      ]
    }
  }
}
```

### 各组件对生成质量的贡献度

| 交付组件 | 重要性 | 贡献度 | 主要价值 |
|---------|-------|--------|---------|
| **Cypher示例库** | ⭐⭐⭐⭐⭐ | 40% | Few-shot learning，最直接的提升 |
| **Schema知识库** | ⭐⭐⭐⭐⭐ | 25% | 解决术语不匹配，提高准确率 |
| **提示词模板** | ⭐⭐⭐⭐ | 15% | 规范输出格式，减少错误 |
| **验证规则** | ⭐⭐⭐⭐ | 10% | 质量保障，自动纠错 |
| **模型配置** | ⭐⭐⭐ | 5% | 优化生成参数 |
| **工具脚本** | ⭐⭐⭐ | 5% | 降低使用门槛 |

### 交付清单检查表

#### 必须交付（核心）
- [ ] `cypher-generator-service.jar` - 可执行的JAR包
- [ ] `schema-knowledge.json` - Schema知识库
- [ ] `cypher-examples.json` - 至少100个高质量示例
- [ ] `prompts/` - 提示词模板目录
- [ ] `application.yml` - 配置文件
- [ ] `DEPLOYMENT.md` - 部署文档

#### 建议交付（增强）
- [ ] `validation-rules.json` - 验证规则
- [ ] `security-policies.json` - 安全策略
- [ ] `schema-extractor.py` - Schema提取工具
- [ ] `example-collector.py` - 示例收集工具
- [ ] `health-check.sh` - 健康检查脚本

#### 可选交付（扩展）
- [ ] 性能监控Dashboard
- [ ] 用户反馈收集接口
- [ ] 知识库自动更新脚本
- [ ] Docker镜像

### 交付成本评估

| 资产类型 | 工作量 | 说明 |
|---------|-------|------|
| Schema知识库 | 3-5人天 | 需要DBA和业务专家配合 |
| Cypher示例库（100个） | 5-7人天 | 需要标注和审核 |
| 提示词模板 | 2-3人天 | 需要多次迭代优化 |
| 验证规则 | 2-3人天 | 根据实际错误调整 |
| 文档编写 | 2-3人天 | 部署和使用文档 |
| **总计** | **14-21人天** | 约3-4周 |

### 快速交付方案（MVP）

#### 最小交付集（1周内可完成）
```
最小交付包
├── cypher-generator-service.jar
├── schema-knowledge-lite.json      # 精简版（核心Label和Property）
├── cypher-examples-lite.json       # 30-50个核心示例
├── prompt-template.txt             # 单一提示词模板
├── application.yml
└── QUICKSTART.md                   # 快速开始文档
```

**质量预期**：
- 简单查询准确率：70-80%
- 中等复杂度查询准确率：50-60%
- 复杂查询准确率：30-40%

#### 标准交付集（3-4周）
完整交付包（如上所述）

**质量预期**：
- 简单查询准确率：85-95%
- 中等复杂度查询准确率：75-85%
- 复杂查询准确率：60-75%

### 价值展示

#### 1. 准确率对比
```
裸模型（无知识资产）：
- 简单查询：40-50%
- 复杂查询：20-30%

+ 知识资产增强：
- 简单查询：85-95% ↑ 45%
- 复杂查询：60-75% ↑ 40%
```

#### 2. 错误率降低
```
常见错误类型：
- Schema不匹配：从30% → 5%
- 语法错误：从20% → 3%
- 性能问题：从15% → 8%
```

#### 3. 可维护性
```
知识资产可独立更新：
- 新增业务术语 → 更新synonym-dictionary.json
- 新增查询模式 → 更新cypher-examples.json
- 优化提示词 → 更新prompt-template.txt
```

### 交付价值公式

```
高质量Cypher生成 = 弱模型能力 + 知识资产（示例库+Schema库） + 提示词工程 + 验证机制
```

**核心要点**：
1. **Cypher示例库是最核心的交付资产**（100-150个高质量示例）
2. **Schema知识库解决术语匹配问题**（同义词、业务含义）
3. **提示词模板规范生成质量**（包含最佳实践和错误避免）
4. **验证规则保障输出质量**（语法+语义验证）
5. **工具脚本降低使用门槛**（Schema提取、示例收集）

---

## 技术栈

- **后端框架**: Spring Boot 3.1.5
- **构建工具**: Maven
- **数据库**: Neo4j (图数据库)
- **缓存**: Redis
- **HTTP客户端**: OkHttp
- **JSON处理**: Gson
- **日志**: SLF4J + Logback

---

## 相关文档

- [README.md](README.md) - 项目介绍和快速开始
- [USAGE_EXAMPLES.md](USAGE_EXAMPLES.md) - 使用示例

---

## 更新日志

- 2024-01-XX - 初始版本，定义整体架构设计
