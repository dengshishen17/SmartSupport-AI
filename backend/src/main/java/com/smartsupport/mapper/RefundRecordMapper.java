package com.smartsupport.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.smartsupport.entity.RefundRecord;
import org.apache.ibatis.annotations.Mapper;

/**
 * 退款记录表的 Mapper 接口——专门操作 refund_record 表。
 * 原理同 OrderMapper，继承 BaseMapper 就自动拥有增删改查。
 */
@Mapper
public interface RefundRecordMapper extends BaseMapper<RefundRecord> {
}
