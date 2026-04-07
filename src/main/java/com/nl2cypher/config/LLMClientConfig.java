package com.nl2cypher.config;

import com.nl2cypher.service.llm.GLMClient;
import com.nl2cypher.service.llm.QwenLocalClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class LLMClientConfig {

    @Value("${nl2cypher.strong-model.api-key}")
    private String zhipuApiKey;

    @Value("${nl2cypher.strong-model.api-url:https://open.bigmodel.cn/api/paas/v4/chat/completions}")
    private String zhipuApiUrl;

    @Value("${nl2cypher.strong-model.model:glm-4-plus}")
    private String zhipuModel;

    @Value("${nl2cypher.strong-model.temperature:0.3}")
    private double zhipuTemperature;

    @Value("${nl2cypher.strong-model.max-tokens:2048}")
    private int zhipuMaxTokens;

    @Value("${nl2cypher.weak-model.api-url}")
    private String qwenApiUrl;

    @Value("${nl2cypher.weak-model.model:Qwen/Qwen2.5-32B-Instruct}")
    private String qwenModel;

    @Value("${nl2cypher.weak-model.temperature:0.7}")
    private double qwenTemperature;

    @Value("${nl2cypher.weak-model.max-tokens:1024}")
    private int qwenMaxTokens;

    @Bean
    public GLMClient glmClient() {
        return new GLMClient(zhipuApiUrl, zhipuApiKey, zhipuModel, 
                            zhipuTemperature, zhipuMaxTokens);
    }

    @Bean
    public QwenLocalClient qwenLocalClient() {
        return new QwenLocalClient(qwenApiUrl, qwenModel, 
                                   qwenTemperature, qwenMaxTokens);
    }
}
