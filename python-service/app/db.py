"""MySQL 业务查询：与 Java 版 OrderService/RefundService/TicketService 同一口径，只读。"""
import pymysql
from . import config

_conn_kwargs = dict(
    host=config.MYSQL_HOST, port=config.MYSQL_PORT, user=config.MYSQL_USER,
    password=config.MYSQL_PASSWORD, database=config.MYSQL_DB, charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor, autocommit=True, connect_timeout=3,
)


def _one(sql: str, order_no: str):
    conn = pymysql.connect(**_conn_kwargs)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (order_no,))
            return cur.fetchone()
    finally:
        conn.close()


def get_order(order_no: str):
    return _one("SELECT order_no, product_name, amount, status, create_time FROM orders WHERE order_no=%s", order_no)


def get_refund(order_no: str):
    return _one("SELECT order_no, refund_reason, refund_status, create_time FROM refund_record WHERE order_no=%s", order_no)


def get_ticket(order_no: str):
    return _one("SELECT order_no, problem_type, description, solution, status, create_time FROM after_sale_ticket WHERE order_no=%s", order_no)
