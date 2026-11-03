package com.smartsupport.ai;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import reactor.core.publisher.Flux;

import java.io.IOException;
import java.net.SocketException;
import java.net.SocketTimeoutException;
import java.net.http.HttpTimeoutException;
import java.time.Duration;
import java.util.concurrent.TimeoutException;

/**
 * 流式 AI 调用的网络异常重试装饰器。
 *
 * <p><b>为什么需要它</b><br>
 * 后端通过 Spring AI 直连 {@code api.deepseek.com}（底层是 JDK 内置 {@code HttpClient}）。
 * JDK HttpClient 会复用池化连接；当服务端已经关闭了那条空闲连接、客户端下次复用并写入时，
 * 会直接收到 RST，表现为 {@code Connection reset}（{@code SocketException}）。
 * 这类故障发生在「连接已建立、正在流式读取」的时刻，属于典型的瞬时网络抖动。
 *
 * <p><b>Spring AI 自带重试为何无效</b><br>
 * 1. {@code RetryTemplate.execute(...)} 只出现在同步调用路径上，
 *    流式路径 {@code internalStream} 完全没有使用它；<br>
 * 2. 即便走同步路径，默认 {@code on-client-errors=false}，
 *    IO 异常（连接重置）也不会被判定为可重试。
 *
 * <p><b>本装饰器做的事</b><br>
 * 包装 {@link ChatModel}，在 {@code stream()} 上叠加 Reactor 的指数退避重试：
 * <ul>
 *   <li>只对「瞬时网络异常」重试（连接重置 / 超时 / IO 错误）；</li>
 *   <li>业务类错误（参数错误、鉴权失败、4xx 等）不重试，直接抛出；</li>
 *   <li><b>只有在本轮尚未向客户端推送过任何内容时才重试</b>，
 *       避免重试导致已推送内容重复。</li>
 * </ul>
 *
 * <p>注意：重试发生在 ChatModel 层，记忆顾问（{@code MessageChatMemoryAdvisor}）在其外层，
 * 因此重试不会重复写入聊天记忆。
 */
public class RetryableChatModel implements ChatModel {

    private static final Logger log = LoggerFactory.getLogger(RetryableChatModel.class);

    /** 流式调用失败后的最大重试次数（不含首次请求） */
    public static final int MAX_RETRY_ATTEMPTS = 2;

    /** 首次退避间隔 */
    public static final Duration INITIAL_BACKOFF = Duration.ofSeconds(1);

    /** 退避上限 */
    private static final Duration MAX_BACKOFF = Duration.ofSeconds(4);

    private final ChatModel delegate;

    public RetryableChatModel(ChatModel delegate) {
        this.delegate = delegate;
    }

    @Override
    public ChatResponse call(Prompt prompt) {
        // 同步路径沿用 Spring AI 自己的 RetryTemplate（已在 application.yml 中调优），
        // 这里直接透传，避免两套重试叠加导致请求量翻倍。
        return delegate.call(prompt);
    }

    @Override
    public Flux<ChatResponse> stream(Prompt prompt) {
        return Flux.defer(() -> {
            // hasEmitted：标记本轮是否已经向客户端推送过内容。
            // 一旦推送过，中途失败就不能重试了——否则重放会把已展示的内容再发一遍。
            boolean[] hasEmitted = {false};
            return delegate.stream(prompt)
                    .doOnNext(r -> hasEmitted[0] = true)
                    .retryWhen(retrySpec(hasEmitted));
        });
    }

    @Override
    public ChatOptions getDefaultOptions() {
        return delegate.getDefaultOptions();
    }

    /**
     * 构造指数退避的重试策略：只对瞬时网络异常生效，且只在尚未推送内容时重试。
     */
    private reactor.util.retry.Retry retrySpec(boolean[] hasEmitted) {
        return reactor.util.retry.Retry.backoff(MAX_RETRY_ATTEMPTS, INITIAL_BACKOFF)
                .maxBackoff(MAX_BACKOFF)
                .filter(error -> !hasEmitted[0] && isTransientNetworkError(error))
                .doBeforeRetry(signal -> log.warn(
                        "AI 流式调用遇到瞬时网络异常，正在进行第 {}/{} 次重试：{}",
                        signal.totalRetries() + 1, MAX_RETRY_ATTEMPTS,
                        signal.failure().getMessage()));
    }

    /**
     * 判断异常是否为可重试的瞬时网络异常。
     *
     * <p>沿 cause 链向上查找，覆盖：
     * {@code SocketException}（连接重置 / broken pipe）、
     * 超时类异常（Socket/Http/通用 Timeout）、
     * {@code IOException} 与 {@code WebClientRequestException}。
     */
    public static boolean isTransientNetworkError(Throwable error) {
        for (Throwable t = error; t != null; t = t.getCause()) {
            if (t instanceof WebClientRequestException) {
                return true;
            }
            if (t instanceof SocketTimeoutException
                    || t instanceof HttpTimeoutException
                    || t instanceof TimeoutException) {
                return true;
            }
            if (t instanceof SocketException) {
                String msg = t.getMessage() == null ? "" : t.getMessage();
                // Connection reset / aborted / broken pipe / closed 都是典型的瞬时网络抖动
                if (msg.contains("reset") || msg.contains("aborted")
                        || msg.contains("broken pipe") || msg.contains("closed")) {
                    return true;
                }
            }
            if (t instanceof IOException) {
                return true;
            }
            if (t.getCause() == t) {
                break;
            }
        }
        return false;
    }

    /**
     * 把底层异常翻译成用户能看懂的中文提示。
     *
     * <p>网络类异常统一给一句友好提示（此时已重试过仍失败）；
     * 其他异常保留原始信息，便于排查。
     */
    public static String friendlyMessage(Throwable error) {
        if (error == null) {
            return "未知错误";
        }
        if (isTransientNetworkError(error)) {
            return "网络连接不稳定，暂时无法完成回答，请稍后重试";
        }
        String msg = error.getMessage();
        return (msg == null || msg.isBlank()) ? "未知错误" : msg;
    }
}
