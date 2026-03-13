import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getProjects, createProject, archiveProject, Project } from '../api'

export default function ProjectListPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const navigate = useNavigate()

  const load = async () => {
    try {
      setProjects(await getProjects())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newName.trim()) return
    const p = await createProject(newName.trim(), newDesc.trim() || undefined)
    setProjects(prev => [p, ...prev])
    setNewName('')
    setNewDesc('')
    setCreating(false)
  }

  const handleArchive = async (slug: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('Archive this project?')) return
    await archiveProject(slug)
    setProjects(prev => prev.filter(p => p.slug !== slug))
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-950 text-gray-400">
        Loading…
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 p-8">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white">AgentBoard</h1>
            <p className="text-gray-400 text-sm mt-1">Collaborative AI agent coordination</p>
          </div>
          <button
            onClick={() => setCreating(true)}
            className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            + New Project
          </button>
        </div>

        {creating && (
          <form onSubmit={handleCreate} className="bg-gray-900 border border-gray-700 rounded-xl p-5 mb-6">
            <h2 className="text-sm font-semibold text-gray-300 mb-4">New Project</h2>
            <input
              autoFocus
              value={newName}
              onChange={e => setNewName(e.target.value)}
              placeholder="Project name"
              className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 mb-3 focus:outline-none focus:border-blue-500"
            />
            <input
              value={newDesc}
              onChange={e => setNewDesc(e.target.value)}
              placeholder="Description (optional)"
              className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 mb-4 focus:outline-none focus:border-blue-500"
            />
            <div className="flex gap-2">
              <button
                type="submit"
                className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
              >
                Create
              </button>
              <button
                type="button"
                onClick={() => setCreating(false)}
                className="bg-gray-700 hover:bg-gray-600 text-gray-300 px-4 py-2 rounded-lg text-sm font-medium transition-colors"
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        {projects.length === 0 ? (
          <div className="text-center py-16 text-gray-500">
            <p className="text-4xl mb-3">🤖</p>
            <p>No projects yet. Create one to get started.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {projects.map(p => (
              <div
                key={p.id}
                onClick={() => navigate(`/projects/${p.slug}`)}
                className="bg-gray-900 border border-gray-800 hover:border-gray-600 rounded-xl p-5 cursor-pointer transition-colors group"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className={`w-2 h-2 rounded-full ${p.online_agents > 0 ? 'bg-green-400' : 'bg-gray-600'}`} />
                    <div>
                      <p className="font-medium text-white group-hover:text-blue-300 transition-colors">
                        {p.name}
                      </p>
                      {p.description && (
                        <p className="text-gray-400 text-sm mt-0.5">{p.description}</p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {p.online_agents > 0 && (
                      <span className="text-xs bg-green-900/50 text-green-400 px-2 py-0.5 rounded-full border border-green-800">
                        {p.online_agents} agent{p.online_agents !== 1 ? 's' : ''} online
                      </span>
                    )}
                    <button
                      onClick={e => handleArchive(p.slug, e)}
                      className="opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-400 text-sm transition-all"
                    >
                      Archive
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
