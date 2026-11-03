import http from './http'

/**
 * 知识库管理接口
 * 对应后端 AiKnowledgeController
 */

/**
 * 上传 md/txt 文件并导入向量库
 * @param {File} file 用户选择的文件
 * @returns {Promise<{fileName:string, imported:number}>}
 */
export function uploadKnowledge(file) {
  const formData = new FormData()
  formData.append('file', file)
  return http.post('/ai/knowledge/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/**
 * 已导入知识文件列表
 * @returns {Promise<Array<{source:string, chunks:number}>>}
 */
export function listKnowledgeFiles() {
  return http.get('/ai/knowledge/files')
}

/**
 * 向量检索测试：返回最相似的知识段落
 * @param {string} query 测试问题
 * @returns {Promise<Array<{content:string, score:number, metadata:object}>>}
 */
export function searchKnowledge(query) {
  return http.get('/ai/knowledge/search', { params: { query } })
}
