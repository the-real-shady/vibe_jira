import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import { Message } from '../api'

const TAG_STYLES: Record<string, string> = {
  system:   'bg-blue-950 border-blue-800 text-blue-300',
  claim:    'bg-gray-800 border-gray-700 text-gray-300',
  update:   'bg-gray-800 border-gray-700 text-gray-300',
  question: 'bg-yellow-950 border-yellow-800 text-yellow-300',
  done:     'bg-green-950 border-green-800 text-green-300',
  conflict: 'bg-red-950 border-red-800 text-red-300',
  blocked:  'bg-orange-950 border-orange-800 text-orange-300',
}

const TAG_BADGE: Record<string, string> = {
  system:   'bg-blue-800 text-blue-200',
  claim:    'bg-gray-700 text-gray-200',
  update:   'bg-gray-700 text-gray-300',
  question: 'bg-yellow-800 text-yellow-200',
  done:     'bg-green-800 text-green-200',
  conflict: 'bg-red-800 text-red-200',
  blocked:  'bg-orange-800 text-orange-200',
}

interface Props {
  messages: Message[]
  onFilterAgent?: (agentId: string) => void
}

function timeStr(ts: string): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function avatar(agentId: string): string {
  return agentId === 'team-lead' ? '👤' : agentId === 'system' ? '⚙️' : '🤖'
}

export default function Thread({ messages, onFilterAgent }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-600 text-sm">
        No messages yet. Send an instruction or connect an agent.
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-3">
      {messages.map(msg => (
        <div
          key={msg.id}
          className={`border rounded-xl p-4 ${TAG_STYLES[msg.tag] || 'bg-gray-800 border-gray-700 text-gray-300'}`}
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-base">{avatar(msg.agent_id)}</span>
              <button
                onClick={() => onFilterAgent?.(msg.agent_id)}
                className="text-sm font-medium hover:underline cursor-pointer"
              >
                {msg.agent_id}
              </button>
              <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${TAG_BADGE[msg.tag] || 'bg-gray-700 text-gray-300'}`}>
                {msg.tag}
              </span>
              {msg.reply_to && (
                <span className="text-xs text-gray-500">↩ reply</span>
              )}
            </div>
            <span className="text-xs text-gray-500">{timeStr(msg.created_at)}</span>
          </div>
          <div className="prose-thread text-sm leading-relaxed">
            <ReactMarkdown>{msg.content}</ReactMarkdown>
          </div>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
