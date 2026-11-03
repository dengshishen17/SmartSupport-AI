-- ============================================================
-- SmartSupport AI —— MySQL 业务库初始化脚本
--
-- 用途：
--   为 SmartSupport AI 项目创建业务数据库 smart_support，包含订单、退款记录、
--   售后工单三张业务表，并灌入一份可直接用于演示的最小数据集。
--
--   配套环境变量：MYSQL_PASSWORD（见 .env.example 与 application.yml）
--   执行示例：mysql -u root -p smart_support < backend/src/main/resources/db/schema.sql
--
-- 重复执行行为：
--   本脚本可安全重复执行。
--   1) 建表使用 CREATE TABLE IF NOT EXISTS —— 表已存在则跳过，不会清空已有数据；
--   2) 演示数据使用 INSERT ... ON DUPLICATE KEY UPDATE —— 遇到主键 id 或唯一键
--      order_no 冲突时，更新该行的字段值，而不是报错或插入重复行；
--   3) 因此，相同订单编号（order_no，如 10001）的演示数据在重复执行后会被
--      覆盖更新为脚本中定义的商品、金额、状态与时间；
--   4) 脚本内不包含 DROP TABLE，也不包含 DELETE FROM，不会删除库中其他数据。
--
-- 注意事项：
--   1) order_no 必须是字符串列（VARCHAR），业务含义为订单编号（如 "10001"）。
--      MyBatis Plus 依赖下划线转驼峰映射（map-underscore-to-camel-case: true），
--      列名必须严格保持小写下划线形式，否则实体字段将无法映射。
--   2) 三张表的 order_no 均建有唯一索引，因为业务层使用 selectOne 按 order_no
--      查询；MyBatis Plus 的 selectOne 在命中多行时会抛 TooManyResultsException。
--   3) 本项目不建立物理外键，三张表通过 order_no 字符串做逻辑关联，
--      由业务代码保证一致性。
--   4) 时间全部为固定值，不使用 NOW()，以保证演示数据可复现、
--      且能体现"超时未发货""运输超时"等依赖时间差的业务场景。
--   5) 数据库名与字符集在下方 CREATE DATABASE 中声明，请确保执行时使用
--      utf8mb4（表内中文数据依赖此字符集）。
--
-- 环境要求：MySQL 8.0 及以上（脚本使用 utf8mb4_0900_ai_ci 排序规则与
--            MySQL 8.0.19+ 引入的 INSERT 行别名语法）。
-- ============================================================

-- ------------------------------------------------------------
-- 1. 创建数据库
-- ------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS `smart_support`
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE `smart_support`;

-- ------------------------------------------------------------
-- 2. 订单表 orders
--    实体类：com.smartsupport.entity.Order
--    对应一个客户订单，status 取值：已下单 / 已发货 / 运输中 / 已完成
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `orders` (
    `id`           BIGINT        NOT NULL AUTO_INCREMENT COMMENT '订单 ID（主键，数据库自增）',
    `order_no`     VARCHAR(20)   NOT NULL                COMMENT '订单编号，如 10001',
    `user_id`      BIGINT        DEFAULT NULL            COMMENT '下单用户 ID（无对应用户表，仅为外部标识）',
    `product_name` VARCHAR(100)  DEFAULT NULL            COMMENT '商品名称',
    `amount`       DECIMAL(10,2) DEFAULT NULL            COMMENT '订单金额',
    `status`       VARCHAR(20)   NOT NULL                COMMENT '订单状态：已下单/已发货/运输中/已完成',
    `create_time`  DATETIME      NOT NULL                COMMENT '下单时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_order_no` (`order_no`)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci
  COMMENT = '订单表';

-- ------------------------------------------------------------
-- 3. 退款记录表 refund_record
--    实体类：com.smartsupport.entity.RefundRecord
--    order_no 逻辑关联 orders.order_no
--    refund_status 取值：审核中 / 已退款 / 已到账
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `refund_record` (
    `id`            BIGINT        NOT NULL AUTO_INCREMENT COMMENT '退款记录 ID（主键，数据库自增）',
    `order_no`      VARCHAR(20)   NOT NULL                COMMENT '关联的订单编号',
    `refund_reason` VARCHAR(255)  DEFAULT NULL            COMMENT '退款原因，如：商品质量问题',
    `refund_status` VARCHAR(20)   DEFAULT NULL            COMMENT '退款状态：审核中/已退款/已到账',
    `create_time`   DATETIME      NOT NULL                COMMENT '申请时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_refund_order_no` (`order_no`)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci
  COMMENT = '退款记录表';

-- ------------------------------------------------------------
-- 4. 售后工单表 after_sale_ticket
--    实体类：com.smartsupport.entity.AfterSaleTicket
--    order_no 逻辑关联 orders.order_no
--    problem_type 取值：商品质量问题 / 七天无理由退货 / 物流问题 / 保修 / 其他
--    status 取值：待处理 / 处理中 / 已完成
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `after_sale_ticket` (
    `id`           BIGINT         NOT NULL AUTO_INCREMENT COMMENT '工单 ID（主键，数据库自增）',
    `order_no`     VARCHAR(20)    NOT NULL                COMMENT '关联的订单编号',
    `problem_type` VARCHAR(50)    DEFAULT NULL            COMMENT '问题类型，如：商品质量问题',
    `description`  VARCHAR(1000)  DEFAULT NULL            COMMENT '问题描述',
    `solution`     VARCHAR(1000)  DEFAULT NULL            COMMENT '处理方案，如：支持退货退款',
    `status`       VARCHAR(20)    NOT NULL DEFAULT '待处理' COMMENT '工单状态：待处理/处理中/已完成',
    `create_time`  DATETIME       NOT NULL                COMMENT '创建时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_ticket_order_no` (`order_no`)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci
  COMMENT = '售后工单表';

-- ------------------------------------------------------------
-- 5. 演示数据 —— 订单（7 条）
--    10001 为主锚点：Tool Calling 的 @ToolParam 示例值即 10001，
--    保证 queryOrderByOrderNo("10001") / queryRefundByOrderNo("10001")
--    / queryTicketByOrderNo("10001") 三个工具均可返回真实数据。
--    订单状态覆盖：已下单(2) / 已发货(1) / 运输中(2) / 已完成(2)
-- ------------------------------------------------------------
INSERT INTO `orders` (`id`, `order_no`, `user_id`, `product_name`, `amount`, `status`, `create_time`) VALUES
    (1, '10001', 1001, '智能扫地机器人 X20',      2999.00, '运输中', '2026-10-20 10:15:00'),
    (2, '10002', 1001, '无线蓝牙耳机 Pro',          499.00, '已下单', '2026-10-28 09:30:00'),
    (3, '10003', 1002, '智能手表 S3',              1299.00, '已发货', '2026-10-25 14:20:00'),
    (4, '10004', 1002, '空气净化器 A1',            1899.00, '已完成', '2026-09-15 11:00:00'),
    (5, '10005', 1003, '保温杯 500ml',               89.00, '已下单', '2026-11-01 16:45:00'),
    (6, '10006', 1003, '挂耳式耳机 Air',            699.00, '运输中', '2026-10-10 08:20:00'),
    (7, '10007', 1004, '笔记本电脑 15 英寸',       7999.00, '已完成', '2026-11-01 10:05:00')
AS demo
ON DUPLICATE KEY UPDATE
    `order_no`     = demo.`order_no`,
    `user_id`      = demo.`user_id`,
    `product_name` = demo.`product_name`,
    `amount`       = demo.`amount`,
    `status`       = demo.`status`,
    `create_time`  = demo.`create_time`;

-- ------------------------------------------------------------
-- 6. 演示数据 —— 退款记录（3 条）
--    refund_status 覆盖：已到账(1) / 审核中(1) / 已退款(1)
-- ------------------------------------------------------------
INSERT INTO `refund_record` (`id`, `order_no`, `refund_reason`, `refund_status`, `create_time`) VALUES
    (1, '10001', '商品质量问题',   '已到账', '2026-10-25 09:00:00'),
    (2, '10002', '未收到货',       '审核中', '2026-10-31 10:20:00'),
    (3, '10007', '七天无理由退货', '已退款', '2026-11-02 15:30:00')
AS demo
ON DUPLICATE KEY UPDATE
    `order_no`      = demo.`order_no`,
    `refund_reason` = demo.`refund_reason`,
    `refund_status` = demo.`refund_status`,
    `create_time`   = demo.`create_time`;

-- ------------------------------------------------------------
-- 7. 演示数据 —— 售后工单（4 条）
--    status 覆盖：处理中(1) / 待处理(2) / 已完成(1)
-- ------------------------------------------------------------
INSERT INTO `after_sale_ticket` (`id`, `order_no`, `problem_type`, `description`, `solution`, `status`, `create_time`) VALUES
    (1, '10001', '商品质量问题', '扫地机器人吸力明显下降，吸口有异物无法清理', '免费维修，客服上门检测并更换滤芯', '处理中', '2026-10-26 09:30:00'),
    (2, '10002', '物流问题',     '下单一周仍未发货，订单状态一直显示已下单',   '已催仓库发货，预计今日出库并提供快递单号', '待处理', '2026-11-01 11:00:00'),
    (3, '10003', '保修',         '手表充电触点接触不良，无法正常充电',       '免费维修，更换充电底座，运费由本方承担', '已完成', '2026-10-26 14:10:00'),
    (4, '10006', '物流问题',     '快递物流已五天未更新，疑似丢件',             '联系快递核实并补发',                     '待处理', '2026-11-02 16:00:00')
AS demo
ON DUPLICATE KEY UPDATE
    `order_no`     = demo.`order_no`,
    `problem_type` = demo.`problem_type`,
    `description`  = demo.`description`,
    `solution`     = demo.`solution`,
    `status`       = demo.`status`,
    `create_time`  = demo.`create_time`;
