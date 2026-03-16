import { useState, useRef, useEffect } from 'react'
import { Agent } from '../api'

interface Props {
  onSend: (content: string) => Promise<void>
  agents?: Agent[]
}

export default function InstructionInput({ onSend, agents = [] }: Props) {
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [mentionQuery, setMentionQuery] = useState<string | null>(null)
  const [mentionStart, setMentionStart] = useState(0)
  const [selectedIdx, setSelectedIdx] = useState(0)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Agents that match the current @query
  const suggestions = mentionQuery !== null
    ? agents.filter(a => a.id.toLowerCase().startsWith(mentionQuery.toLowerCase()))
    : []

  // Detect @mention in textarea as the user types
  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value
    setText(val)

    const cursor = e.target.selectionStart ?? val.length
    // Walk back from cursor to find an @ that isn't preceded by a word char
    const textBefore = val.slice(0, cursor)
    const match = textBefore.match(/@(\w*)$/)
    if (match) {
      setMentionQuery(match[1])
      setMentionStart(cursor - match[0].length)
      setSelectedIdx(0)
    } else {
      setMentionQuery(null)
    }
  }

  const insertMention = (agentId: string) => {
    const cursor = textareaRef.current?.selectionStart ?? text.length
    const before = text.slice(0, mentionStart)
    const after  = text.slice(cursor)
    const newText = `${before}@${agentId} ${after}`
    setText(newText)
    setMentionQuery(null)
    // Restore focus and move cursor after the inserted mention
    requestAnimationFrame(() => {
      const ta = textareaRef.current
      if (!ta) return
      ta.focus()
      const pos = before.length + agentId.length + 2 // '@' + name + ' '
      ta.setSelectionRange(pos, pos)
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mentionQuery !== null && suggestions.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedIdx(i => (i + 1) % suggestions.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedIdx(i => (i - 1 + suggestions.length) % suggestions.length)
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        insertMention(suggestions[selectedIdx].id)
        return
      }
      if (e.key === 'Escape') {
        setMentionQuery(null)
        return
      }
    }

    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      handleSubmit(e as unknown as React.FormEvent)
    }
  }

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setMentionQuery(null)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const content = text.trim()
    if (!content) return
    setSending(true)
    try {
      await onSend(content)
      setText('')
      setMentionQuery(null)
    } finally {
      setSending(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="border-t border-gray-800 p-4 bg-gray-950">
      <div className="relative flex gap-3 items-end">
        {/* @mention dropdown */}
        {mentionQuery !== null && suggestions.length > 0 && (
          <div
            ref={dropdownRef}
            className="absolute bottom-full mb-1 left-0 bg-gray-800 border border-gray-700 rounded-lg shadow-lg overflow-hidden z-10 min-w-[160px]"
          >
            {suggestions.map((a, i) => (
              <button
                key={a.id}
                type="button"
                onMouseDown={e => { e.preventDefault(); insertMention(a.id) }}
                className={`w-full text-left px-3 py-1.5 text-sm flex items-center gap-2 transition-colors ${
                  i === selectedIdx
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-200 hover:bg-gray-700'
                }`}
              >
                <span className="w-1.5 h-1.5 rounded-full bg-green-400 shrink-0" />
                @{a.id}
              </button>
            ))}
          </div>
        )}

        <textarea
          ref={textareaRef}
          value={text}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder="Send instruction… type @ to mention an agent  (⌘+Enter to send)"
          rows={2}
          className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 resize-none focus:outline-none focus:border-blue-500 transition-colors"
        />
        <button
          type="submit"
          disabled={sending || !text.trim()}
          className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors h-[70px]"
        >
          {sending ? '…' : 'Send'}
        </button>
      </div>
    </form>
  )
}
