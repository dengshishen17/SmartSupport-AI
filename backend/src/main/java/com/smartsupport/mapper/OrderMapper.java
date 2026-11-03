package com.smartsupport.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.smartsupport.entity.Order;
import org.apache.ibatis.annotations.Mapper;

/**
 * 订单表的 Mapper 接口——专门操作 orders 表。
 *
 * BaseMapper<Order> 已经内置了增删改查方法：
 *   insert / deleteById / updateById / selectById / selectList ...
 * 所以一般 SQL 不用自己写，MyBatis Plus 自动帮你生成。
 *
 * @Mapper：告诉 Spring "这是一个数据库操作接口，帮我管理它"
 */
@Mapper
public interface OrderMapper extends BaseMapper<Order> {
    // 目前没有额外自定义方法，BaseMapper 的通用 CRUD 已经够用。
    // 后面如果要用复杂查询（如联表、分页条件），可以在这里加方法。
}
