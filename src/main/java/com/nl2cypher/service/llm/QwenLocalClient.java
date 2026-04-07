package com.nl2cypher.service.llm;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonArray;
import lombok.extern.slf4j.Slf4j;
import okhttp3.*;
import org.springframework.stereotype.Component;
import java.io.IOException;
import java.util.*;
import java.util.concurrent.TimeUnit;

@Slf4j
@Component
public class QwenLocalClient {
    private final OkHttpClient client;
    private final Gson gson;
    private final String apiUrl;
    private final String model;
    private final double temperature;
    private final int maxTokens;

    public QwenLocalClient(String apiUrl, String model, double temperature, int maxTokens) {
        this.client = new OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .build();
        this.gson = new Gson();
        this.apiUrl = apiUrl;
        this.model = model;
        this.temperature = temperature;
        this.maxTokens = maxTokens;
    }

    public String chat(String systemMessage, String userMessage) throws IOException {
        JsonObject requestBody = new JsonObject();
        requestBody.addProperty("model", model);
        
        JsonArray messages = new JsonArray();
        
        if (systemMessage != null && !systemMessage.isEmpty()) {
            JsonObject systemMsg = new JsonObject();
            systemMsg.addProperty("role", "system");
            systemMsg.addProperty("content", systemMessage);
            messages.add(systemMsg);
        }
        
        JsonObject userMsg = new JsonObject();
        userMsg.addProperty("role", "user");
        userMsg.addProperty("content", userMessage);
        messages.add(userMsg);
        
        requestBody.add("messages", messages);
        requestBody.addProperty("temperature", temperature);
        requestBody.addProperty("max_tokens", maxTokens);

        Request request = new Request.Builder()
            .url(apiUrl)
            .addHeader("Content-Type", "application/json")
            .post(RequestBody.create(requestBody.toString(), MediaType.parse("application/json")))
            .build();

        try (Response response = client.newCall(request).execute()) {
            if (!response.isSuccessful()) {
                String errorBody = response.body() != null ? response.body().string() : "Unknown error";
                log.error("Qwen Local API call failed: {} - {}", response.code(), errorBody);
                throw new IOException("Qwen Local API call failed: " + response.code() + " - " + errorBody);
            }

            String responseBody = response.body().string();
            JsonObject jsonResponse = gson.fromJson(responseBody, JsonObject.class);
            
            if (jsonResponse.has("choices") && jsonResponse.getAsJsonArray("choices").size() > 0) {
                JsonObject choice = jsonResponse.getAsJsonArray("choices").get(0).getAsJsonObject();
                return choice.getAsJsonObject("message").get("content").getAsString();
            } else {
                throw new IOException("Invalid response format from Qwen Local API");
            }
        }
    }

    public String chat(String userMessage) throws IOException {
        return chat(null, userMessage);
    }

    public String chatWithJson(String systemMessage, Map<String, Object> userMessageData) throws IOException {
        String jsonUserMessage = gson.toJson(userMessageData);
        return chat(systemMessage, jsonUserMessage);
    }
}
