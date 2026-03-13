import { useState, useCallback } from 'react'
import { Message, getThread } from '../api'

export function useThread(slug: string) {
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (tag?: string) => {
    setLoading(true)
    try {
      const data = await getThread(slug, undefined, tag, 100)
      setMessages(data)
    } finally {
      setLoading(false)
    }
  }, [slug])

  const addMessage = useCallback((msg: Message) => {
    setMessages(prev => {
      if (prev.some(m => m.id === msg.id)) return prev
      return [...prev, msg]
    })
  }, [])

  const updateMessage = useCallback((msg: Message) => {
    setMessages(prev => prev.map(m => m.id === msg.id ? msg : m))
  }, [])

  return { messages, loading, load, addMessage, updateMessage }
}
