package com.smartsupport.eval;

import com.smartsupport.common.Result;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * RAG 检索评测接口（只读、独立于生产问答链路）。
 *
 * 与生产接口的关系：
 *   - 生产的 /ai/knowledge/chat 把 topK=5、similarityThreshold=0.0 写死；
 *   - 本接口只是把这两个参数开放成可扫描的参数矩阵，检索本身仍然走同一个
 *     PgVectorStore Bean、同一张 vector_store 表、同一套 embedding 模型与距离度量，
 *     所以扫出来的指标反映的就是生产检索链路的真实表现。
 *
 * 边界（明确不做）：
 *   - 不做任何答案质量评分（只评「有没有检索到正确的知识章节」）
 *   - 不删除、不重置、不写入知识库（对 vector_store 只有 SELECT）
 *   - 不修改生产问答逻辑
 */
@RestController
@RequestMapping("/eval/rag")
public class RagEvalController {

    private final RagEvalService ragEvalService;

    public RagEvalController(RagEvalService ragEvalService) {
        this.ragEvalService = ragEvalService;
    }

    /**
     * 知识库现状（只读）。
     * GET /eval/rag/knowledge-base
     */
    @GetMapping("/knowledge-base")
    public Result<Map<String, Object>> knowledgeBase() {
        return Result.ok(ragEvalService.knowledgeBaseInfo());
    }

    /**
     * 评测集内容。
     * GET /eval/rag/dataset
     */
    @GetMapping("/dataset")
    public Result<Map<String, Object>> dataset() {
        return Result.ok(ragEvalService.loadDataset());
    }

    /**
     * 执行检索评测。
     * POST /eval/rag/run?topKs=1,3,5,8&thresholds=0.0,0.5,0.7
     *
     * 参数均可省略，默认扫描 topK={1,3,5,8} × threshold={0.0,0.5,0.7}。
     */
    @PostMapping("/run")
    public Result<Map<String, Object>> run(
            @RequestParam(required = false) String topKs,
            @RequestParam(required = false) String thresholds) {
        try {
            List<Integer> parsedTopKs = parseIntegers(topKs, List.of(1, 3, 5, 8));
            List<Double> parsedThresholds = parseDoubles(thresholds, List.of(0.0, 0.5, 0.7));
            return Result.ok(ragEvalService.runRetrievalEval(parsedTopKs, parsedThresholds));
        } catch (Exception e) {
            return Result.fail("评测执行失败：" + e.getMessage());
        }
    }

    private List<Integer> parseIntegers(String raw, List<Integer> defaults) {
        if (raw == null || raw.isBlank()) {
            return defaults;
        }
        try {
            return Arrays.stream(raw.split(","))
                    .map(String::trim)
                    .filter(s -> !s.isEmpty())
                    .map(Integer::parseInt)
                    .filter(v -> v > 0)
                    .distinct()
                    .toList();
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException("topKs 必须是逗号分隔的正整数");
        }
    }

    private List<Double> parseDoubles(String raw, List<Double> defaults) {
        if (raw == null || raw.isBlank()) {
            return defaults;
        }
        try {
            return Arrays.stream(raw.split(","))
                    .map(String::trim)
                    .filter(s -> !s.isEmpty())
                    .map(Double::parseDouble)
                    .filter(v -> v >= 0.0 && v <= 1.0)
                    .distinct()
                    .toList();
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException("thresholds 必须是逗号分隔的 0~1 之间的小数");
        }
    }
}
