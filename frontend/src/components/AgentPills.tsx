import { Agent } from '../api'

interface Props {
  agents: Agent[]
  onFilterAgent?: (agentId: string | null) => void
  filteredAgent?: string | null
}

export default function AgentPills({ agents, onFilterAgent, filteredAgent }: Props) {
  if (agents.length === 0) return null

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {agents.map(agent => (
        <button
          key={agent.id}
          onClick={() => onFilterAgent?.(filteredAgent === agent.id ? null : agent.id)}
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
            filteredAgent === agent.id
              ? 'bg-blue-600 text-white'
              : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
          }`}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
          {agent.name}
        </button>
      ))}
    </div>
  )
}
