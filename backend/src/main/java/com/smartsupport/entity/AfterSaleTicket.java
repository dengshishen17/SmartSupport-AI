package com.smartsupport.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import java.time.LocalDateTime;

/**
 * 售后工单实体类——对应数据库中的 after_sale_ticket 表。
 * 客户提出售后需求时，客服创建一张工单来跟踪处理。
 */
@TableName("after_sale_ticket")
public class AfterSaleTicket {

    @TableId(type = IdType.AUTO)
    private Long id;            // 工单 ID（主键）

    private String orderNo;     // 关联的订单编号

    private String problemType; // 问题类型（如：商品质量问题）

    private String description; // 问题描述

    private String solution;    // 处理方案（如：支持退货退款）

    private String status;      // 工单状态：待处理/处理中/已完成

    private LocalDateTime createTime; // 创建时间

    // ========== Getter / Setter ==========

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }

    public String getOrderNo() { return orderNo; }
    public void setOrderNo(String orderNo) { this.orderNo = orderNo; }

    public String getProblemType() { return problemType; }
    public void setProblemType(String problemType) { this.problemType = problemType; }

    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }

    public String getSolution() { return solution; }
    public void setSolution(String solution) { this.solution = solution; }

    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }

    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
}
