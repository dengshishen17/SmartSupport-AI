package com.smartsupport.ai;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartsupport.ai.tool.AfterSaleQueryTools;
import com.smartsupport.common.Result;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.client.advisor.MessageChatMemoryAdvisor;
import org.springframework.ai.chat.memory.ChatMemory;
import org.springframework.ai.chat.model.ToolContext;
import org.springframework.ai.deepseek.DeepSeekChatModel;
import org.springframework.ai.document.Document;
import org.springframework.ai.support.ToolCallbacks;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.definition.ToolDefinition;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * 知识库管理接口（Day 4-4）
 *
 * 提供三个功能：
 * 1. POST /ai/knowledge/import-policy —— 将售后政策 Markdown 导入 PgVectorStore
 * 2. GET  /ai/knowledge/search?query=xxx —— 搜索向量库（验证导入是否成功）
 * 3. POST /ai/knowledge/chat —— RAG 问答：检索知识 + DeepSeek 生成回答
 *
 * VectorStore 和 EmbeddingModel 都是 Spring AI 自动创建的 Bean，
 * 这里通过构造器注入直接使用，不额外创建新 Bean。
 */
@RestController
@RequestMapping("/ai/knowledge")
public class AiKnowledgeController {

    private static final Logger log = LoggerFactory.getLogger(AiKnowledgeController.class);

    private final VectorStore vectorStore;
    private final ChatClient chatClient;
    private final AfterSaleQueryTools queryTools;
    private final ObjectMapper objectMapper;
    /** PostgreSQL 专属 JdbcTemplate，用于直接统计 vector_store 中的已导入文件 */
    private final JdbcTemplate pgJdbcTemplate;

    /** 售后政策文件路径，默认相对于 backend/ 运行目录 */
    @Value("${smartsupport.knowledge.policy-file:../售后政策演示数据.md}")
    private String policyFile;

    public AiKnowledgeController(VectorStore vectorStore, DeepSeekChatModel chatModel,
                                 AfterSaleQueryTools queryTools, ChatMemory chatMemory,
                                 ObjectMapper objectMapper,
                                 @Qualifier("pgVectorJdbcTemplate") JdbcTemplate pgJdbcTemplate) {
        this.vectorStore = vectorStore;
        // 基于同一个 DeepSeekChatModel 构建 ChatClient：
        // 挂载记忆顾问实现多轮对话（Day 5），调用时通过 conversationId 指定会话。
        // 外层包一层 RetryableChatModel，为流式调用补上 Spring AI 缺失的
        // 瞬时网络异常重试（连接重置 / 超时），重试不会重复写入聊天记忆。
        this.chatClient = ChatClient.builder(new RetryableChatModel(chatModel))
                .defaultAdvisors(MessageChatMemoryAdvisor.builder(chatMemory).build())
                .build();
        this.queryTools = queryTools;
        this.objectMapper = objectMapper;
        this.pgJdbcTemplate = pgJdbcTemplate;
    }

    /**
     * 导入售后政策文档到向量库
     * POST /ai/knowledge/import-policy
     *
     * 流程：读文件 → 按 ## 标题拆分段落 → 每段创建 Document → vectorStore.add() 批量嵌入并入库
     */
    @PostMapping("/import-policy")
    public Result<Map<String, Object>> importPolicy() {
        try {
            // 1. 读取 Markdown 文件
            Path filePath = Path.of(policyFile);
            if (!Files.exists(filePath)) {
                return Result.fail("文件不存在：" + filePath.toAbsolutePath());
            }
            String content = Files.readString(filePath);

            // 2. 按 "## " 标题拆分，每个章节作为一个 Document
            List<Document> documents = splitIntoDocuments(content, "售后政策演示数据.md");

            if (documents.isEmpty()) {
                return Result.fail("未提取到任何文档段落");
            }

            // 3. 批量嵌入并写入 PgVectorStore（内部调用阿里云百炼 text-embedding-v4）
            vectorStore.add(documents);

            return Result.ok(Map.of(
                    "imported", documents.size(),
                    "file", filePath.getFileName().toString()
            ));
        } catch (Exception e) {
            return Result.fail("导入失败：" + e.getMessage());
        }
    }

    /**
     * 上传知识文件并导入向量库（知识库管理页使用）
     * POST /ai/knowledge/upload，multipart/form-data，字段名 file
     *
     * 仅支持 .md / .txt：读取文本 → 按 ## 标题切分 → 逐段 Embedding → 存入 pgvector，
     * 每段 metadata.source 记为原始文件名。
     */
    @PostMapping("/upload")
    public Result<Map<String, Object>> upload(@RequestParam("file") MultipartFile file) {
        if (file == null || file.isEmpty()) {
            return Result.fail("上传文件为空");
        }
        String fileName = file.getOriginalFilename();
        if (fileName == null) {
            return Result.fail("无法获取文件名");
        }
        String lower = fileName.toLowerCase();
        if (!lower.endsWith(".md") && !lower.endsWith(".txt")) {
            return Result.fail("仅支持 .md / .txt 文本文件");
        }

        try {
            String content = new String(file.getBytes(), StandardCharsets.UTF_8);
            List<Document> documents = splitIntoDocuments(content, fileName);
            if (documents.isEmpty()) {
                return Result.fail("未提取到任何文档段落（文档至少需要包含一个 ## 章节标题）");
            }
            vectorStore.add(documents);

            return Result.ok(Map.of(
                    "fileName", fileName,
                    "imported", documents.size()
            ));
        } catch (Exception e) {
            return Result.fail("上传导入失败：" + e.getMessage());
        }
    }

    /**
     * 已导入知识文件列表（知识库管理页使用）
     * GET /ai/knowledge/files
     *
     * 直接统计 vector_store 表：按 metadata.source 分组，返回每个文件的段落数。
     */
    @GetMapping("/files")
    public Result<List<Map<String, Object>>> files() {
        try {
            List<Map<String, Object>> rows = pgJdbcTemplate.queryForList(
                    "SELECT metadata->>'source' AS source, COUNT(*) AS chunks " +
                    "FROM vector_store GROUP BY 1 ORDER BY 1"
            );
            return Result.ok(rows);
        } catch (Exception e) {
            return Result.fail("查询文件列表失败：" + e.getMessage());
        }
    }

    /**
     * 按 "## " 标题把文档拆成段落，每段构造一个带 source 元数据的 Document。
     * import-policy 与 upload 共用，保证切分口径一致。
     */
    private List<Document> splitIntoDocuments(String content, String source) {
        String[] sections = content.split("(?=\n## )");
        List<Document> documents = new ArrayList<>();
        for (String section : sections) {
            String trimmed = section.trim();
            if (trimmed.isEmpty()) continue;
            // 跳过文件开头的前言部分（# 标题 + 声明），不含正文
            if (trimmed.startsWith("# ") && !trimmed.contains("\n## ")) continue;

            documents.add(new Document(trimmed, Map.of("source", source)));
        }
        return documents;
    }

    /**
     * 搜索向量库（验证导入是否成功）
     * GET /ai/knowledge/search?query=退款流程
     *
     * 返回与 query 最相似的 3 条知识段落
     */
    @GetMapping("/search")
    public Result<List<Map<String, Object>>> search(@RequestParam String query) {
        try {
            List<Document> results = vectorStore.similaritySearch(
                    SearchRequest.builder().query(query).topK(3).build()
            );

            List<Map<String, Object>> response = results.stream()
                    .map(doc -> Map.<String, Object>of(
                            "content", doc.getText(),
                            "score", doc.getScore() != null ? doc.getScore() : 0.0,
                            "metadata", doc.getMetadata()
                    ))
                    .toList();

            return Result.ok(response);
        } catch (Exception e) {
            return Result.fail("搜索失败：" + e.getMessage());
        }
    }

    /**
     * 售后知识问答（RAG）
     * POST /ai/knowledge/chat
     * 请求体：{"question": "退款需要多久到账"}
     *
     * 流程：用户问题 → 向量检索售后政策 → 拼接知识上下文 → DeepSeek 生成回答
     */
    @PostMapping("/chat")
    public Result<Map<String, Object>> chat(@RequestBody KnowledgeChatRequest request) {
        if (request == null || request.question() == null || request.question().isBlank()) {
            return Result.fail("question 不能为空");
        }

        // sessionId 可选：不传则生成新会话（行为等同旧版单轮）；传入同一 ID 即可连续追问
        String sessionId = (request.sessionId() == null || request.sessionId().isBlank())
                ? UUID.randomUUID().toString()
                : request.sessionId();

        try {
            // 1. 从 PgVectorStore 检索售后政策段落
            // topK=5 多召回，similarityThreshold=0.0 显式接受全部（口语表达与正式政策
            // 的语义距离偏大，阈值过严会导致口语化提问检索为空）
            List<Document> retrieved = vectorStore.similaritySearch(
                    SearchRequest.builder()
                            .query(request.question())
                            .topK(5)
                            .similarityThreshold(0.0)
                            .build()
            );

            if (retrieved.isEmpty()) {
                // 只有向量库完全没数据时才会走到这里（阈值已为 0 不过滤）
                // 客服式兜底：共情 + 说明现状 + 不编造政策
                // 注意：同样挂载查询工具！用户问具体订单号时（如"订单 10001 到哪了"），
                // 即使知识库为空，AI 也能调用工具查真实业务数据，而不是机械地让用户重复提供
                // 提示词拆两段：指令放 system（每轮重新注入，不进历史），问题放 user（进历史）
                String fallbackSystem = """
                        你是企业售后客服。用户正在咨询售后问题，但售后政策知识库暂时没有检索到相关条文。
                        请这样做：
                        1. 先对用户的问题表示理解和重视（如涉及商品质量问题，表达歉意）
                        2. 用户的问题涉及具体订单号时，直接调用查询工具获取真实业务数据并如实告知用户；政策规则类问题则说明暂时无法确认具体规则，为避免误导不做主观判断
                        3. 只有在确实缺少必要信息时才追问（如用户没提供订单号、或需要了解商品问题的具体表现）
                        4. 用户也可以直接转人工客服处理
                        语气自然亲切，像真实客服一样说话。使用纯文本输出，不要使用任何 Markdown 格式符号。控制在 150 字以内。
                        """;
                String reply = chatClient.prompt()
                        .system(fallbackSystem)
                        .user(request.question())
                        .tools(queryTools)
                        .advisors(a -> a.param(ChatMemory.CONVERSATION_ID, sessionId))
                        .call()
                        .content();
                return Result.ok(Map.of(
                        "reply", reply,
                        "sources", List.of(),
                        "rag", false,
                        "sessionId", sessionId
                ));
            }

            // 2. 拼接检索到的政策知识作为上下文
            String context = retrieved.stream()
                    .map(Document::getText)
                    .collect(Collectors.joining("\n\n---\n\n"));

            // 3. 构建 Prompt：指令 + 政策知识放 system（每轮重新注入、不进历史），
            //    用户问题单独放 user（进历史）——这样 Redis 里存的是干净的问答对，
            //    不会把大段政策上下文重复塞进每一轮历史，节省 Token
            String systemPrompt = """
                    你是企业售后客服，正在接待一位客户。请根据以下售后政策知识处理客户的诉求。
                    处理要求：
                    1. 先理解客户的真实意图（退货、退款、换货、保修、查物流等），即使用户的表达很口语化
                    2. 只依据下方知识内容回答具体规则，不要编造政策条款
                    3. 用户提出明确诉求时（如要退货），先共情安抚，再直接说明对应的处理规则、流程和时效
                    4. 用户的问题涉及具体订单号时，优先调用查询工具获取真实业务数据（订单状态、退款进度、工单进度），再结合政策回答，不要凭空猜测数据
                    5. 如果处理该诉求还需要更多信息（如购买时间、订单编号、商品具体状况），在说明规则后自然地追问
                    6. 如果知识中确实没有相关规则，明确说明暂时无法确认，建议转人工客服，不要硬答
                    7. 用自然、简洁、连贯的中文回答，像真实客服一样说话
                    8. 使用纯文本输出，不要使用任何 Markdown 格式：不要加粗符号、不要标题符号、不要减号列表符号；需要分点时用"第一、第二"或分号自然衔接
                    9. 回答控制在 250 字以内

                    【售后政策知识】
                    %s
                    """.formatted(context);

            // 4. 调用 DeepSeek 生成回答（挂载查询工具）
            // 模型判断问题涉及具体订单号时，会自动调用 queryOrderByOrderNo 等工具
            // 拿到真实业务数据后再组织语言回答，而不是凭政策条文猜
            String reply = chatClient.prompt()
                    .system(systemPrompt)
                    .user(request.question())
                    .tools(queryTools)
                    .advisors(a -> a.param(ChatMemory.CONVERSATION_ID, sessionId))
                    .call()
                    .content();

            // 5. 返回回答 + 引用来源
            List<String> sources = retrieved.stream()
                    .map(doc -> doc.getMetadata().getOrDefault("source", "unknown").toString())
                    .toList();

            return Result.ok(Map.of(
                    "reply", reply,
                    "sources", sources,
                    "rag", true,
                    "sessionId", sessionId
            ));
        } catch (Exception e) {
            return Result.fail("知识问答失败：" + e.getMessage());
        }
    }

    /**
     * 售后知识问答流式接口（SSE）
     * POST /ai/knowledge/chat/stream
     *
     * 与同步版 /chat 的 RAG 逻辑一致（topK=5, threshold=0.0），额外推送：
     *   1. reference 事件：检索完成后先告知前端是否命中知识、引用来源
     *   2. tool start/result 事件：AI 每次调用查询工具时推送工具名、入参、结果
     *   3. content 事件：最终回答逐 chunk 推送
     *   4. done / error 事件
     */
    @PostMapping(value = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamChat(@RequestBody KnowledgeChatRequest request) {
        SseEmitter emitter = new SseEmitter(300_000L);

        if (request == null || request.question() == null || request.question().isBlank()) {
            sendEvent(emitter, Map.of("type", "error", "code", "BAD_REQUEST", "message", "question 不能为空"));
            emitter.complete();
            return emitter;
        }

        String sessionId = (request.sessionId() == null || request.sessionId().isBlank())
                ? UUID.randomUUID().toString()
                : request.sessionId();

        emitter.onTimeout(emitter::complete);
        emitter.onError(e -> emitter.complete());

        // 1. RAG 检索（参数与同步版一致）；检索异常降级为空结果，不中断流式回答
        List<Document> retrieved = List.of();
        try {
            List<Document> docs = vectorStore.similaritySearch(
                    SearchRequest.builder()
                            .query(request.question())
                            .topK(5)
                            .similarityThreshold(0.0)
                            .build()
            );
            if (docs != null) {
                retrieved = docs;
            }
        } catch (Exception ignored) {
            // 向量库/Embedding 不可用时降级为无知识回答
        }

        boolean ragHit = !retrieved.isEmpty();
        List<String> sources = retrieved.stream()
                .map(doc -> doc.getMetadata().getOrDefault("source", "unknown").toString())
                .toList();

        // 2. 命中知识/空库两套 system prompt，与同步版保持一致
        String systemPrompt;
        if (!ragHit) {
            systemPrompt = """
                    你是企业售后客服。用户正在咨询售后问题，但售后政策知识库暂时没有检索到相关条文。
                    请这样做：
                    1. 先对用户的问题表示理解和重视（如涉及商品质量问题，表达歉意）
                    2. 用户的问题涉及具体订单号时，直接调用查询工具获取真实业务数据并如实告知用户；政策规则类问题则说明暂时无法确认具体规则，为避免误导不做主观判断
                    3. 只有在确实缺少必要信息时才追问（如用户没提供订单号、或需要了解商品问题的具体表现）
                    4. 用户也可以直接转人工客服处理
                    语气自然亲切，像真实客服一样说话。使用纯文本输出，不要使用任何 Markdown 格式符号。控制在 150 字以内。
                    """;
        } else {
            String context = retrieved.stream()
                    .map(Document::getText)
                    .collect(Collectors.joining("\n\n---\n\n"));
            systemPrompt = """
                    你是企业售后客服，正在接待一位客户。请根据以下售后政策知识处理客户的诉求。
                    处理要求：
                    1. 先理解客户的真实意图（退货、退款、换货、保修、查物流等），即使用户的表达很口语化
                    2. 只依据下方知识内容回答具体规则，不要编造政策条款
                    3. 用户提出明确诉求时（如要退货），先共情安抚，再直接说明对应的处理规则、流程和时效
                    4. 用户的问题涉及具体订单号时，优先调用查询工具获取真实业务数据（订单状态、退款进度、工单进度），再结合政策回答，不要凭空猜测数据
                    5. 如果处理该诉求还需要更多信息（如购买时间、订单编号、商品具体状况），在说明规则后自然地追问
                    6. 如果知识中确实没有相关规则，明确说明暂时无法确认，建议转人工客服，不要硬答
                    7. 用自然、简洁、连贯的中文回答，像真实客服一样说话
                    8. 使用纯文本输出，不要使用任何 Markdown 格式：不要加粗符号、不要标题符号、不要减号列表符号；需要分点时用"第一、第二"或分号自然衔接
                    9. 回答控制在 250 字以内

                    【售后政策知识】
                    %s
                    """.formatted(context);
        }

        // 3. 检索完成先推 reference 事件，前端可据此渲染"引用来源"
        sendEvent(emitter, Map.of(
                "type", "reference",
                "rag", ragHit,
                "sources", sources
        ));

        // 4. 把 @Tool 工具逐个包装成"会推送 SSE 事件"的回调
        ToolCallback[] wrappedCallbacks = Arrays.stream(ToolCallbacks.from(queryTools))
                .map(delegate -> (ToolCallback) new SseToolCallback(delegate, emitter))
                .toArray(ToolCallback[]::new);

        // 5. 流式生成
        chatClient.prompt()
                .system(systemPrompt)
                .user(request.question())
                .toolCallbacks(wrappedCallbacks)
                .advisors(a -> a.param(ChatMemory.CONVERSATION_ID, sessionId))
                .stream()
                .content()
                .subscribe(
                        chunk -> {
                            if (chunk != null && !chunk.isEmpty()) {
                                sendEvent(emitter, Map.of("type", "content", "content", chunk));
                            }
                        },
                        error -> {
                            // 网络类异常（连接重置 / 超时）翻译成用户能看懂的中文提示，
                            // 不把 "Connection reset" 这种底层错误直接抛给前端
                            log.warn("AI 知识库流式回答失败：{}", error.toString());
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
     * synchronized：Flux 回调线程与工具执行线程可能不同，防止事件报文交错。
     */
    private synchronized void sendEvent(SseEmitter emitter, Map<String, Object> data) {
        try {
            String json = objectMapper.writeValueAsString(data);
            emitter.send(SseEmitter.event().data(json));
        } catch (IOException e) {
            // 推送失败通常意味着连接已断开，直接结束 emitter
            emitter.complete();
        }
    }

    /**
     * 工具回调包装器：在真实工具执行前后各推一条 SSE 事件（start/result 严格成对）。
     * 委托给 Spring AI 根据 @Tool 注解生成的原生 MethodToolCallback，不改业务逻辑。
     */
    private class SseToolCallback implements ToolCallback {

        private final ToolCallback delegate;
        private final SseEmitter emitter;

        SseToolCallback(ToolCallback delegate, SseEmitter emitter) {
            this.delegate = delegate;
            this.emitter = emitter;
        }

        @Override
        public ToolDefinition getToolDefinition() {
            return delegate.getToolDefinition();
        }

        @Override
        public String call(String toolInput) {
            String toolName = getToolDefinition().name();

            // 入参是 JSON 字符串（如 {"orderNo":"10001"}），解析成 JSON 对象推送
            Object args;
            try {
                args = objectMapper.readValue(toolInput == null || toolInput.isBlank() ? "{}" : toolInput, Object.class);
            } catch (Exception e) {
                args = toolInput;
            }
            sendEvent(emitter, Map.of(
                    "type", "tool",
                    "stage", "start",
                    "toolName", toolName,
                    "args", args
            ));

            // 执行真实查询工具
            try {
                String result = delegate.call(toolInput);
                sendEvent(emitter, Map.of(
                        "type", "tool",
                        "stage", "result",
                        "toolName", toolName,
                        "result", result != null ? result : ""
                ));
                return result;
            } catch (RuntimeException e) {
                // 工具本身报错也成对推 result，前端不会一直停在"调用中"状态
                sendEvent(emitter, Map.of(
                        "type", "tool",
                        "stage", "result",
                        "toolName", toolName,
                        "result", "工具执行失败：" + e.getMessage()
                ));
                throw e;
            }
        }

        @Override
        public String call(String toolInput, ToolContext toolContext) {
            // 框架内部可能走双参版本，强制收敛到上面的单参包装逻辑
            return call(toolInput);
        }
    }

    /** 问答请求体。sessionId 为可选字段：续聊时传上一次响应返回的值，旧请求不带它也完全兼容 */
    public record KnowledgeChatRequest(String question, String sessionId) {
    }
}
