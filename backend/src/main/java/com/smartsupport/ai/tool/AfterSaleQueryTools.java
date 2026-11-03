package com.smartsupport.ai.tool;

import com.smartsupport.entity.AfterSaleTicket;
import com.smartsupport.entity.Order;
import com.smartsupport.entity.RefundRecord;
import com.smartsupport.service.OrderService;
import com.smartsupport.service.RefundService;
import com.smartsupport.service.TicketService;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

/**
 * AI 售后查询工具（Day 5 Tool Calling）
 *
 * 只做一件事：把现有 Service 的查询方法包装成 AI 能自动调用的"工具"。
 * 不重复实现任何业务逻辑，全部委托给现有 OrderService / RefundService / TicketService。
 * 只读查询，不新增、修改、删除任何业务数据。
 *
 * ┌──────────────────────── 权限限制说明 ────────────────────────┐
 * │ 当前项目没有登录/认证体系，无法验证"该订单是否属于当前用户"。   │
 * │ 本工具按"客服后台演示"定位实现：知道订单号即可查询。           │
 * │ 缓解措施：返回数据中刻意裁剪掉 userId，减少信息泄露面。        │
 * │ 生产环境正确做法（后续迭代）：接入登录认证后，从会话取当前     │
 * │ 用户 ID，查询到订单后校验 order.userId == 当前用户 ID，       │
 * │ 不一致则拒绝返回；绝不让用户自行传 userId 作为查询条件。       │
 * └──────────────────────────────────────────────────────────────┘
 */
@Component
public class AfterSaleQueryTools {

    private final OrderService orderService;
    private final RefundService refundService;
    private final TicketService ticketService;

    public AfterSaleQueryTools(OrderService orderService,
                               RefundService refundService,
                               TicketService ticketService) {
        this.orderService = orderService;
        this.refundService = refundService;
        this.ticketService = ticketService;
    }

    /**
     * 查订单。用户问"我的订单到哪了""订单 10001 发货了吗"时由 AI 自动调用。
     * 返回自然语言文本（模型的"食物"是文本，比 JSON 更友好），不含 userId。
     */
    @Tool(name = "queryOrderByOrderNo",
            description = "根据订单编号查询订单信息，包括商品名称、金额、订单/物流状态和下单时间。"
                    + "当用户询问订单状态、物流进度、是否发货时使用此工具。")
    public String queryOrderByOrderNo(
            @ToolParam(description = "订单编号，例如 10001") String orderNo) {
        Order order = orderService.getByOrderNo(orderNo);
        if (order == null) {
            return "未找到订单号为 " + orderNo + " 的订单，请与用户确认订单号是否输入正确。";
        }
        return String.format("订单号：%s，商品：%s，金额：%s 元，订单状态：%s，下单时间：%s",
                order.getOrderNo(), order.getProductName(), order.getAmount(),
                order.getStatus(), order.getCreateTime());
    }

    /**
     * 查退款。用户问"我的退款到账了吗""退款审核通过了吗"时由 AI 自动调用。
     */
    @Tool(name = "queryRefundByOrderNo",
            description = "根据订单编号查询退款记录，包括退款原因、退款状态（审核中/已退款/已到账）和申请时间。"
                    + "当用户询问退款进度、退款是否到账时使用此工具。")
    public String queryRefundByOrderNo(
            @ToolParam(description = "订单编号，例如 10001") String orderNo) {
        RefundRecord refund = refundService.getByOrderNo(orderNo);
        if (refund == null) {
            return "未找到订单号为 " + orderNo + " 的退款记录，该订单可能尚未申请退款。";
        }
        return String.format("订单号：%s，退款原因：%s，退款状态：%s，申请时间：%s",
                refund.getOrderNo(), refund.getRefundReason(),
                refund.getRefundStatus(), refund.getCreateTime());
    }

    /**
     * 查售后工单。用户问"我的售后申请处理得怎么样了"时由 AI 自动调用。
     */
    @Tool(name = "queryTicketByOrderNo",
            description = "根据订单编号查询售后工单，包括问题类型、问题描述、处理方案和工单状态（待处理/处理中/已完成）。"
                    + "当用户询问售后申请、投诉、维修工单的处理进度时使用此工具。")
    public String queryTicketByOrderNo(
            @ToolParam(description = "订单编号，例如 10001") String orderNo) {
        AfterSaleTicket ticket = ticketService.getByOrderNo(orderNo);
        if (ticket == null) {
            return "未找到订单号为 " + orderNo + " 的售后工单，该订单可能尚未提交售后申请。";
        }
        return String.format("订单号：%s，问题类型：%s，问题描述：%s，处理方案：%s，工单状态：%s，创建时间：%s",
                ticket.getOrderNo(), ticket.getProblemType(), ticket.getDescription(),
                ticket.getSolution(), ticket.getStatus(), ticket.getCreateTime());
    }
}
