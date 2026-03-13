import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  getProjects,
  getThread,
  getTasks,
  getAgents,
  postInstruction,
  Message,
  Task,
  Agent,
  Project,
} from '../api'
import { useWebSocket } from '../hooks/useWebSocket'
import Thread from '../components/Thread'
import TaskRegistry from '../components/TaskRegistry'
import AgentPills from '../components/AgentPills'
import InstructionInput from '../components/InstructionInput'
import Sidebar from '../components/Sidebar'

const TAG_FILTERS = ['All', 'conflict', 'blocked', 'question', 'done', 'system']

export default function ProjectPage() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()

  const [project, setProject] = useState<Project | null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [tagFilter, setTagFilter] = useState<string>('All')
  const [agentFilter, setAgentFilter] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // Conflict/blocked badge
  const hasConflict = messages.some(m => m.tag === 'conflict')
  const hasBlocked = messages.some(m => {
    if (m.tag !== 'blocked') return false
    const age = (Date.now() - new Date(m.created_at).getTime()) / 1000 / 60
    return age > 10
  })

  useEffect(() => {
    if (!slug) return
    Promise.all([
      getProjects(),
      getThread(slug, undefined, undefined, 100),
      getTasks(slug),
      getAgents(slug),
    ]).then(([projs, msgs, tks, ags]) => {
      setProjects(projs)
      const current = projs.find(p => p.slug === slug) || null
      setProject(current)
      setMessages(msgs)
      setTasks(tks)
      setAgents(ags)
      setLoading(false)
    }).catch(() => navigate('/'))
  }, [slug, navigate])

  const handleWsEvent = useCallback((event: { type: string; data: unknown }) => {
    if (event.type === 'message') {
      const msg = event.data as Message
      setMessages(prev => prev.some(m => m.id === msg.id) ? prev : [...prev, msg])
    } else if (event.type === 'task_update') {
      const task = event.data as Task
      setTasks(prev => prev.some(t => t.id === task.id) ? prev.map(t => t.id === task.id ? task : t) : [...prev, task])
    } else if (event.type === 'agent_status') {
      const { agent_id, online } = event.data as { agent_id: string; online: boolean }
      setAgents(prev => prev.map(a => a.id === agent_id ? { ...a, online } : a).filter(a => a.online))
      // Refresh agents list
      if (slug) getAgents(slug).then(setAgents)
    }
  }, [slug])

  useWebSocket(slug!, handleWsEvent)

  const handleSend = async (content: string) => {
    if (!slug) return
    const msg = await postInstruction(slug, content)
    setMessages(prev => prev.some(m => m.id === msg.id) ? prev : [...prev, msg])
  }

  const displayedMessages = messages.filter(m => {
    if (tagFilter !== 'All' && m.tag !== tagFilter) return false
    if (agentFilter && m.agent_id !== agentFilter) return false
    return true
  })

  const mcpEndpoint = `${window.location.protocol}//${window.location.host}/mcp/projects/${slug}`

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-950 text-gray-400">
        Loading…
      </div>
    )
  }

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden">
      {/* Sidebar */}
      <Sidebar projects={projects} currentSlug={slug!} mcpEndpoint={mcpEndpoint} />

      {/* Center: Thread */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Topbar */}
        <div className="border-b border-gray-800 px-4 py-3 flex items-center justify-between gap-4 shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <h1 className="font-semibold text-white truncate">{project?.name}</h1>
            <div className="flex items-center gap-1">
              {hasConflict && (
                <span className="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse" title="Conflicts detected" />
              )}
              {hasBlocked && (
                <span className="w-2.5 h-2.5 rounded-full bg-yellow-400 animate-pulse" title="Agents blocked > 10 min" />
              )}
            </div>
            <span className="text-xs text-gray-500 shrink-0">{agents.length} online</span>
          </div>
          <AgentPills agents={agents} onFilterAgent={setAgentFilter} filteredAgent={agentFilter} />
        </div>

        {/* Tag filters */}
        <div className="flex items-center gap-1 px-4 py-2 border-b border-gray-800 shrink-0">
          {agentFilter && (
            <button
              onClick={() => setAgentFilter(null)}
              className="text-xs bg-blue-900 text-blue-300 border border-blue-700 px-2 py-0.5 rounded-full mr-1"
            >
              @{agentFilter.slice(0, 12)} ✕
            </button>
          )}
          {TAG_FILTERS.map(t => (
            <button
              key={t}
              onClick={() => setTagFilter(t)}
              className={`text-xs px-2.5 py-1 rounded-full transition-colors ${
                tagFilter === t
                  ? 'bg-gray-700 text-white'
                  : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              {t}
            </button>
          ))}
          <span className="ml-auto text-xs text-gray-600">{displayedMessages.length} messages</span>
        </div>

        {/* Thread */}
        <Thread messages={displayedMessages} onFilterAgent={setAgentFilter} />

        {/* Instruction input */}
        <InstructionInput onSend={handleSend} />
      </div>

      {/* Right panel: Task Registry */}
      <div className="w-56 border-l border-gray-800 flex flex-col shrink-0">
        <TaskRegistry slug={slug!} tasks={tasks} onTasksChange={setTasks} />
      </div>
    </div>
  )
}
