const API_KEY = import.meta.env.VITE_API_KEY || ''
const BASE = '/api/v1'

function headers(): HeadersInit {
  return API_KEY ? { 'X-API-Key': API_KEY, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: headers(),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err || res.statusText)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export interface Project {
  id: string
  slug: string
  name: string
  description: string | null
  archived: boolean
  created_at: string
  online_agents: number
}

export interface Message {
  id: string
  project_id: string
  agent_id: string
  content: string
  tag: string
  reply_to: string | null
  created_at: string
}

export interface Task {
  id: string
  project_id: string
  title: string
  description: string | null
  status: string
  agent_id: string | null
  progress: number
  pr_url: string | null
  created_at: string
  updated_at: string
}

export interface Agent {
  id: string
  project_id: string
  name: string
  capabilities: string | null
  last_ping: string | null
  online: boolean
}

// Projects
export const getProjects = () => req<Project[]>('GET', '/projects/')
export const createProject = (name: string, description?: string) =>
  req<Project>('POST', '/projects/', { name, description })
export const archiveProject = (slug: string) => req<void>('DELETE', `/projects/${slug}`)

// Thread
export const getThread = (slug: string, since?: string, tag?: string, limit = 50) => {
  const params = new URLSearchParams()
  if (since) params.set('since', since)
  if (tag) params.set('tag', tag)
  params.set('limit', String(limit))
  return req<Message[]>('GET', `/projects/${slug}/thread/?${params}`)
}
export const postInstruction = (slug: string, content: string) =>
  req<Message>('POST', `/projects/${slug}/thread/`, { content })

// Tasks
export const getTasks = (slug: string, status?: string) => {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  return req<Task[]>('GET', `/projects/${slug}/tasks/?${params}`)
}
export const createTask = (slug: string, title: string, description?: string) =>
  req<Task>('POST', `/projects/${slug}/tasks/`, { title, description })
export const updateTask = (slug: string, taskId: string, updates: Partial<Task>) =>
  req<Task>('PATCH', `/projects/${slug}/tasks/${taskId}`, updates)
export const deleteTask = (slug: string, taskId: string) =>
  req<void>('DELETE', `/projects/${slug}/tasks/${taskId}`)

// Agents
export const getAgents = (slug: string) => req<Agent[]>('GET', `/projects/${slug}/agents/`)

// WebSocket URL
export function wsUrl(slug: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  const key = API_KEY ? `?api_key=${API_KEY}` : ''
  return `${proto}//${host}/ws/projects/${slug}${key}`
}

// SWR fetcher
export const fetcher = (path: string) => req('GET', path)
