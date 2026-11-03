package com.smartsupport.ai;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartsupport.ai.tool.AfterSaleQueryTools;
import com.smartsupport.common.Result;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.memory.ChatMemory;
import org.springframework.ai.chat.client.advisor.MessageChatMemoryAdvisor;
import org.springframework.ai.deepseek.DeepSeekChatModel;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * AI 聊天接口控制器——用户发一句话，调用 DeepSeek 大模型，返回 AI 的回答。
 *
 * Day 5 升级：接入多轮对话记忆。原理三句话：
 * 1. ChatClient 挂上 MessageChatMemoryAdvisor 顾问，调用前自动从 Redis 读出
 *    该会话的历史消息，和历史一起发给 DeepSeek；调用后自动把本轮问答写回 Redis。
 * 2. 用 sessionId 区分不同会话：前端首次可不传（后端生成新 ID 并在响应里返回），
 *    之后每次带上同一 sessionId 即可连续对话。
 * 3. 历史窗口最多 20 条消息（约 10 轮），Redis 键 2 小时无新消息自动过期。
 */
@RestController
@RequestMapping("/ai")
public class AiChatController {

    private static final Logger log = LoggerFactory.getLogger(AiChatController.class);

    private final ChatClient chatClient;
    private final AfterSaleQueryTools queryTools;
    private final VectorStore vectorStore;
    private final ObjectMapper objectMapper;

    /**
     * 客服身份系统提示词：每次请求都携带，但不会写入记忆（system 消息不进历史）。
     * 作用：让 AI 以"SmartSupport 智能客服助手"的身份回答，而不是暴露成底层 DeepSeek 模型。
     */
    private static final String SYSTEM_PROMPT = """
            你是 SmartSupport 智能客服助手。

            你的职责：
            1. 解答商品咨询
            2. 查询订单信息
            3. 处理售后问题
            4. 介绍商品功能

            回复要求：
            1. 语言友好，像真人客服
            2. 不确定的信息不要编造
            3. 如果用户问题与客服无关，礼貌提醒用户
            """;

    public AiChatController(DeepSeekChatModel chatModel, ChatMemory chatMemory,
                            AfterSaleQueryTools queryTools, VectorStore vectorStore,
                            ObjectMapper objectMapper) {
        // 基于同一个 DeepSeekChatModel 构建 ChatClient，挂载记忆顾问。
        // 外层再包一层 RetryableChatModel：为「流式调用」补上 Spring AI 缺失的
        // 瞬时网络异常重试（JDK HttpClient 复用已失效连接时会收到 RST，
        // 表现为 "Connection reset"）。重试发生在记忆顾问内侧，不会重复写入聊天记忆。
        this.chatClient = ChatClient.builder(new RetryableChatModel(chatModel))
                .defaultAdvisors(MessageChatMemoryAdvisor.builder(chatMemory).build())
                .build();
        this.queryTools = queryTools;
        this.vectorStore = vectorStore;
        this.objectMapper = objectMapper;
    }

    /**
     * AI 聊天接口（支持多轮对话）
     * POST /ai/chat
     * 请求体 JSON 格式：{"message": "你好", "sessionId": "可选，续聊时传上一次响应返回的值"}
     */
    @PostMapping("/chat")
    public Result<Map<String, String>> chat(@RequestBody ChatRequest request) {
        // 1. 入参校验：空消息直接拒绝，不浪费一次大模型调用（要花钱的）
        if (request == null || request.message() == null || request.message().isBlank()) {
            return Result.fail("message 不能为空");
        }
        // 2. sessionId 可选：不传则生成新会话（行为等同旧版单轮）；传入同一 ID 即连续对话
        String sessionId = (request.sessionId() == null || request.sessionId().isBlank())
                ? UUID.randomUUID().toString()
                : request.sessionId();
        // 3. RAG 检索：命中知识则把内容拼进 System Prompt 的【知识参考】段。
        //    阈值取 0.3 而不是知识库接口的 0：聊天接口混有闲聊，阈值过低会让
        //    "你好"也硬配一段政策白耗 Token；0.3 能挡住闲聊、放过口语化售后问题。
        //    检索失败（向量库/嵌入服务不可用）时降级为普通对话，不影响接口可用。
        String systemPrompt = SYSTEM_PROMPT;
        try {
            List<Document> retrieved = vectorStore.similaritySearch(
                    SearchRequest.builder()
                            .query(request.message())
                            .topK(3)
                            .similarityThreshold(0.3)
                            .build()
            );
            if (retrieved != null && !retrieved.isEmpty()) {
                String context = retrieved.stream()
                        .map(Document::getText)
                        .collect(Collectors.joining("\n\n---\n\n"));
                systemPrompt = SYSTEM_PROMPT + """

                        当用户问题涉及商品、订单、售后等业务规则时，优先依据下方知识参考回答，不要编造；
                        知识参考中没有的内容，如实说明不确定。与业务无关的闲聊正常聊天即可，不用参考知识。

                        【知识参考】
                        %s
                        """.formatted(context);
            }
        } catch (Exception ignored) {
            // 降级：检索异常时使用原始 SYSTEM_PROMPT，聊天功能不受影响
        }
        // 4. 调用大模型：advisors 参数指定本次请求使用哪个会话的记忆
        try {
            String reply = chatClient.prompt()
                    .system(systemPrompt)
                    .user(request.message())
                    .tools(queryTools)
                    .advisors(a -> a.param(ChatMemory.CONVERSATION_ID, sessionId))
                    .call()
                    .content();
            // 5. 返回回答 + sessionId（前端保存它，下次请求带上即可续聊）
            return Result.ok(Map.of("reply", reply, "sessionId", sessionId));
        } catch (Exception e) {
            // 调用失败（如密钥无效 401、网络超时）时返回友好错误，不让前端收到白屏 500
            return Result.fail("AI 调用失败：" + e.getMessage());
        }
    }

    /**
     * AI 聊天流式接口（Day 7 SSE）
     * POST /ai/chat/stream
     *
     * 最简版本：只 .user(message)，不带 system prompt、不带工具、不带 RAG、不带记忆。
     * 响应类型 text/event-stream，逐 chunk 推送，协议如下：
     *   data: {"type":"content","content":"增量文本"}
     *   ...
     *   data: {"type":"done","sessionId":"会话ID"}
     * 出错：
     *   data: {"type":"error","code":"LLM_ERROR","message":"错误信息"}
     */
    @PostMapping(value = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamChat(@RequestBody ChatRequest request) {
        // 300 秒超时：AI 流式生成可能较慢，给足时间
        SseEmitter emitter = new SseEmitter(300_000L);

        // 入参校验：空消息直接推错误事件并结束
        if (request == null || request.message() == null || request.message().isBlank()) {
            sendEvent(emitter, Map.of("type", "error", "code", "BAD_REQUEST", "message", "message 不能为空"));
            emitter.complete();
            return emitter;
        }

        // sessionId 生成逻辑与同步接口一致
        String sessionId = (request.sessionId() == null || request.sessionId().isBlank())
                ? UUID.randomUUID().toString()
                : request.sessionId();

        // RAG 检索：与同步版 /ai/chat 一致，topK=3, threshold=0.3
        // 命中知识则拼进 system prompt；检索异常时降级为纯 SYSTEM_PROMPT
        String systemPrompt = SYSTEM_PROMPT;
        try {
            List<Document> retrieved = vectorStore.similaritySearch(
                    SearchRequest.builder()
                            .query(request.message())
                            .topK(3)
                            .similarityThreshold(0.3)
                            .build()
            );
            if (retrieved != null && !retrieved.isEmpty()) {
                String context = retrieved.stream()
                        .map(Document::getText)
                        .collect(Collectors.joining("\n\n---\n\n"));
                systemPrompt = SYSTEM_PROMPT + """

                        当用户问题涉及商品、订单、售后等业务规则时，优先依据下方知识参考回答，不要编造；
                        知识参考中没有的内容，如实说明不确定。与业务无关的闲聊正常聊天即可，不用参考知识。

                        【知识参考】
                        %s
                        """.formatted(context);
            }
        } catch (Exception ignored) {
            // 降级：检索异常时使用原始 SYSTEM_PROMPT，聊天功能不受影响
        }

        // 兜底回调：超时/异常/完成时清理
        emitter.onTimeout(emitter::complete);
        emitter.onError(e -> emitter.complete());

        // 流式调用：system 带 RAG 知识、挂工具、带记忆
        chatClient.prompt()
                .system(systemPrompt)
                .user(request.message())
                .tools(queryTools)
                .advisors(a -> a.param(ChatMemory.CONVERSATION_ID, sessionId))
                .stream()
                .content()
                .subscribe(
                        chunk -> {
                            // 跳过空 chunk（Spring AI 流里可能出现空字符串）
                            if (chunk != null && !chunk.isEmpty()) {
                                sendEvent(emitter, Map.of("type", "content", "content", chunk));
                            }
                        },
                        error -> {
                            // 网络类异常（连接重置 / 超时）翻译成用户能看懂的中文提示，
                            // 不把 "Connection reset" 这种底层错误直接抛给前端
                            log.warn("AI 流式回答失败：{}", error.toString());
                            sendEvent(emitter, Map.of("type", "error", "code", "LLM_ERROR",
                                    "message", RetryableChatModel.friendlyMessage(error)));
                            emitter.complete();
                        },
                        () -> {
                            sendEvent(emitter, Map.of("type", "done", "sessionId", sessionId));
                            emitter.complete();
                        }
                );

        return emitter;
    }

    /**
     * 用 ObjectMapper 序列化事件数据并通过 SseEmitter 推送。
     * 统一封装，避免手写 JSON 字符串导致引号/换行转义错误。
     */
    private void sendEvent(SseEmitter emitter, Map<String, Object> data) {
        try {
            String json = objectMapper.writeValueAsString(data);
            emitter.send(SseEmitter.event().data(json));
        } catch (IOException e) {
            // 推送失败通常意味着连接已断开，直接结束 emitter
            emitter.complete();
        }
    }

    /**
     * 请求体对应的 Java 对象。
     * record 是 Java 17 的简化类写法：一行顶以前十几行，
     * 自动生成构造器和 message() 读取方法，Jackson 能直接把 JSON 转成它。
     * sessionId 为新增可选字段：旧请求 {"message":"..."} 不带它也完全兼容。
     */
    public record ChatRequest(String message, String sessionId) {
    }
}
