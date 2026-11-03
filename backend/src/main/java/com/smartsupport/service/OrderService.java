package com.smartsupport.service;

import com.smartsupport.entity.Order;

import java.util.List;

/**
 * 订单业务接口——定义"系统能对外提供哪些订单相关功能"。
 * 面向接口编程，好处是：调用方（Controller）只依赖接口，不关心具体实现，
 * 将来换一种实现方式，调用方代码一行都不用改。
 */
public interface OrderService {

    /**
     * 根据订单编号查询订单详情
     * @param orderNo 订单编号，如 "10001"
     * @return 订单对象，找不到返回 null
     */
    Order getByOrderNo(String orderNo);

    /**
     * 查询所有订单列表
     */
    List<Order> listAll();

    /**
     * 新增一个订单
     * @param order 订单对象
     * @return true=成功，false=失败
     */
    boolean add(Order order);
}
