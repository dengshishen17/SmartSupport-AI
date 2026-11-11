"""MCP Server：把三个订单查询工具按 MCP 协议暴露，Dify/Claude Desktop 可直接接入。
运行：python -m app.mcp_server  （stdio 模式）
"""
from mcp.server.mcpserver import MCPServer
from . import tools as biz

mcp = MCPServer("smartsupport-tools")


@mcp.tool(description="根据订单编号查询订单信息（商品/金额/状态/下单时间）。")
def queryOrderByOrderNo(orderNo: str) -> str:
    return biz.query_order_text(orderNo)


@mcp.tool(description="根据订单编号查询退款记录（原因/状态/申请时间）。")
def queryRefundByOrderNo(orderNo: str) -> str:
    return biz.query_refund_text(orderNo)


@mcp.tool(description="根据订单编号查询售后工单（问题类型/描述/方案/状态）。")
def queryTicketByOrderNo(orderNo: str) -> str:
    return biz.query_ticket_text(orderNo)


@mcp.tool(description="根据订单编号测算保修期（在保/过保）。")
def queryWarrantyByOrderNo(orderNo: str) -> str:
    return biz.query_warranty_text(orderNo)


if __name__ == "__main__":
    mcp.run()
