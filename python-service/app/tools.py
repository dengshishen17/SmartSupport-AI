"""业务工具：LangChain Tool 封装 + 纯函数版本（供 DeepSeek 原生 tool_calls 与 MCP 复用）。
安全口径与 Java 版一致：返回裁掉 userId；生产应从登录态取 userId 校验，绝不让模型传 userId。
"""
from langchain_core.tools import tool
from . import db


def _warranty_months(product_name: str) -> int | None:
    """按《售后政策》§4.1 保修期表：商品名关键词 → 保修月数；食品类不支持保修返回 None。
    后续可替换为商品类目表查询。"""
    name = (product_name or "")
    if any(k in name for k in ("耳机", "手表", "电脑", "笔记本", "手机", "数码")):
        return 12  # 电子数码类 12 个月
    if any(k in name for k in ("扫地机器人", "空气净化器", "家电", "冰箱", "洗衣机", "空调")):
        return 24  # 家电类 24 个月
    if any(k in name for k in ("保温杯", "杯", "配饰", "日用品")):
        return 3  # 配饰/日用品类 3 个月
    if any(k in name for k in ("食品", "零食", "消耗品")):
        return None
    return 12  # 默认按电子数码口径


def query_order_text(order_no: str) -> str:
    try:
        o = db.get_order(order_no)
    except Exception as e:
        return f"订单库暂时不可用（{e}），请稍后重试或转人工客服。"
    if not o:
        return f"未找到订单号为 {order_no} 的订单，请与用户确认订单号是否输入正确。"
    return f"订单号：{o['order_no']}，商品：{o.get('product_name')}，金额：{o.get('amount')} 元，订单状态：{o.get('status')}，下单时间：{o.get('create_time')}"


def query_refund_text(order_no: str) -> str:
    try:
        r = db.get_refund(order_no)
    except Exception as e:
        return f"退款记录库暂时不可用（{e}），请稍后重试或转人工客服。"
    if not r:
        return f"未找到订单号为 {order_no} 的退款记录，该订单可能尚未申请退款。"
    return f"订单号：{r['order_no']}，退款原因：{r.get('refund_reason')}，退款状态：{r.get('refund_status')}，申请时间：{r.get('create_time')}"


def query_ticket_text(order_no: str) -> str:
    try:
        t = db.get_ticket(order_no)
    except Exception as e:
        return f"工单库暂时不可用（{e}），请稍后重试或转人工客服。"
    if not t:
        return f"未找到订单号为 {order_no} 的售后工单，该订单可能尚未提交售后申请。"
    return (f"订单号：{t['order_no']}，问题类型：{t.get('problem_type')}，问题描述：{t.get('description')}，"
            f"处理方案：{t.get('solution')}，工单状态：{t.get('status')}，创建时间：{t.get('create_time')}")


@tool("queryOrderByOrderNo", description="根据订单编号查询订单信息，包括商品名称、金额、订单/物流状态和下单时间。当用户询问订单状态、物流进度、是否发货时使用此工具。")
def query_order_tool(orderNo: str) -> str:
    return query_order_text(orderNo)


@tool("queryRefundByOrderNo", description="根据订单编号查询退款记录，包括退款原因、退款状态（审核中/已退款/已到账）和申请时间。当用户询问退款进度、退款是否到账时使用此工具。")
def query_refund_tool(orderNo: str) -> str:
    return query_refund_text(orderNo)


@tool("queryTicketByOrderNo", description="根据订单编号查询售后工单，包括问题类型、问题描述、处理方案和工单状态（待处理/处理中/已完成）。当用户询问售后申请、投诉、维修工单的处理进度时使用此工具。")
def query_ticket_tool(orderNo: str) -> str:
    return query_ticket_text(orderNo)


def query_warranty_text(order_no: str) -> str:
    """保修测算：查订单商品+下单时间，按保修期表推算是否在保。演示用下单时间近似签收时间。"""
    import datetime
    try:
        o = db.get_order(order_no)
    except Exception as e:
        return f"订单库暂时不可用（{e}），请稍后重试或转人工客服。"
    if not o:
        return f"未找到订单号为 {order_no} 的订单，无法核实保修期。"
    months = _warranty_months(str(o.get("product_name")))
    if months is None:
        return f"订单号：{order_no}，商品：{o.get('product_name')}属于食品/消耗品类，按政策不支持保修。"
    ct = o.get("create_time")
    try:
        buy = ct if hasattr(ct, "year") else datetime.datetime.fromisoformat(str(ct))
        expiry = buy + datetime.timedelta(days=30 * months)
        left = (expiry - datetime.datetime.now()).days
        status = "在保" if left > 0 else "已过保"
        return (f"订单号：{order_no}，商品：{o.get('product_name')}，保修期 {months} 个月，"
                f"购买时间 {buy:%Y-%m-%d}，{status}（约{'剩余' if left > 0 else '超期'}{abs(left)}天）。"
                f"在保非人为故障可免费维修，来回运费由本方承担。")
    except Exception:
        return f"订单号：{order_no}，商品：{o.get('product_name')}，保修期 {months} 个月（购买时间解析失败，仅供参考）。"


@tool("queryWarrantyByOrderNo", description="根据订单编号测算保修期：查订单商品与购买时间，按保修期表推算在保/过保。当用户问保修多久、能不能免费修时使用。")
def query_warranty_tool(orderNo: str) -> str:
    return query_warranty_text(orderNo)


TOOLS = [query_order_tool, query_refund_tool, query_ticket_tool, query_warranty_tool]

# OpenAI/DeepSeek 原生 function-calling schema（供 openai 客户端直调）
OPENAI_TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "queryOrderByOrderNo",
     "description": "根据订单编号查询订单信息，包括商品名称、金额、订单/物流状态和下单时间。",
     "parameters": {"type": "object", "properties": {"orderNo": {"type": "string", "description": "订单编号，例如 10001"}}, "required": ["orderNo"]}}},
    {"type": "function", "function": {"name": "queryRefundByOrderNo",
     "description": "根据订单编号查询退款记录，包括退款原因、退款状态和申请时间。",
     "parameters": {"type": "object", "properties": {"orderNo": {"type": "string", "description": "订单编号，例如 10001"}}, "required": ["orderNo"]}}},
    {"type": "function", "function": {"name": "queryTicketByOrderNo",
     "description": "根据订单编号查询售后工单，包括问题类型、问题描述、处理方案和工单状态。",
     "parameters": {"type": "object", "properties": {"orderNo": {"type": "string", "description": "订单编号，例如 10001"}}, "required": ["orderNo"]}}},
    {"type": "function", "function": {"name": "queryWarrantyByOrderNo",
     "description": "根据订单编号测算保修期（在保/过保），含商品类别与剩余天数。",
     "parameters": {"type": "object", "properties": {"orderNo": {"type": "string", "description": "订单编号，例如 10001"}}, "required": ["orderNo"]}}},
]

DISPATCH = {"queryOrderByOrderNo": query_order_text,
            "queryRefundByOrderNo": query_refund_text,
            "queryTicketByOrderNo": query_ticket_text,
            "queryWarrantyByOrderNo": query_warranty_text}
