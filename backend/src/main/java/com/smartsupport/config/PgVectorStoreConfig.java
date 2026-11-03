package com.smartsupport.config;

import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.ai.vectorstore.pgvector.PgVectorStore;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * PG 向量存储配置（Day 4-3）
 *
 * 为什么手动创建而不是用自动配置？
 *   Spring AI 的 PgVectorStoreAutoConfiguration 会用默认 JdbcTemplate，
 *   而默认 JdbcTemplate 绑定的是 @Primary 的 MySQL 数据源——向量会写进 MySQL 而非 PostgreSQL。
 *   所以排除自动配置，在这里用 pgVectorJdbcTemplate 手动创建。
 *
 * 三者关系：
 *   EmbeddingModel（阿里云百炼 text-embedding-v4）→ 把文本变成 1024 维向量
 *   pgVectorJdbcTemplate（PostgreSQL 独立数据源）→ 读写向量数据
 *   PgVectorStore → 把两者组合起来，提供 add() / similaritySearch() 等方法
 */
@Configuration
public class PgVectorStoreConfig {

    /**
     * 向量存储 Bean，后续 RAG 检索和知识库导入都用它
     *
     * @param pgVectorJdbcTemplate PostgreSQL 专属 JdbcTemplate（来自 PgVectorDataSourceConfig）
     * @param embeddingModel       阿里云百炼 text-embedding-v4（由 OpenAiEmbeddingAutoConfiguration 自动创建）
     */
    @Bean
    public VectorStore vectorStore(
            @Qualifier("pgVectorJdbcTemplate") JdbcTemplate pgVectorJdbcTemplate,
            EmbeddingModel embeddingModel) {
        return PgVectorStore.builder(pgVectorJdbcTemplate, embeddingModel)
                .dimensions(1024)          // 与 application.yml 中 spring.ai.openai.embedding.options.dimensions 一致
                .initializeSchema(true)    // 首次启动自动在 PG 中建表（vector_store 表）
                .build();
    }
}
