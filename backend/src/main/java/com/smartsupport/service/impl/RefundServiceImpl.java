package com.smartsupport.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.smartsupport.entity.RefundRecord;
import com.smartsupport.mapper.RefundRecordMapper;
import com.smartsupport.service.RefundService;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 退款业务实现类——真正干活的代码。
 * 原理同 OrderServiceImpl。
 */
@Service
public class RefundServiceImpl implements RefundService {

    private final RefundRecordMapper refundRecordMapper;

    public RefundServiceImpl(RefundRecordMapper refundRecordMapper) {
        this.refundRecordMapper = refundRecordMapper;
    }

    @Override
    public RefundRecord getByOrderNo(String orderNo) {
        // 等价于 SQL：SELECT * FROM refund_record WHERE order_no = 'xxx' LIMIT 1
        return refundRecordMapper.selectOne(
                new LambdaQueryWrapper<RefundRecord>()
                        .eq(RefundRecord::getOrderNo, orderNo)
        );
    }

    @Override
    public List<RefundRecord> listAll() {
        // 等价于 SQL：SELECT * FROM refund_record
        return refundRecordMapper.selectList(null);
    }
}
