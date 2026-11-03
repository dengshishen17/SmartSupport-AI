package com.smartsupport.controller;

import com.smartsupport.common.Result;
import com.smartsupport.entity.AfterSaleTicket;
import com.smartsupport.service.TicketService;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 售后工单接口控制器——提供工单相关的 REST 接口。
 */
@RestController
@RequestMapping("/api/ticket")
public class TicketController {

    private final TicketService ticketService;

    public TicketController(TicketService ticketService) {
        this.ticketService = ticketService;
    }

    /**
     * 查询所有工单
     * GET /api/ticket/list
     */
    @GetMapping("/list")
    public Result<List<AfterSaleTicket>> list() {
        return Result.ok(ticketService.listAll());
    }

    /**
     * 根据订单编号查询工单
     * GET /api/ticket/10001
     */
    @GetMapping("/{orderNo}")
    public Result<AfterSaleTicket> getByOrderNo(@PathVariable String orderNo) {
        AfterSaleTicket ticket = ticketService.getByOrderNo(orderNo);
        if (ticket == null) {
            return Result.fail("未找到工单：" + orderNo);
        }
        return Result.ok(ticket);
    }

    /**
     * 创建工单
     * POST /api/ticket
     */
    @PostMapping
    public Result<?> create(@RequestBody AfterSaleTicket ticket) {
        boolean success = ticketService.create(ticket);
        return success ? Result.ok("工单创建成功") : Result.fail("工单创建失败");
    }
}
