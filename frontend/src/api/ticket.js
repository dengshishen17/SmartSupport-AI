import http from './http'

/**
 * 售后工单接口，对应后端 TicketController（/api/ticket）
 */

/**
 * 工单列表
 * @returns {Promise<Array<{
 *   id:number, orderNo:string, problemType:string, description:string,
 *   solution:string, status:string, createTime:string
 * }>>}
 */
export function listTickets() {
  return http.get('/api/ticket/list')
}

/**
 * 创建工单（status 留空，后端默认"待处理"）
 * @param {{orderNo:string, problemType:string, description:string, solution:string}} data
 */
export function createTicket(data) {
  return http.post('/api/ticket', data)
}
