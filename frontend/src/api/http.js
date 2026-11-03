import axios from 'axios'

// 统一 axios 实例：超时给长一点（AI 调用比较慢），响应统一拆出 data
const http = axios.create({ baseURL: '/', timeout: 120000 })

http.interceptors.response.use(
  (res) => {
    const body = res.data
    if (body && body.code === 200) return body.data
    return Promise.reject(new Error((body && body.message) || '请求失败'))
  },
  (err) => Promise.reject(err),
)

export default http