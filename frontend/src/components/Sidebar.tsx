import { useNavigate } from 'react-router-dom'
import { Project } from '../api'

interface Props {
  projects: Project[]
  currentSlug: string
  mcpEndpoint: string
}

export default function Sidebar({ projects, currentSlug, mcpEndpoint }: Props) {
  const navigate = useNavigate()

  const copyEndpoint = () => {
    navigator.clipboard.writeText(mcpEndpoint)
  }

  return (
    <div className="w-52 bg-gray-900 border-r border-gray-800 flex flex-col h-full shrink-0">
      <div className="p-4 border-b border-gray-800">
        <button
          onClick={() => navigate('/')}
          className="text-sm font-bold text-white hover:text-blue-300 transition-colors"
        >
          AgentBoard
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        <p className="text-xs text-gray-600 uppercase tracking-wider px-2 py-1 mb-1">Projects</p>
        {projects.map(p => (
          <button
            key={p.id}
            onClick={() => navigate(`/projects/${p.slug}`)}
            className={`w-full text-left flex items-center gap-2 px-2 py-2 rounded-lg text-sm transition-colors ${
              p.slug === currentSlug
                ? 'bg-gray-800 text-white'
                : 'text-gray-400 hover:bg-gray-800 hover:text-white'
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${p.online_agents > 0 ? 'bg-green-400' : 'bg-gray-600'}`} />
            <span className="truncate">{p.name}</span>
          </button>
        ))}
      </div>

      <div className="p-3 border-t border-gray-800">
        <p className="text-xs text-gray-500 mb-1">MCP Endpoint</p>
        <div className="flex items-center gap-1">
          <code className="flex-1 text-xs text-blue-300 bg-gray-800 px-2 py-1 rounded truncate">
            {mcpEndpoint}
          </code>
          <button
            onClick={copyEndpoint}
            className="text-gray-500 hover:text-gray-300 text-xs px-1 py-1 transition-colors"
            title="Copy"
          >
            📋
          </button>
        </div>
      </div>
    </div>
  )
}
