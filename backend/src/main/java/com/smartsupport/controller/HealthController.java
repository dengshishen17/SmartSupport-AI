package com.smartsupport.controller;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 健康检查接口。
 * /health   ：Day 1 验收标准“项目能启动、接口能访问”
 * /db-check ：Day 2 第一步验收标准“MySQL 能连接”——真正执行一条 SQL 验证
 */
@RestController // = @Controller + @ResponseBody：返回值不走页面跳转，直接序列化为 JSON
public class HealthController {

    // JdbcTemplate 是 Spring 对 JDBC 的轻量封装。
    // 项目里有两个 JdbcTemplate：jdbcTemplate（MySQL，主数据源）和 pgVectorJdbcTemplate（PostgreSQL）。
    // 必须用 @Qualifier 显式指定 jdbcTemplate，否则按类型注入可能拿到 PostgreSQL 那个，
    // 导致下面的 SELECT DATABASE()（MySQL 专属语法）报语法错误。
    private final JdbcTemplate jdbcTemplate;

    // 构造器注入：Spring 启动时自动把 JdbcTemplate 实例传进来
    public HealthController(@Qualifier("jdbcTemplate") JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    // 注册一个 GET 接口，路径为 /health
    @GetMapping("/health")
    public Map<String, Object> health() {
        return Map.of(
                "code", 200,
                "status", "UP",
                "message", "SmartSupport AI 后端启动成功",
                "timestamp", LocalDateTime.now().toString()
        );
    }

    /**
     * 数据库连通性检查：向 MySQL 实际发送两条 SQL。
     * SELECT VERSION()  返回数据库版本
     * SELECT DATABASE() 返回当前连接的库名（即 url 里的 smart_support）
     * 能拿到结果，证明“网络通 + 账号密码对 + 库存在”三件事全部成立。
     */
    @GetMapping("/db-check")
    public Map<String, Object> dbCheck() {
        Map<String, Object> result = new LinkedHashMap<>();
        try {
            String version = jdbcTemplate.queryForObject("SELECT VERSION()", String.class);
            String database = jdbcTemplate.queryForObject("SELECT DATABASE()", String.class);
            result.put("code", 200);
            result.put("mysqlStatus", "UP");
            result.put("message", "MySQL 连接成功");
            result.put("mysqlVersion", version);
            result.put("currentDatabase", database);
            result.put("timestamp", LocalDateTime.now().toString());
        } catch (Exception e) {
            // 连接失败时不要让页面报 500 白屏，而是返回结构化的错误信息，方便排查
            result.put("code", 500);
            result.put("mysqlStatus", "DOWN");
            result.put("message", "MySQL 连接失败");
            result.put("error", e.getMessage());
        }
        return result;
    }
}
