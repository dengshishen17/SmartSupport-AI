package com.smartsupport.eval;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.io.InputStream;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * RAG 检索评测服务（只读评测，不修改生产逻辑、不写知识库）。
 *
 * 设计要点：
 * 1. 检索调用与生产链路完全一致——都走 Spring AI 的 VectorStore.similaritySearch(SearchRequest)，
 *    底层是同一个 PgVectorStore Bean（同一张 public.vector_store 表、同一套余弦距离 + HNSW 索引）。
 *    与 AiKnowledgeController 的差别只是本类把 topK / similarityThreshold 变成可扫描的参数，
 *    生产接口写死 topK=5、threshold=0.0。
 *
 * 2. ground truth 用「章节标题」而不是 chunk id：
 *    现有向量库的 Document 只有 metadata.source（文件名），没有 chunk 序号，
 *    且 id 是 uuid_generate_v4() 随机生成、跨次导入不稳定。
 *    但每个 chunk 的 content 都以 "## 章节标题" 开头（如 "## 一、退款政策"），
 *    所以用章节标题做标注既准确又不需要改库、不需要重新导入知识库。
 *
 * 3. 严格只读：本类只对 vector_store 执行 SELECT，绝不 DELETE / UPDATE / INSERT。
 */
@Service
public class RagEvalService {

    private static final Logger log = LoggerFactory.getLogger(RagEvalService.class);

    /** 评测集在 classpath 下的位置 */
    private static final String DATASET_PATH = "eval/rag-eval-cases.json";

    private final VectorStore vectorStore;
    private final ObjectMapper objectMapper;
    private final JdbcTemplate pgJdbcTemplate;

    public RagEvalService(VectorStore vectorStore,
                          ObjectMapper objectMapper,
                          @Qualifier("pgVectorJdbcTemplate") JdbcTemplate pgJdbcTemplate) {
        this.vectorStore = vectorStore;
        this.objectMapper = objectMapper;
        this.pgJdbcTemplate = pgJdbcTemplate;
    }

    // ==================== 对外方法 ====================

    /**
     * 读取知识库现状（只读 SELECT），用于报告里说明「被评测的知识库到底是什么状态」。
     */
    public Map<String, Object> knowledgeBaseInfo() {
        Map<String, Object> info = new LinkedHashMap<>();
        List<Map<String, Object>> bySource = pgJdbcTemplate.queryForList(
                "SELECT metadata->>'source' AS source, COUNT(*) AS chunks "
                        + "FROM public.vector_store GROUP BY 1 ORDER BY 1");
        info.put("chunksBySource", bySource);

        List<Map<String, Object>> chunks = pgJdbcTemplate.queryForList(
                "SELECT id, metadata->>'source' AS source, content FROM public.vector_store ORDER BY id");
        List<Map<String, Object>> detail = new ArrayList<>();
        for (Map<String, Object> row : chunks) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("id", String.valueOf(row.get("id")));
            item.put("source", row.get("source"));
            item.put("section", extractSection(String.valueOf(row.get("content"))));
            item.put("contentLength", String.valueOf(row.get("content")).length());
            detail.add(item);
        }
        info.put("chunkDetails", detail);
        info.put("totalChunks", detail.size());
        return info;
    }

    /**
     * 读取评测集。
     */
    public Map<String, Object> loadDataset() {
        try (InputStream in = new ClassPathResource(DATASET_PATH).getInputStream()) {
            JsonNode root = objectMapper.readTree(in);
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("version", root.path("version").asText(""));
            out.put("description", root.path("description").asText(""));
            out.put("groundTruthBasis", root.path("groundTruthBasis").asText(""));
            List<EvalCase> cases = parseCases(root);
            out.put("totalCases", cases.size());
            out.put("answerableCases", cases.stream().filter(c -> !c.outOfScope()).count());
            out.put("outOfScopeCases", cases.stream().filter(EvalCase::outOfScope).count());
            out.put("cases", cases.stream().map(c -> c.toMap()).toList());
            return out;
        } catch (Exception e) {
            throw new IllegalStateException("读取评测集失败：" + e.getMessage(), e);
        }
    }

    /**
     * 执行检索评测：对 (topK × similarityThreshold) 参数矩阵逐组合批量检索并计算指标。
     */
    public Map<String, Object> runRetrievalEval(List<Integer> topKs, List<Double> thresholds) {
        List<EvalCase> cases = parseCases(readDatasetNode());
        List<EvalCase> answerable = cases.stream().filter(c -> !c.outOfScope()).toList();
        List<EvalCase> outOfScope = cases.stream().filter(EvalCase::outOfScope).toList();

        List<Map<String, Object>> configs = new ArrayList<>();
        for (Integer topK : topKs) {
            for (Double threshold : thresholds) {
                configs.add(evaluateConfig(cases, answerable, outOfScope, topK, threshold));
            }
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("knowledgeBase", knowledgeBaseInfo());
        result.put("answerableCount", answerable.size());
        result.put("outOfScopeCount", outOfScope.size());
        result.put("configs", configs);
        return result;
    }

    // ==================== 内部实现 ====================

    /**
     * 评测单个参数组合 (topK, threshold)。
     */
    private Map<String, Object> evaluateConfig(List<EvalCase> allCases,
                                               List<EvalCase> answerable,
                                               List<EvalCase> outOfScope,
                                               int topK,
                                               double threshold) {
        List<Map<String, Object>> caseRows = new ArrayList<>();

        int hit1 = 0, hit3 = 0, hit5 = 0;
        double mrrSum = 0.0;
        long totalLatencyNs = 0L;
        long maxLatencyNs = 0L;
        int totalReturned = 0;

        for (EvalCase c : answerable) {
            RetrievalOutcome outcome = retrieve(c.query(), topK, threshold);

            // 首个命中 chunk 的排名（1 起），0 表示未命中
            int firstHitRank = 0;
            for (int i = 0; i < outcome.sections().size(); i++) {
                if (c.matches(outcome.sections().get(i))) {
                    firstHitRank = i + 1;
                    break;
                }
            }
            if (firstHitRank > 0) {
                mrrSum += 1.0 / firstHitRank;
                if (firstHitRank <= 1) hit1++;
                if (firstHitRank <= 3) hit3++;
                if (firstHitRank <= 5) hit5++;
            }

            totalLatencyNs += outcome.latencyNs();
            maxLatencyNs = Math.max(maxLatencyNs, outcome.latencyNs());
            totalReturned += outcome.sections().size();

            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", c.id());
            row.put("query", c.query());
            row.put("category", c.category());
            row.put("expectedSections", c.expectedSections());
            row.put("firstHitRank", firstHitRank);
            row.put("hit", firstHitRank > 0);
            row.put("returnedCount", outcome.sections().size());
            row.put("latencyMs", round(outcome.latencyNs() / 1_000_000.0));
            row.put("retrieved", outcome.detail());
            caseRows.add(row);
        }

        // out_of_scope 探针：单独统计，不计入 Hit Rate / MRR 分母
        List<Map<String, Object>> oosRows = new ArrayList<>();
        double oosScoreSum = 0.0;
        for (EvalCase c : outOfScope) {
            RetrievalOutcome outcome = retrieve(c.query(), topK, threshold);
            oosScoreSum += outcome.topScore();
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", c.id());
            row.put("query", c.query());
            row.put("topScore", round(outcome.topScore()));
            row.put("topSection", outcome.sections().isEmpty() ? null : outcome.sections().get(0));
            row.put("latencyMs", round(outcome.latencyNs() / 1_000_000.0));
            oosRows.add(row);
        }

        int n = answerable.size();
        Map<String, Object> metrics = new LinkedHashMap<>();
        metrics.put("hitRateAt1", ratio(hit1, n));
        metrics.put("hitRateAt3", ratio(hit3, n));
        metrics.put("hitRateAt5", ratio(hit5, n));
        metrics.put("hitAt1Count", hit1);
        metrics.put("hitAt3Count", hit3);
        metrics.put("hitAt5Count", hit5);
        metrics.put("mrr", n == 0 ? 0.0 : round(mrrSum / n));
        metrics.put("avgLatencyMs", round(totalLatencyNs / 1_000_000.0 / Math.max(n, 1)));
        metrics.put("maxLatencyMs", round(maxLatencyNs / 1_000_000.0));
        metrics.put("avgReturnedChunks", round((double) totalReturned / Math.max(n, 1)));

        // 明确标注每个 Hit Rate@K 是否被 topK 截断：
        // 当 topK < K 时，实际最多只能命中第 topK 条，此时 Hit Rate@K 实际等于 Hit Rate@topK，
        // 不能与 topK >= K 的组合横向比较，必须在报告里区分标注。
        Map<String, Object> capping = new LinkedHashMap<>();
        capping.put("hitAt1", topK >= 1 ? "valid" : "capped");
        capping.put("hitAt3", topK >= 3 ? "valid" : "capped_by_topK");
        capping.put("hitAt5", topK >= 5 ? "valid" : "capped_by_topK");
        metrics.put("hitRateCapping", capping);

        Map<String, Object> oos = new LinkedHashMap<>();
        oos.put("note", "out_of_scope 探针：只做描述性统计（top-1 相似度），不计入 Hit Rate / MRR");
        oos.put("avgTopScore", outOfScope.isEmpty() ? null : round(oosScoreSum / outOfScope.size()));
        oos.put("rows", oosRows);

        Map<String, Object> config = new LinkedHashMap<>();
        config.put("topK", topK);
        config.put("similarityThreshold", threshold);
        config.put("hitAtKComputable", List.of(1, 3, 5).stream().filter(k -> k <= topK).toList());
        config.put("metrics", metrics);
        config.put("outOfScopeProbe", oos);
        config.put("cases", caseRows);
        return config;
    }

    /**
     * 执行一次真实检索（走生产同一条 VectorStore.similaritySearch 链路），并记录耗时。
     */
    private RetrievalOutcome retrieve(String query, int topK, double threshold) {
        SearchRequest request = SearchRequest.builder()
                .query(query)
                .topK(topK)
                .similarityThreshold(threshold)
                .build();

        long start = System.nanoTime();
        List<Document> docs = vectorStore.similaritySearch(request);
        long elapsed = System.nanoTime() - start;

        List<String> sections = new ArrayList<>();
        List<Map<String, Object>> detail = new ArrayList<>();
        double topScore = 0.0;
        for (int i = 0; i < docs.size(); i++) {
            Document doc = docs.get(i);
            String section = extractSection(doc.getText());
            sections.add(section);
            Double score = doc.getScore();
            if (i == 0 && score != null) {
                topScore = score;
            }
            Map<String, Object> d = new LinkedHashMap<>();
            d.put("rank", i + 1);
            d.put("section", section);
            d.put("score", score == null ? null : round(score));
            d.put("source", doc.getMetadata() == null ? null : doc.getMetadata().get("source"));
            detail.add(d);
        }
        return new RetrievalOutcome(sections, detail, topScore, elapsed);
    }

    /**
     * 从 chunk 正文提取章节标题：content 的第一行形如 "## 一、退款政策"。
     */
    private String extractSection(String content) {
        if (content == null) {
            return null;
        }
        for (String line : content.split("\n", 2)) {
            String trimmed = line.trim();
            if (trimmed.startsWith("## ")) {
                return trimmed.substring(3).trim();
            }
        }
        return null;
    }

    private JsonNode readDatasetNode() {
        try (InputStream in = new ClassPathResource(DATASET_PATH).getInputStream()) {
            return objectMapper.readTree(in);
        } catch (Exception e) {
            throw new IllegalStateException("读取评测集失败：" + e.getMessage(), e);
        }
    }

    private List<EvalCase> parseCases(JsonNode root) {
        List<EvalCase> cases = new ArrayList<>();
        JsonNode arr = root.path("cases");
        for (JsonNode n : arr) {
            List<String> expected = new ArrayList<>();
            for (JsonNode s : n.path("expectedSections")) {
                expected.add(s.asText());
            }
            cases.add(new EvalCase(
                    n.path("id").asText(),
                    n.path("query").asText(),
                    n.path("category").asText(""),
                    expected));
        }
        return cases;
    }

    private static double ratio(int part, int total) {
        return total == 0 ? 0.0 : round((double) part / total);
    }

    private static double round(double v) {
        if (Double.isNaN(v) || Double.isInfinite(v)) {
            return 0.0;
        }
        return Math.round(v * 10000.0) / 10000.0;
    }

    // ==================== 内部数据结构 ====================

    /** 一条评测用例 */
    public record EvalCase(String id, String query, String category, List<String> expectedSections) {

        /** 期望章节为空 => out_of_scope 探针，不计入 Hit Rate / MRR 分母 */
        public boolean outOfScope() {
            return expectedSections == null || expectedSections.isEmpty();
        }

        /** 检索到的 chunk 章节是否命中期望 */
        public boolean matches(String section) {
            if (section == null || expectedSections == null) {
                return false;
            }
            return expectedSections.contains(section);
        }

        public Map<String, Object> toMap() {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", id);
            m.put("query", query);
            m.put("category", category);
            m.put("expectedSections", expectedSections);
            m.put("outOfScope", outOfScope());
            return m;
        }
    }

    /** 单次检索的结果与耗时 */
    private record RetrievalOutcome(List<String> sections,
                                    List<Map<String, Object>> detail,
                                    double topScore,
                                    long latencyNs) {
    }
}
