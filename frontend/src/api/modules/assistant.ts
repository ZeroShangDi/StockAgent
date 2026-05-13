import { api } from '../client'
import { generateUuid } from '@/utils/id'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export interface AssistantArtifact {
  artifact_id: string
  title: string
  artifact_type: 'html'
  intent?: string
  created_at?: string
  html?: string
}

export interface AssistantMessage {
  message_id: string
  role: 'user' | 'assistant'
  content: string
  artifacts?: AssistantArtifact[]
  created_at?: string
}

export interface AssistantConversation {
  conversation_id: string
  title: string
  latest_artifact_id?: string | null
  message_count: number
  created_at?: string
  updated_at?: string
  last_message_at?: string | null
}

export interface AssistantConversationDetail extends AssistantConversation {
  messages: AssistantMessage[]
  artifacts: AssistantArtifact[]
}

export interface AssistantStreamEvent {
  type: string
  [key: string]: unknown
}

function buildApiUrl(path: string): string {
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path
  }
  return `${BASE_URL}${path}`
}

export const assistantApi = {
  createConversation: (title?: string) =>
    api.post<AssistantConversation>('/assistant/conversations', { title }),

  listConversations: () =>
    api.get<{ items: AssistantConversation[] }>('/assistant/conversations'),

  getConversation: (conversationId: string) =>
    api.get<AssistantConversationDetail>(`/assistant/conversations/${conversationId}`),

  getArtifact: (artifactId: string) =>
    api.get<AssistantArtifact>(`/assistant/artifacts/${artifactId}`),

  async streamConversationMessage(
    conversationId: string,
    content: string,
    onEvent: (event: AssistantStreamEvent) => void,
  ): Promise<void> {
    const token = localStorage.getItem('access_token')
    const response = await fetch(
      buildApiUrl(`/assistant/conversations/${conversationId}/messages/stream`),
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          'X-Trace-ID': generateUuid(),
        },
        body: JSON.stringify({ content }),
      },
    )

    if (!response.ok || !response.body) {
      throw new Error(`流式请求失败 (${response.status})`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    const consumeBuffer = (): void => {
      const normalized = buffer.replace(/\r\n/g, '\n')
      const chunks = normalized.split('\n\n')
      const trailingIncomplete = normalized.endsWith('\n\n') ? '' : (chunks.pop() || '')

      for (const rawEvent of chunks) {
        const dataLines = rawEvent
          .split('\n')
          .filter((line) => line.startsWith('data: '))
          .map((line) => line.slice(6))

        if (!dataLines.length) continue

        const payload = dataLines.join('\n').trim()
        if (!payload) continue

        onEvent(JSON.parse(payload) as AssistantStreamEvent)
      }

      buffer = trailingIncomplete
    }

    while (true) {
      const { value, done } = await reader.read()
      if (done) {
        consumeBuffer()
        break
      }

      buffer += decoder.decode(value, { stream: true })
      consumeBuffer()
    }
  },
}

export default assistantApi
