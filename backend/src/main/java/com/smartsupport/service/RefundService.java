package com.smartsupport.service;

import com.smartsupport.entity.RefundRecord;

import java.util.List;

/**
 * 退款业务接口——定义系统能对外提供哪些退款相关功能。
 */
public interface RefundService {

    /**
     * 根据订单编号查询退款记录
     * @param orderNo 订单编号，如 "10001"
     * @return 退款记录，找不到返回 null
     */
    RefundRecord getByOrderNo(String orderNo);

    /**
     * 查询所有退款记录
     */
    List<RefundRecord> listAll();
}
