package com.smartsupport.config;

import com.smartsupport.ai.RedisChatMemoryRepository;
import org.springframework.ai.chat.memory.ChatMemory;
import org.springframework.ai.chat.memory.MessageWindowChatMemory;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 聊天记忆配置（Day 5 多轮对话）
 *
 * MessageWindowChatMemory：Spring AI 内置的窗口式记忆，只保留最近 maxMessages 条消息，
 * 超出自动丢弃最旧的，控制每次请求携带历史的 Token 成本。
 * 底层存储由 RedisChatMemoryRepository 提供（Redis，2 小时 TTL 自动过期）。
 *
 * 两个 AI 接口（/ai/chat 和 /ai/knowledge/chat）共用这一个 ChatMemory Bean：
 * 同一 sessionId 下跨接口也能接上上下文（如先问政策、再查订单进度）。
 */
@Configuration
public class ChatMemoryConfig {

    /** 最多保留 20 条消息（user/assistant 各算一条，约 10 轮对话） */
    private static final int MAX_MESSAGES = 20;

    @Bean
    public ChatMemory chatMemory(RedisChatMemoryRepository redisRepository) {
        return MessageWindowChatMemory.builder()
                .chatMemoryRepository(redisRepository)
                .maxMessages(MAX_MESSAGES)
                .build();
    }
}
