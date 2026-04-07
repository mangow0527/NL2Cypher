package com.nl2cypher;

import com.nl2cypher.model.representation.NL2CypherResult;
import com.nl2cypher.service.orchestration.NL2CypherOrchestrator;
import org.springframework.boot.SpringApplication;
import org.springframework.context.ConfigurableApplicationContext;

public class NL2CypherDemo {
    
    public static void main(String[] args) {
        ConfigurableApplicationContext context = SpringApplication.run(NL2CypherApplication.class, args);
        
        NL2CypherOrchestrator orchestrator = context.getBean(NL2CypherOrchestrator.class);
        
        String[] testQueries = {
            "查找在阿里巴巴工作的所有员工",
            "查找年龄大于30岁的员工",
            "查找张三认识的所有人",
            "查找在阿里巴巴工作超过5年且年龄大于30岁的员工",
            "统计每个公司有多少员工"
        };
        
        System.out.println("=== NL2Cypher 系统演示 ===\n");
        
        for (String query : testQueries) {
            System.out.println("查询: " + query);
            System.out.println("---");
            
            try {
                NL2CypherResult result = orchestrator.convert(query);
                
                if (result.isSuccess()) {
                    System.out.println("生成的Cypher:");
                    System.out.println(result.getGeneratedCypher());
                    System.out.println("\n置信度: " + result.getConfidence());
                    System.out.println("处理时间: " + result.getProcessingTimeMs() + "ms");
                    
                    if (result.getValidationResult() != null && 
                        result.getValidationResult().getOverallScore() != null) {
                        System.out.println("验证分数: " + 
                            result.getValidationResult().getOverallScore().getTotalScore());
                    }
                    
                    if (result.getValidationResult() != null && 
                        result.getValidationResult().getQueryExplanation() != null) {
                        System.out.println("\n查询解释:");
                        System.out.println(result.getValidationResult().getQueryExplanation().getNaturalLanguageExplanation());
                    }
                } else {
                    System.out.println("转换失败: " + result.getErrorMessage());
                }
                
            } catch (Exception e) {
                System.out.println("处理错误: " + e.getMessage());
            }
            
            System.out.println("\n" + "=".repeat(50) + "\n");
        }
        
        context.close();
    }
}
