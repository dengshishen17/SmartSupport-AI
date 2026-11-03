package com.smartsupport.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.smartsupport.entity.AfterSaleTicket;
import org.apache.ibatis.annotations.Mapper;

/**
 * 售后工单表的 Mapper 接口——专门操作 after_sale_ticket 表。
 * 原理同 OrderMapper，继承 BaseMapper 就自动拥有增删改查。
 */
@Mapper
public interface AfterSaleTicketMapper extends BaseMapper<AfterSaleTicket> {
}
