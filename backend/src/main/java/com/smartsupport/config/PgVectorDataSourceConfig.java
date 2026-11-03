package com.smartsupport.config;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.jdbc.DataSourceBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.core.JdbcTemplate;

import javax.sql.DataSource;

/**
 * 多数据源配置（Day 4 RAG 使用）
 *
 * 为什么需要这个配置类？
 *   - MySQL（spring.datasource）是业务数据库，给 Order/Refund/Ticket 用，必须保持为主数据源
 *   - PostgreSQL（pgvector.datasource）是向量数据库，给 RAG 知识库用，独立隔离
 *   - Spring Boot 默认只自动配置一个数据源；一旦手动定义第二个 DataSource Bean，
 *     自动配置会退出，所以必须把 MySQL 也显式重新声明为 @Primary
 *
 * 配置完成后：
 *   - 现有 MySQL 的 Mapper/Service/Controller 完全不受影响（走 @Primary 的 dataSource）
 *   - 后续手动创建 PgVectorStore 时，注入 pgVectorJdbcTemplate 即可
 */
@Configuration
public class PgVectorDataSourceConfig {

    /**
     * MySQL 主数据源 —— 保持 @Primary，确保现有业务代码正常
     * 属性来源：application.yml 中的 spring.datasource.*
     *
     * 注意：同样不能用 @ConfigurationProperties("spring.datasource") 直接绑
     * DataSourceBuilder.create().build() 出来的 HikariDataSource——
     * Hikari 的属性名是 jdbcUrl 而非 url，直接绑定时 url 字段会丢失（jdbcUrl=null），
     * 第一次获取连接时报 "jdbcUrl is required"。
     * 改用 @Value 显式读取 + DataSourceBuilder.url()（其内部有 url→jdbcUrl 别名映射）。
     */
    @Bean
    @Primary
    public DataSource dataSource(
            @Value("${spring.datasource.url}") String url,
            @Value("${spring.datasource.username}") String username,
            @Value("${spring.datasource.password}") String password) {
        return DataSourceBuilder.create()
                .url(url)
                .username(username)
                .password(password)
                .build();
    }

    /**
     * PostgreSQL 向量库数据源 —— 与 MySQL 隔离，不标记 @Primary
     *
     * 注意：不用 @ConfigurationProperties 绑定，因为 HikariCP 的属性名是 jdbcUrl 而非 url，
     * @ConfigurationProperties("pgvector.datasource") 无法将 url 正确绑定到 HikariDataSource.jdbcUrl，
     * 会导致 "jdbcUrl is required" 启动报错。
     * 改用 @Value 显式读取 + DataSourceBuilder.url() 直接设置，确保 jdbcUrl 正确赋值。
     */
    @Bean(name = "pgVectorDataSource")
    public DataSource pgVectorDataSource(
            @Value("${pgvector.datasource.url}") String url,
            @Value("${pgvector.datasource.username}") String username,
            @Value("${pgvector.datasource.password}") String password) {
        return DataSourceBuilder.create()
                .url(url)
                .username(username)
                .password(password)
                .build();
    }

    /**
     * MySQL 主数据源对应的 JdbcTemplate
     *
     * 为什么必须显式声明？
     *   Spring Boot 的 JdbcTemplateAutoConfiguration 本来会自动创建名为 "jdbcTemplate" 的 Bean，
     *   但它带 @ConditionalOnMissingBean(JdbcOperations.class) —— 容器里一旦已有 JdbcOperations 实现就退让。
     *   本类下方的 pgVectorJdbcTemplate 恰好就是 JdbcOperations 的实现，且用户配置类先于自动配置处理，
     *   于是自动配置被跳过，容器里**只剩** pgVectorJdbcTemplate（PostgreSQL）一个 JdbcTemplate。
     *
     *   后果：任何按类型注入 JdbcTemplate 的地方，拿到的都是 PostgreSQL。
     *   HealthController 的 SELECT DATABASE() 是 MySQL 专属语法，在 PG 上必然报
     *   "bad SQL grammar [SELECT DATABASE()]"，导致 /db-check 永远返回 mysqlStatus=DOWN。
     *
     * 这里显式补出 MySQL 版的 jdbcTemplate，并标 @Primary（与 Spring Boot 原生行为一致），
     * 让「默认的 JdbcTemplate = MySQL」这一约定恢复，同时保持 PG 侧仍需显式 @Qualifier 注入。
     */
    @Bean(name = "jdbcTemplate")
    @Primary
    public JdbcTemplate jdbcTemplate(@Qualifier("dataSource") DataSource dataSource) {
        return new JdbcTemplate(dataSource);
    }

    /**
     * PostgreSQL 专属 JdbcTemplate
     * 后续给 PgVectorStore 用，和 MySQL 的 JdbcTemplate 互不干扰
     */
    @Bean(name = "pgVectorJdbcTemplate")
    public JdbcTemplate pgVectorJdbcTemplate(
            @Qualifier("pgVectorDataSource") DataSource pgVectorDataSource) {
        return new JdbcTemplate(pgVectorDataSource);
    }
}
