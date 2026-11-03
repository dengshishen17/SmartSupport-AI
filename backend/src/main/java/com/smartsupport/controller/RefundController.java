package com.smartsupport.controller;

import com.smartsupport.common.Result;
import com.smartsupport.entity.RefundRecord;
import com.smartsupport.service.RefundService;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 退款接口控制器——提供退款相关的 REST 接口。
 */
@RestController
@RequestMapping("/api/refund")
public class RefundController {

    private final RefundService refundService;

    public RefundController(RefundService refundService) {
        this.refundService = refundService;
    }

    /**
     * 查询所有退款记录
     * GET /api/refund/list
     */
    @GetMapping("/list")
    public Result<List<RefundRecord>> list() {
        return Result.ok(refundService.listAll());
    }

    /**
     * 根据订单编号查询退款记录
     * GET /api/refund/10001
     */
    @GetMapping("/{orderNo}")
    public Result<RefundRecord> getByOrderNo(@PathVariable String orderNo) {
        RefundRecord record = refundService.getByOrderNo(orderNo);
        if (record == null) {
            return Result.fail("未找到退款记录：" + orderNo);
        }
        return Result.ok(record);
    }
}
