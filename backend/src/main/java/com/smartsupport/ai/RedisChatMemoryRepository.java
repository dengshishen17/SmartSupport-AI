package com.smartsupport.ai;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.ai.chat.memory.ChatMemoryRepository;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.MessageType;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * Redis 版聊天记忆仓库（Day 5 多轮对话）
 *
 * 实现 Spring AI 的 ChatMemoryRepository 接口，把对话历史存进现有 Redis。
 * 存储结构：String key = "chat:memory:{sessionId}"，value = 消息列表 JSON，
 * 每次保存全量覆盖并刷新 2 小时 TTL（过期自动清理，无需手动维护）。
 *
 * ┌──────────────────────── 关键设计：只存纯文本对话 ────────────────────────┐
 * │ 历史中只保留 user / assistant 的纯文本消息，丢弃两类消息：               │
 * │ 1. SystemMessage —— 系统提示词每轮由接口重新注入，存了会重复膨胀          │
 * │ 2. 工具调用消息（带 toolCalls 的 assistant / ToolResponseMessage）——     │
 * │    这类消息必须成对出现才合法，若被记忆窗口裁剪拆散，重放历史时            │
 * │    DeepSeek 会直接报 400。过滤后历史永远是干净的"问答对"结构，            │
 * │    工具查询到的数据已体现在 assistant 的最终回复文本里，不丢信息。         │
 * └──────────────────────────────────────────────────────────────────────────┘
 */
@Component
public class RedisChatMemoryRepository implements ChatMemoryRepository {

    private static final String KEY_PREFIX = "chat:memory:";
    /** 会话过期时间：2 小时无新消息自动清理 */
    private static final Duration TTL = Duration.ofHours(2);

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;

    public RedisChatMemoryRepository(StringRedisTemplate redisTemplate, ObjectMapper objectMapper) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
    }

    /** 存储用的简化消息结构：只保留角色和文本内容 */
    public record StoredMessage(String role, String content) {
    }

    @Override
    public List<String> findConversationIds() {
        // 演示项目数据量小，直接用 keys；生产环境应改用 SCAN 增量遍历
        Set<String> keys = redisTemplate.keys(KEY_PREFIX + "*");
        if (keys == null) {
            return List.of();
        }
        return keys.stream().map(k -> k.substring(KEY_PREFIX.length())).toList();
    }

    @Override
    public List<Message> findByConversationId(String conversationId) {
        String json = redisTemplate.opsForValue().get(KEY_PREFIX + conversationId);
        if (json == null || json.isEmpty()) {
            return List.of();
        }
        try {
            StoredMessage[] stored = objectMapper.readValue(json, StoredMessage[].class);
            List<Message> messages = new ArrayList<>();
            for (StoredMessage sm : stored) {
                if ("user".equals(sm.role())) {
                    messages.add(new UserMessage(sm.content()));
                } else if ("assistant".equals(sm.role())) {
                    messages.add(new AssistantMessage(sm.content()));
                }
            }
            return messages;
        } catch (Exception e) {
            // 历史数据损坏时降级为空记忆，宁可"失忆"也不让当次对话报错
            return List.of();
        }
    }

    /**
     * 全量保存。MessageWindowChatMemory 每次都传入"历史 + 新消息"的窗口内完整列表。
     */
    @Override
    public void saveAll(String conversationId, List<Message> messages) {
        try {
            List<StoredMessage> stored = new ArrayList<>();
            for (Message message : messages) {
                if (message.getMessageType() == MessageType.USER) {
                    stored.add(new StoredMessage("user", message.getText()));
                } else if (message.getMessageType() == MessageType.ASSISTANT) {
                    AssistantMessage assistant = (AssistantMessage) message;
                    // 跳过工具调用消息：无文本或带 toolCalls 的都不是自然语言回复
                    boolean hasToolCalls = assistant.getToolCalls() != null && !assistant.getToolCalls().isEmpty();
                    if (!hasToolCalls && assistant.getText() != null && !assistant.getText().isBlank()) {
                        stored.add(new StoredMessage("assistant", assistant.getText()));
                    }
                }
            }
            if (stored.isEmpty()) {
                redisTemplate.delete(KEY_PREFIX + conversationId);
                return;
            }
            String json = objectMapper.writeValueAsString(stored);
            redisTemplate.opsForValue().set(KEY_PREFIX + conversationId, json, TTL);
        } catch (Exception e) {
            // 存储失败不影响当次回答，代价只是失去跨轮记忆
        }
    }

    @Override
    public void deleteByConversationId(String conversationId) {
        redisTemplate.delete(KEY_PREFIX + conversationId);
    }
}
