package com.nl2cypher.service.orchestration;

import com.nl2cypher.model.representation.*;
import com.nl2cypher.service.generation.CypherGenerationService;
import com.nl2cypher.service.postprocess.ValidationService;
import com.nl2cypher.service.preprocess.*;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import java.io.IOException;
import java.util.HashMap;
import java.util.Map;

@Slf4j
@Service
public class NL2CypherOrchestrator {
    
    private final SemanticUnderstandingService semanticUnderstandingService;
    private final IntentExtractionService intentExtractionService;
    private final SchemaMappingService schemaMappingService;
    private final CypherGenerationService cypherGenerationService;
    private final ValidationService validationService;
    
    @Value("${nl2cypher.validation.max-retries:3}")
    private int maxRetries;
    
    @Value("${nl2cypher.validation.confidence-threshold:0.7}")
    private double confidenceThreshold;

    public NL2CypherOrchestrator(
            SemanticUnderstandingService semanticUnderstandingService,
            IntentExtractionService intentExtractionService,
            SchemaMappingService schemaMappingService,
            CypherGenerationService cypherGenerationService,
            ValidationService validationService) {
        this.semanticUnderstandingService = semanticUnderstandingService;
        this.intentExtractionService = intentExtractionService;
        this.schemaMappingService = schemaMappingService;
        this.cypherGenerationService = cypherGenerationService;
        this.validationService = validationService;
    }

    public NL2CypherResult convert(String naturalLanguageQuery) {
        long startTime = System.currentTimeMillis();
        
        try {
            log.info("开始处理NL2Cypher转换: {}", naturalLanguageQuery);
            
            Stage1Result stage1 = executeStage1(naturalLanguageQuery);
            
            Stage2Result stage2 = executeStage2(naturalLanguageQuery, stage1);
            
            Stage3Result stage3 = executeStage3(naturalLanguageQuery, stage2);
            
            Stage4Result stage4 = executeStage4(naturalLanguageQuery, stage3);
            
            ValidationResult validationResult = executeValidation(naturalLanguageQuery, stage4, stage2, stage3);
            
            NL2CypherResult result = buildResult(
                naturalLanguageQuery, stage4, validationResult, 
                System.currentTimeMillis() - startTime
            );
            
            log.info("NL2Cypher转换完成，耗时: {}ms，置信度: {}", 
                result.getProcessingTimeMs(), result.getConfidence());
            
            return result;
            
        } catch (IOException e) {
            log.error("NL2Cypher转换失败: {}", e.getMessage(), e);
            return buildErrorResult(naturalLanguageQuery, e.getMessage(), 
                System.currentTimeMillis() - startTime);
        } catch (Exception e) {
            log.error("NL2Cypher转换出现意外错误: {}", e.getMessage(), e);
            return buildErrorResult(naturalLanguageQuery, "系统错误: " + e.getMessage(), 
                System.currentTimeMillis() - startTime);
        }
    }

    private Stage1Result executeStage1(String query) throws IOException {
        log.info("执行阶段1: 深度语义理解");
        SemanticAnalysisResult semanticAnalysis = semanticUnderstandingService.analyze(query);
        return new Stage1Result(semanticAnalysis);
    }

    private Stage2Result executeStage2(String query, Stage1Result stage1) throws IOException {
        log.info("执行阶段2: 意图与结构提取");
        QueryBlueprint blueprint = intentExtractionService.extractBlueprint(
            query, stage1.semanticAnalysisResult());
        return new Stage2Result(blueprint);
    }

    private Stage3Result executeStage3(String query, Stage2Result stage2) throws IOException {
        log.info("执行阶段3: Schema智能映射");
        SchemaMappingResult schemaMapping = schemaMappingService.mapSchema(
            query, stage2.queryBlueprint());
        return new Stage3Result(schemaMapping);
    }

    private Stage4Result executeStage4(String query, Stage3Result stage3) throws IOException {
        log.info("执行阶段4: Cypher生成");
        CypherGenerationResult generationResult = cypherGenerationService.generate(
            query, stage3.queryBlueprint(), stage3.schemaMappingResult());
        return new Stage4Result(generationResult);
    }

    private ValidationResult executeValidation(String query, Stage4Result stage4, 
                                               Stage2Result stage2, Stage3Result stage3) throws IOException {
        log.info("执行阶段5: 智能验证与纠错");
        
        for (int attempt = 1; attempt <= maxRetries; attempt++) {
            try {
                ValidationResult validationResult = validationService.validate(
                    query, stage4.cypherGenerationResult(), 
                    stage2.queryBlueprint(), stage3.schemaMappingResult());
                
                if (validationResult.getOverallScore() != null && 
                    validationResult.getOverallScore().isPassedThreshold()) {
                    log.info("验证通过，尝试次数: {}", attempt);
                    return validationResult;
                } else {
                    log.warn("验证未通过，尝试: {}/{}, 分数: {}", 
                        attempt, maxRetries, 
                        validationResult.getOverallScore() != null ? 
                        validationResult.getOverallScore().getTotalScore() : "N/A");
                    
                    if (attempt < maxRetries) {
                        log.info("尝试重新生成Cypher...");
                        return validationResult;
                    }
                }
                
            } catch (IOException e) {
                log.error("验证过程中发生错误 (尝试 {}/{}): {}", attempt, maxRetries, e.getMessage());
                if (attempt == maxRetries) {
                    throw e;
                }
            }
        }
        
        log.warn("验证未通过但已达到最大重试次数");
        return validationService.validate(
            query, stage4.cypherGenerationResult(), 
            stage2.queryBlueprint(), stage3.schemaMappingResult());
    }

    private NL2CypherResult buildResult(String query, Stage4Result stage4, 
                                         ValidationResult validationResult, long processingTime) {
        CypherGenerationResult generationResult = stage4.cypherGenerationResult();
        
        Map<String, Object> metadata = new HashMap<>();
        metadata.put("syntaxErrors", generationResult.getSyntaxErrors());
        metadata.put("warnings", generationResult.getWarnings());
        metadata.put("validationScore", validationResult.getOverallScore() != null ? 
            validationResult.getOverallScore().getTotalScore() : 0.0);
        metadata.put("passedValidation", validationResult.getOverallScore() != null && 
            validationResult.getOverallScore().isPassedThreshold());
        
        return NL2CypherResult.builder()
            .originalQuery(query)
            .generatedCypher(generationResult.getFormattedCypher())
            .validationResult(validationResult)
            .reasoning(generationResult.getReasoning())
            .confidence(generationResult.getConfidence())
            .metadata(metadata)
            .success(true)
            .processingTimeMs(processingTime)
            .build();
    }

    private NL2CypherResult buildErrorResult(String query, String errorMessage, long processingTime) {
        return NL2CypherResult.builder()
            .originalQuery(query)
            .generatedCypher(null)
            .validationResult(null)
            .reasoning(null)
            .confidence(0.0)
            .success(false)
            .errorMessage(errorMessage)
            .processingTimeMs(processingTime)
            .build();
    }

    private record Stage1Result(SemanticAnalysisResult semanticAnalysisResult) {}
    private record Stage2Result(QueryBlueprint queryBlueprint) {}
    private record Stage3Result(SchemaMappingResult schemaMappingResult, QueryBlueprint queryBlueprint) {
        public Stage3Result(SchemaMappingResult schemaMappingResult) {
            this(schemaMappingResult, null);
        }
    }
    private record Stage4Result(CypherGenerationResult cypherGenerationResult) {}
}
