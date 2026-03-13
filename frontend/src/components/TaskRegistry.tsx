import { useState } from 'react'
import { Task, createTask, updateTask, deleteTask } from '../api'

const STATUS_COLORS: Record<string, string> = {
  pending:     'text-gray-400 bg-gray-800',
  claimed:     'text-blue-300 bg-blue-900/50',
  in_progress: 'text-yellow-300 bg-yellow-900/50',
  done:        'text-green-300 bg-green-900/50',
  blocked:     'text-orange-300 bg-orange-900/50',
  conflict:    'text-red-300 bg-red-900/50',
}

const STATUS_BAR: Record<string, string> = {
  pending:     'bg-gray-600',
  claimed:     'bg-blue-500',
  in_progress: 'bg-yellow-500',
  done:        'bg-green-500',
  blocked:     'bg-orange-500',
  conflict:    'bg-red-500',
}

interface Props {
  slug: string
  tasks: Task[]
  onTasksChange: (tasks: Task[]) => void
}

export default function TaskRegistry({ slug, tasks, onTasksChange }: Props) {
  const [adding, setAdding] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editStatus, setEditStatus] = useState('')
  const [editProgress, setEditProgress] = useState(0)

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newTitle.trim()) return
    const task = await createTask(slug, newTitle.trim())
    onTasksChange([...tasks, task])
    setNewTitle('')
    setAdding(false)
  }

  const handleDelete = async (taskId: string) => {
    await deleteTask(slug, taskId)
    onTasksChange(tasks.filter(t => t.id !== taskId))
  }

  const startEdit = (task: Task) => {
    setEditingId(task.id)
    setEditStatus(task.status)
    setEditProgress(task.progress)
  }

  const saveEdit = async (task: Task) => {
    const updated = await updateTask(slug, task.id, {
      status: editStatus,
      progress: editProgress,
    })
    onTasksChange(tasks.map(t => t.id === task.id ? updated : t))
    setEditingId(null)
  }

  const stats = {
    agents: new Set(tasks.filter(t => t.agent_id).map(t => t.agent_id)).size,
    prs: tasks.filter(t => t.pr_url).length,
    conflicts: tasks.filter(t => t.status === 'conflict').length,
    done: tasks.filter(t => t.status === 'done').length,
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-4 border-b border-gray-800">
        <h2 className="text-sm font-semibold text-gray-300">Tasks</h2>
        <button
          onClick={() => setAdding(true)}
          className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 px-2 py-1 rounded transition-colors"
        >
          + Add
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {adding && (
          <form onSubmit={handleAdd} className="bg-gray-800 rounded-lg p-3">
            <input
              autoFocus
              value={newTitle}
              onChange={e => setNewTitle(e.target.value)}
              placeholder="Task title…"
              className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-white placeholder-gray-500 mb-2 focus:outline-none focus:border-blue-500"
            />
            <div className="flex gap-1">
              <button type="submit" className="text-xs bg-blue-600 hover:bg-blue-500 text-white px-2 py-1 rounded transition-colors">
                Add
              </button>
              <button type="button" onClick={() => setAdding(false)} className="text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 px-2 py-1 rounded transition-colors">
                Cancel
              </button>
            </div>
          </form>
        )}

        {tasks.length === 0 && !adding && (
          <p className="text-xs text-gray-600 text-center py-8">No tasks yet</p>
        )}

        {tasks.map(task => (
          <div
            key={task.id}
            className={`rounded-lg p-3 border ${
              task.status === 'conflict'
                ? 'border-red-700 bg-red-950/30'
                : task.status === 'blocked'
                ? 'border-orange-800 bg-orange-950/20'
                : 'border-gray-800 bg-gray-900'
            }`}
          >
            {editingId === task.id ? (
              <div>
                <p className="text-xs font-medium text-white mb-2">{task.title}</p>
                <select
                  value={editStatus}
                  onChange={e => setEditStatus(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-xs text-white mb-2 focus:outline-none"
                >
                  {['pending','claimed','in_progress','done','blocked','conflict'].map(s => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={editProgress}
                  onChange={e => setEditProgress(Number(e.target.value))}
                  className="w-full mb-2"
                />
                <p className="text-xs text-gray-400 mb-2">Progress: {editProgress}%</p>
                <div className="flex gap-1">
                  <button onClick={() => saveEdit(task)} className="text-xs bg-blue-600 hover:bg-blue-500 text-white px-2 py-1 rounded transition-colors">Save</button>
                  <button onClick={() => setEditingId(null)} className="text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 px-2 py-1 rounded transition-colors">Cancel</button>
                </div>
              </div>
            ) : (
              <div>
                <div className="flex items-start justify-between gap-2 mb-2">
                  <p className="text-xs font-medium text-white leading-tight">{task.title}</p>
                  <div className="flex gap-1 shrink-0">
                    <button
                      onClick={() => startEdit(task)}
                      className="text-gray-600 hover:text-gray-300 text-xs transition-colors"
                      title="Edit"
                    >✏</button>
                    <button
                      onClick={() => handleDelete(task.id)}
                      className="text-gray-600 hover:text-red-400 text-xs transition-colors"
                      title="Delete"
                    >✕</button>
                  </div>
                </div>

                <span className={`inline-block text-xs px-1.5 py-0.5 rounded font-medium mb-2 ${STATUS_COLORS[task.status] || 'text-gray-400 bg-gray-800'}`}>
                  {task.status}
                </span>

                {task.agent_id && (
                  <p className="text-xs text-gray-500 mb-1">🤖 {task.agent_id.slice(0, 12)}</p>
                )}

                {task.progress > 0 && (
                  <div className="w-full bg-gray-800 rounded-full h-1 mt-1">
                    <div
                      className={`h-1 rounded-full transition-all ${STATUS_BAR[task.status] || 'bg-gray-500'}`}
                      style={{ width: `${task.progress}%` }}
                    />
                  </div>
                )}

                {task.pr_url && (
                  <a href={task.pr_url} target="_blank" rel="noreferrer" className="text-xs text-blue-400 hover:underline mt-1 block truncate">
                    PR ↗
                  </a>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Stats bar */}
      <div className="border-t border-gray-800 p-3 grid grid-cols-2 gap-2">
        <div className="bg-gray-900 rounded-lg p-2 text-center">
          <p className="text-lg font-bold text-white">{stats.agents}</p>
          <p className="text-xs text-gray-500">Agents</p>
        </div>
        <div className="bg-gray-900 rounded-lg p-2 text-center">
          <p className="text-lg font-bold text-white">{stats.prs}</p>
          <p className="text-xs text-gray-500">PRs</p>
        </div>
        <div className="bg-gray-900 rounded-lg p-2 text-center">
          <p className={`text-lg font-bold ${stats.conflicts > 0 ? 'text-red-400' : 'text-white'}`}>{stats.conflicts}</p>
          <p className="text-xs text-gray-500">Conflicts</p>
        </div>
        <div className="bg-gray-900 rounded-lg p-2 text-center">
          <p className="text-lg font-bold text-green-400">{stats.done}</p>
          <p className="text-xs text-gray-500">Done</p>
        </div>
      </div>
    </div>
  )
}
