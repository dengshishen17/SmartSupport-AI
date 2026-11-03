package com.smartsupport;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * SmartSupport AI 后端启动入口。
 *
 * @SpringBootApplication 是一个组合注解，等于：
 *   1. @SpringBootConfiguration —— 标记这是一个 Spring 配置类
 *   2. @EnableAutoConfiguration —— 根据 pom.xml 里的依赖自动配置（如内置 Tomcat、Redis 客户端）
 *   3. @ComponentScan           —— 自动扫描本类所在包及子包中的组件（@RestController 等）
 */
@SpringBootApplication
public class SmartSupportApplication {

    public static void main(String[] args) {
        // 一行代码启动整个 Spring Boot 应用（内置 Tomcat，默认 8080 端口）
        SpringApplication.run(SmartSupportApplication.class, args);
    }
}
