package com.smartsupport.ai;

import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.Prompt;
import reactor.core.publisher.Flux;

import java.io.IOException;
import java.net.SocketException;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * RetryableChatModel 的单元测试。
 *
 * <p>验证四件事：
 * 1. 瞬时网络异常（Connection reset）会被自动重试并最终成功；
 * 2. 连续失败超过重试上限后抛出异常；
 * 3. 非网络类异常不重试，直接抛出；
 * 4. 已经向客户端推送过内容后失败时不再重试（避免内容重复）。
 *
 * <p>用 {@link CountDownLatch} 等待异步流结束，不依赖 reactor-test（离线环境无该依赖）。
 */
class RetryableChatModelTest {

    /** 模拟上游：前 failTimes 次抛 Connection reset，之后正常返回内容 */
    private static ChatModel flakyModel(int failTimes, AtomicInteger calls) {
        return new ChatModel() {
            @Override
            public ChatResponse call(Prompt prompt) {
                throw new UnsupportedOperationException();
            }

            @Override
            public Flux<ChatResponse> stream(Prompt prompt) {
                return Flux.defer(() -> {
                    int n = calls.incrementAndGet();
                    if (n <= failTimes) {
                        return Flux.error(new SocketException("Connection reset"));
                    }
                    return Flux.just(new ChatResponse(List.of()));
                });
            }
        };
    }

    /** 订阅 Flux，收集事件与错误 */
    private static void subscribe(Flux<ChatResponse> flux, AtomicInteger received,
                                  AtomicReference<Throwable> error, CountDownLatch done) {
        flux.subscribe(
                r -> received.incrementAndGet(),
                t -> {
                    error.set(t);
                    done.countDown();
                },
                done::countDown);
    }

    /** 简单的可变引用容器（避免引入 AtomicReference 的 import 顺序问题） */
    private static final class AtomicReference<T> {
        private volatile T value;

        void set(T v) {
            this.value = v;
        }

        T get() {
            return value;
        }
    }

    @Test
    void 瞬时网络异常会自动重试并最终成功() throws InterruptedException {
        AtomicInteger calls = new AtomicInteger();
        AtomicInteger received = new AtomicInteger();
        AtomicReference<Throwable> error = new AtomicReference<>();
        CountDownLatch done = new CountDownLatch(1);

        RetryableChatModel model = new RetryableChatModel(flakyModel(1, calls));
        subscribe(model.stream(new Prompt("hi")), received, error, done);

        assertThat(done.await(20, TimeUnit.SECONDS)).isTrue();
        assertThat(error.get()).isNull();
        assertThat(received.get()).isEqualTo(1);
        assertThat(calls.get()).isEqualTo(2); // 失败 1 次 + 成功 1 次
    }

    @Test
    void 连续失败超过重试上限后抛出异常() throws InterruptedException {
        AtomicInteger calls = new AtomicInteger();
        AtomicInteger received = new AtomicInteger();
        AtomicReference<Throwable> error = new AtomicReference<>();
        CountDownLatch done = new CountDownLatch(1);

        // failTimes=99 意味着永远失败
        RetryableChatModel model = new RetryableChatModel(flakyModel(99, calls));
        subscribe(model.stream(new Prompt("hi")), received, error, done);

        assertThat(done.await(30, TimeUnit.SECONDS)).isTrue();
        assertThat(error.get()).isNotNull();
        assertThat(RetryableChatModel.isTransientNetworkError(error.get())).isTrue();
        // 首次 + MAX_RETRY_ATTEMPTS 次重试
        assertThat(calls.get()).isEqualTo(RetryableChatModel.MAX_RETRY_ATTEMPTS + 1);
    }

    @Test
    void 非网络类异常不重试直接抛出() throws InterruptedException {
        AtomicInteger calls = new AtomicInteger();
        AtomicInteger received = new AtomicInteger();
        AtomicReference<Throwable> error = new AtomicReference<>();
        CountDownLatch done = new CountDownLatch(1);

        ChatModel model = new ChatModel() {
            @Override
            public ChatResponse call(Prompt prompt) {
                throw new UnsupportedOperationException();
            }

            @Override
            public Flux<ChatResponse> stream(Prompt prompt) {
                return Flux.defer(() -> {
                    calls.incrementAndGet();
                    return Flux.error(new IllegalArgumentException("参数错误"));
                });
            }
        };

        subscribe(new RetryableChatModel(model).stream(new Prompt("hi")), received, error, done);

        assertThat(done.await(10, TimeUnit.SECONDS)).isTrue();
        assertThat(error.get()).isInstanceOf(IllegalArgumentException.class);
        assertThat(calls.get()).isEqualTo(1); // 不重试
    }

    @Test
    void 已推送内容后失败不再重试() throws InterruptedException {
        AtomicInteger calls = new AtomicInteger();
        AtomicInteger received = new AtomicInteger();
        AtomicReference<Throwable> error = new AtomicReference<>();
        CountDownLatch done = new CountDownLatch(1);

        ChatModel model = new ChatModel() {
            @Override
            public ChatResponse call(Prompt prompt) {
                throw new UnsupportedOperationException();
            }

            @Override
            public Flux<ChatResponse> stream(Prompt prompt) {
                return Flux.defer(() -> {
                    int n = calls.incrementAndGet();
                    if (n == 1) {
                        // 先推一个 chunk，再抛异常
                        return Flux.concat(
                                Flux.just(new ChatResponse(List.of())),
                                Flux.error(new SocketException("Connection reset")));
                    }
                    return Flux.just(new ChatResponse(List.of()));
                });
            }
        };

        subscribe(new RetryableChatModel(model).stream(new Prompt("hi")), received, error, done);

        assertThat(done.await(10, TimeUnit.SECONDS)).isTrue();
        assertThat(received.get()).isEqualTo(1);
        // 已推送内容后不应重试
        assertThat(calls.get()).isEqualTo(1);
    }

    @Test
    void 网络异常被翻译成友好提示() {
        String msg = RetryableChatModel.friendlyMessage(new SocketException("Connection reset"));
        assertThat(msg).contains("网络连接不稳定");

        String other = RetryableChatModel.friendlyMessage(new IllegalArgumentException("参数错误"));
        assertThat(other).isEqualTo("参数错误");
    }

    @Test
    void 瞬时网络异常识别规则() {
        assertThat(RetryableChatModel.isTransientNetworkError(new IOException("boom"))).isTrue();
        assertThat(RetryableChatModel.isTransientNetworkError(new SocketException("Connection reset"))).isTrue();
        assertThat(RetryableChatModel.isTransientNetworkError(new IllegalArgumentException("x"))).isFalse();
    }
}
