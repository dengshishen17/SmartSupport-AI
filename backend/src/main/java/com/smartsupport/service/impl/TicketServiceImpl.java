package com.smartsupport.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.smartsupport.entity.AfterSaleTicket;
import com.smartsupport.mapper.AfterSaleTicketMapper;
import com.smartsupport.service.TicketService;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 售后工单业务实现类。
 * 原理同 OrderServiceImpl。
 */
@Service
public class TicketServiceImpl implements TicketService {

    private final AfterSaleTicketMapper afterSaleTicketMapper;

    public TicketServiceImpl(AfterSaleTicketMapper afterSaleTicketMapper) {
        this.afterSaleTicketMapper = afterSaleTicketMapper;
    }

    @Override
    public AfterSaleTicket getByOrderNo(String orderNo) {
        return afterSaleTicketMapper.selectOne(
                new LambdaQueryWrapper<AfterSaleTicket>()
                        .eq(AfterSaleTicket::getOrderNo, orderNo)
        );
    }

    @Override
    public List<AfterSaleTicket> listAll() {
        return afterSaleTicketMapper.selectList(null);
    }

    @Override
    public boolean create(AfterSaleTicket ticket) {
        // 新创建的工单默认状态设为"待处理"
        if (ticket.getStatus() == null || ticket.getStatus().isEmpty()) {
            ticket.setStatus("待处理");
        }
        return afterSaleTicketMapper.insert(ticket) > 0;
    }
}
