package com.smartsupport.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.smartsupport.entity.Order;
import com.smartsupport.mapper.OrderMapper;
import com.smartsupport.service.OrderService;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 订单业务实现类——真正干活的代码。
 *
 * @Service：告诉 Spring "这是一个业务类，请帮我创建并管理它的实例"，
 *           同时也会被自动扫描注册（启动类上的 @ComponentScan 起作用）。
 *
 * 为什么用 LambdaQueryWrapper？
 *   MyBatis Plus 提供的条件构造器，用 Java 代码写查询条件，而不是手写 SQL 字符串。
 *   好处：写错字段名编译器直接报错；IDE 有代码提示；不怕 SQL 注入。
 */
@Service
public class OrderServiceImpl implements OrderService {

    // 注入 Mapper：Mapper 由 MyBatis Plus 生成代理对象，Spring 容器管理
    private final OrderMapper orderMapper;

    // 构造器注入：Spring 自动把容器中的 OrderMapper 传进来
    public OrderServiceImpl(OrderMapper orderMapper) {
        this.orderMapper = orderMapper;
    }

    @Override
    public Order getByOrderNo(String orderNo) {
        // LambdaQueryWrapper：写条件就像写 Java 代码
        // 下面这行等价于 SQL：SELECT * FROM orders WHERE order_no = '10001' LIMIT 1
        return orderMapper.selectOne(
                new LambdaQueryWrapper<Order>()
                        .eq(Order::getOrderNo, orderNo)
        );
    }

    @Override
    public List<Order> listAll() {
        // 等价于 SQL：SELECT * FROM orders
        return orderMapper.selectList(null);
    }

    @Override
    public boolean add(Order order) {
        // 等价于 SQL：INSERT INTO orders (order_no, user_id, ...) VALUES (...)
        // insert 返回受影响的行数，1 表示成功，0 表示失败
        return orderMapper.insert(order) > 0;
    }
}
