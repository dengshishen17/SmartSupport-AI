package com.smartsupport.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 订单实体类——对应数据库中的 orders 表。
 * 每一行订单数据在 Java 代码里就是一个 Order 对象。
 *
 * @TableName("orders")：告诉 MyBatis Plus 这个类对应哪张表
 * @TableId(type = IdType.AUTO)：告诉 MyBatis Plus 主键是自增的
 */
@TableName("orders")
public class Order {

    @TableId(type = IdType.AUTO)
    private Long id;            // 订单 ID（主键，数据库自增）

    private String orderNo;     // 订单编号，如 "10001"

    private Long userId;        // 下单用户 ID

    private String productName; // 商品名称

    private BigDecimal amount;  // 订单金额（用 BigDecimal 存小数金额最准确）

    private String status;      // 订单状态：已下单/已发货/运输中/已完成

    private LocalDateTime createTime; // 下单时间

    // ========== Getter / Setter ==========
    // MyBatis Plus 把数据库查询结果转成 Java 对象时，通过 setter 方法赋值；
    // 返回 JSON 给前端时，通过 getter 方法取值。所以每个字段都要写。

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }

    public String getOrderNo() { return orderNo; }
    public void setOrderNo(String orderNo) { this.orderNo = orderNo; }

    public Long getUserId() { return userId; }
    public void setUserId(Long userId) { this.userId = userId; }

    public String getProductName() { return productName; }
    public void setProductName(String productName) { this.productName = productName; }

    public BigDecimal getAmount() { return amount; }
    public void setAmount(BigDecimal amount) { this.amount = amount; }

    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }

    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
}
