package com.smartsupport.controller;

import com.smartsupport.common.Result;
import com.smartsupport.entity.Order;
import com.smartsupport.service.OrderService;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 订单接口控制器——接收前端请求，调用业务层处理。
 * @RestController：告诉 Spring 这是一个接口类，返回值直接变成 JSON
 * @RequestMapping("/api/order")：这个类的所有接口路径都以 /api/order 开头
 */
@RestController
@RequestMapping("/api/order")
public class OrderController {

    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    /**
     * 查询所有订单
     * GET /api/order/list
     */
    @GetMapping("/list")
    public Result<List<Order>> list() {
        return Result.ok(orderService.listAll());
    }

    /**
     * 根据订单编号查询订单详情
     * GET /api/order/10001
     */
    @GetMapping("/{orderNo}")
    public Result<Order> getByOrderNo(@PathVariable String orderNo) {
        Order order = orderService.getByOrderNo(orderNo);
        if (order == null) {
            return Result.fail("未找到订单：" + orderNo);
        }
        return Result.ok(order);
    }

    /**
     * 新增订单
     * POST /api/order
     * 前端传 JSON 格式的订单数据
     */
    @PostMapping
    public Result<?> add(@RequestBody Order order) {
        boolean success = orderService.add(order);
        return success ? Result.ok("订单创建成功") : Result.fail("订单创建失败");
    }
}
