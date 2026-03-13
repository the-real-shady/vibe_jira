import { useEffect, useRef, useCallback } from 'react'
import { wsUrl } from '../api'

type Handler = (event: { type: string; data: unknown }) => void

export function useWebSocket(slug: string, onMessage: Handler) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  const connect = useCallback(() => {
    const ws = new WebSocket(wsUrl(slug))
    wsRef.current = ws

    ws.onmessage = (e) => {
      try {
        const payload = JSON.parse(e.data)
        onMessageRef.current(payload)
      } catch {
        // ignore malformed frames
      }
    }

    ws.onclose = () => {
      reconnectTimer.current = setTimeout(connect, 3000)
    }

    ws.onerror = () => ws.close()

    const pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping')
    }, 30_000)

    ws.addEventListener('close', () => clearInterval(pingInterval))
  }, [slug])

  useEffect(() => {
    connect()
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])
}
