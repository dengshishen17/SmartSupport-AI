package com.smartsupport.service;

import com.smartsupport.entity.AfterSaleTicket;

import java.util.List;

/**
 * 售后工单业务接口——定义系统能对外提供哪些工单相关功能。
 */
public interface TicketService {

    /**
     * 根据订单编号查询工单
     * @param orderNo 订单编号
     * @return 工单对象，找不到返回 null
     */
    AfterSaleTicket getByOrderNo(String orderNo);

    /**
     * 查询所有工单
     */
    List<AfterSaleTicket> listAll();

    /**
     * 创建新工单
     * @param ticket 工单对象
     * @return true=成功，false=失败
     */
    boolean create(AfterSaleTicket ticket);
}
