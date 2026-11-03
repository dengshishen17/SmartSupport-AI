import http from './http'

// 发送聊天消息；sessionId 可选，传入同一个值即为连续对话
export function sendChat(message, sessionId) {
  return http.post('/ai/chat', { message, sessionId: sessionId || undefined })
}

/**
 * 流式聊天：fetch POST /ai/chat/stream，手动解析 SSE（text/event-stream）
 *
 * 后端 SseEmitter 推送格式：
 *   data: {"type":"content","content":"增量文本"}\n\n
 *   data: {"type":"done","sessionId":"会话ID"}\n\n
 *   data: {"type":"error","code":"LLM_ERROR","message":"错误信息"}\n\n
 *
 * @param {string} message 用户输入
 * @param {string} sessionId 会话ID（可选）
 * @param {Object} callbacks 回调
 * @param {(delta: string) => void} callbacks.onContent 收到增量文本
 * @param {(sessionId: string) => void} callbacks.onDone 流结束
 * @param {(message: string) => void} callbacks.onError 出错
 */
export async function chatStream(message, sessionId, { onContent, onDone, onError }) {
  const resp = await fetch('/ai/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, sessionId: sessionId || undefined }),
  })

  if (!resp.ok) {
    onError?.(`HTTP ${resp.status}`)
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      // 追加到缓冲区，按 \n\n 切分事件（SSE 事件以空行分隔）
      buffer += decoder.decode(value, { stream: true })
      const events = buffer.split('\n\n')
      // 最后一段可能是不完整的半包，留到下一轮
      buffer = events.pop()

      for (const raw of events) {
        // 每行可能是 "data: {...}"，取首行 data 即可
        const line = raw.split('\n').find((l) => l.startsWith('data:'))
        if (!line) continue
        const jsonStr = line.slice(5).trim() // 去掉 "data:" 前缀
        if (!jsonStr) continue

        let evt
        try {
          evt = JSON.parse(jsonStr)
        } catch {
          continue // 非 JSON 行跳过
        }

        if (evt.type === 'content') {
          onContent?.(evt.content || '')
        } else if (evt.type === 'done') {
          onDone?.(evt.sessionId)
        } else if (evt.type === 'error') {
          onError?.(evt.message || '未知错误')
        }
      }
    }
  } catch (e) {
    onError?.(e.message || '网络异常')
  } finally {
    reader.releaseLock()
  }
}

/**
 * 知识库流式问答：POST /ai/knowledge/chat/stream
 *
 * 与 chatStream 的区别：入参字段是 question；事件多两种：
 *   data: {"type":"reference","rag":true,"sources":["售后政策演示数据.md"]}
 *   data: {"type":"tool","stage":"start","toolName":"queryOrderByOrderNo","args":{"orderNo":"10001"}}
 *   data: {"type":"tool","stage":"result","toolName":"queryOrderByOrderNo","result":"订单号：..."}
 *
 * @param {(rag:boolean, sources:string[]) => void} [callbacks.onReference] 检索完成
 * @param {(stage:string, toolName:string, payload:object) => void} [callbacks.onTool]
 *        stage='start' 时 payload=args；stage='result' 时 payload 为 {result}
 */
export async function knowledgeChatStream(question, sessionId, {
  onContent, onDone, onError, onReference, onTool,
}) {
  const resp = await fetch('/ai/knowledge/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, sessionId: sessionId || undefined }),
  })

  if (!resp.ok) {
    onError?.(`HTTP ${resp.status}`)
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const events = buffer.split('\n\n')
      buffer = events.pop()

      for (const raw of events) {
        const line = raw.split('\n').find((l) => l.startsWith('data:'))
        if (!line) continue
        const jsonStr = line.slice(5).trim()
        if (!jsonStr) continue

        let evt
        try {
          evt = JSON.parse(jsonStr)
        } catch {
          continue
        }

        if (evt.type === 'content') {
          onContent?.(evt.content || '')
        } else if (evt.type === 'done') {
          onDone?.(evt.sessionId)
        } else if (evt.type === 'error') {
          onError?.(evt.message || '未知错误')
        } else if (evt.type === 'reference') {
          onReference?.(evt.rag !== false, evt.sources || [])
        } else if (evt.type === 'tool') {
          if (evt.stage === 'start') {
            onTool?.('start', evt.toolName, evt.args || {})
          } else if (evt.stage === 'result') {
            onTool?.('result', evt.toolName, { result: evt.result || '' })
          }
        }
      }
    }
  } catch (e) {
    onError?.(e.message || '网络异常')
  } finally {
    reader.releaseLock()
  }
}