<template>
  <div class="workspace-page" :class="{ 'artifact-open': showArtifactPane }">
    <div class="floating-actions">
      <button
        v-if="showArtifactPane"
        type="button"
        class="floating-btn ghost"
        @click="closeArtifact"
      >
        收起预览
      </button>
      <button
        type="button"
        class="floating-btn"
        :disabled="loading"
        @click="startNewConversation"
      >
        新对话
      </button>
    </div>

    <div class="workspace-shell">
      <div class="chat-pane">
        <section class="chat-content">
          <section
            v-if="messages.length === 0"
            class="landing"
          >
            <h1>今天想让 StockAgent 帮你做什么？</h1>
            <div class="prompt-list">
              <button
                v-for="prompt in quickPrompts"
                :key="prompt"
                type="button"
                class="prompt-chip"
                @click="usePrompt(prompt)"
              >
                {{ prompt }}
              </button>
            </div>
          </section>

          <section
            v-else
            ref="messageContainerRef"
            class="message-stream"
          >
            <article
              v-for="message in messages"
              :key="message.id"
              class="message-row"
              :class="message.role"
            >
              <div class="message-card">
                <div
                  class="message-body markdown-body"
                  v-html="renderMessageContent(message)"
                ></div>
                <div
                  v-if="message.artifacts?.length"
                  class="message-artifacts"
                >
                  <button
                    v-for="artifact in message.artifacts"
                    :key="artifact.artifact_id"
                    type="button"
                    class="artifact-chip"
                    @click="openArtifact(artifact)"
                  >
                    {{ artifact.title }}
                  </button>
                </div>
              </div>
            </article>
          </section>
        </section>

        <div
          v-if="loading || streamStatus"
          class="status-line"
        >
          {{ streamStatus || '正在处理请求' }}
        </div>

        <footer class="composer">
          <div class="composer-shell">
            <textarea
              v-model="draft"
              class="composer-input"
              rows="1"
              placeholder="给 StockAgent 发送消息"
              @keydown.enter.exact.prevent="sendMessage"
            />
            <button
              type="button"
              class="send-btn"
              :disabled="loading || !draft.trim() || !conversationId"
              @click="sendMessage"
            >
              {{ loading ? '处理中' : '发送' }}
            </button>
          </div>
        </footer>
      </div>

      <aside
        v-if="showArtifactPane"
        class="artifact-pane"
      >
        <div class="artifact-head">
          <div class="artifact-title">{{ activeArtifact?.title || '结果预览' }}</div>
        </div>
        <iframe
          class="artifact-frame"
          sandbox=""
          :srcdoc="activeArtifactHtml"
          title="assistant-artifact"
        />
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'

import { assistantApi } from '@/api'
import type {
  AssistantArtifact,
  AssistantConversation,
  AssistantMessage,
  AssistantStreamEvent,
} from '@/api/modules/assistant'

type ChatRole = 'user' | 'assistant'

interface ChatMessageItem {
  id: string
  role: ChatRole
  content: string
  artifacts?: AssistantArtifact[]
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

const markdownRenderer: any = new (marked as any).Renderer()
markdownRenderer.code = (token: { text: string; lang?: string }) => {
  const language = (token.lang || 'text').trim()
  return `
    <div class="code-block">
      <div class="code-block__head">${escapeHtml(language)}</div>
      <pre><code>${escapeHtml(token.text || '')}</code></pre>
    </div>
  `
}

marked.setOptions({
  gfm: true,
  breaks: true,
  renderer: markdownRenderer,
})

const quickPrompts = [
  '筛选近30天内涨幅超过20%的股票，并按 20%-40%、40%-60%、60%-80%、80%-100%、100%以上分层展示，每层列出名称、代码和近30天涨幅，再生成 HTML',
  '帮我总结一下当前系统适合做哪些研究任务，并生成一页 HTML 说明',
  '告诉我这个智能工作台当前的安全边界是什么',
]

const conversationId = ref('')
const conversation = ref<AssistantConversation | null>(null)
const draft = ref('')
const loading = ref(false)
const streamStatus = ref('')
const activeArtifact = ref<AssistantArtifact | null>(null)
const activeArtifactHtml = ref('')
const messageContainerRef = ref<HTMLElement | null>(null)
const messages = ref<ChatMessageItem[]>([])
const currentAssistantId = ref('')

const showArtifactPane = computed(() => Boolean(activeArtifactHtml.value))

async function ensureConversation(): Promise<void> {
  if (conversationId.value) return
  const created = await assistantApi.createConversation()
  conversation.value = created
  conversationId.value = created.conversation_id
}

async function startNewConversation(): Promise<void> {
  if (loading.value) return
  const created = await assistantApi.createConversation()
  conversation.value = created
  conversationId.value = created.conversation_id
  messages.value = []
  activeArtifact.value = null
  activeArtifactHtml.value = ''
  streamStatus.value = ''
  currentAssistantId.value = ''
}

function usePrompt(prompt: string): void {
  draft.value = prompt
  void sendMessage()
}

function renderMessageContent(message: ChatMessageItem): string {
  const raw = message.content || (message.role === 'assistant' && loading.value ? '正在思考...' : '')
  const sanitized = raw
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/\son\w+="[^"]*"/gi, '')
    .replace(/\son\w+='[^']*'/gi, '')

  if (message.role === 'user') {
    return `<p>${escapeHtml(sanitized).replace(/\n/g, '<br />')}</p>`
  }

  return String(marked.parse(sanitized))
}

function appendAssistantDelta(content: string): void {
  const target = messages.value.find((item) => item.id === currentAssistantId.value)
  if (!target) return
  target.content += content
}

async function scrollToBottom(): Promise<void> {
  await nextTick()
  const el = messageContainerRef.value
  if (el) {
    el.scrollTop = el.scrollHeight
  }
}

function closeArtifact(): void {
  activeArtifact.value = null
  activeArtifactHtml.value = ''
}

async function openArtifact(artifact: AssistantArtifact): Promise<void> {
  activeArtifact.value = artifact
  if (artifact.html) {
    activeArtifactHtml.value = artifact.html
    return
  }
  const full = await assistantApi.getArtifact(artifact.artifact_id)
  activeArtifact.value = full
  activeArtifactHtml.value = full.html || ''
}

function handleStreamEvent(event: AssistantStreamEvent): void {
  if (event.type === 'status') {
    streamStatus.value = String(event.label || '')
    return
  }

  if (event.type === 'tool_result') {
    const target = messages.value.find((item) => item.id === currentAssistantId.value)
    const summary = event.summary as Record<string, unknown> | undefined
    if (target && !target.content && summary) {
      const qualifiedCount = summary.qualified_count ?? '-'
      const latestTradeDate = summary.latest_trade_date ?? '-'
      target.content = `已完成数据筛选，最新交易日 ${latestTradeDate}，满足条件的股票共 ${qualifiedCount} 只。\n\n`
    }
    void scrollToBottom()
    return
  }

  if (event.type === 'assistant_delta') {
    appendAssistantDelta(String(event.content || ''))
    void scrollToBottom()
    return
  }

  if (event.type === 'artifact' && event.artifact) {
    const artifact = event.artifact as AssistantArtifact
    const target = messages.value.find((item) => item.id === currentAssistantId.value)
    if (target) {
      target.artifacts = [...(target.artifacts || []), artifact]
    }
    activeArtifact.value = artifact
    activeArtifactHtml.value = artifact.html || ''
    return
  }

  if (event.type === 'done' && event.message) {
    const message = event.message as AssistantMessage
    const target = messages.value.find((item) => item.id === currentAssistantId.value)
    if (target) {
      target.content = message.content || target.content
      target.artifacts = (message.artifacts || []) as AssistantArtifact[]
    }
    streamStatus.value = ''
    void scrollToBottom()
    return
  }

  if (event.type === 'error') {
    const target = messages.value.find((item) => item.id === currentAssistantId.value)
    if (target && !target.content) {
      target.content = `请求失败：${String(event.detail || '未知错误')}`
    }
    void scrollToBottom()
  }
}

async function sendMessage(): Promise<void> {
  if (!draft.value.trim() || loading.value) return
  await ensureConversation()

  const content = draft.value.trim()
  draft.value = ''
  loading.value = true
  streamStatus.value = '正在准备上下文'

  messages.value.push({
    id: `user-${Date.now()}`,
    role: 'user',
    content,
  })

  currentAssistantId.value = `assistant-${Date.now()}`
  messages.value.push({
    id: currentAssistantId.value,
    role: 'assistant',
    content: '',
    artifacts: [],
  })

  await scrollToBottom()

  try {
    await assistantApi.streamConversationMessage(conversationId.value, content, handleStreamEvent)
    const latest = await assistantApi.getConversation(conversationId.value)
    const latestAssistant = [...latest.messages].reverse().find((item) => item.role === 'assistant')
    const target = messages.value.find((item) => item.id === currentAssistantId.value)

    if (target && latestAssistant) {
      target.content = latestAssistant.content || target.content
      target.artifacts = (latestAssistant.artifacts || []) as AssistantArtifact[]
      const latestArtifact = target.artifacts?.[0]
      if (latestArtifact && !activeArtifactHtml.value) {
        await openArtifact(latestArtifact)
      }
    }
  } catch (error) {
    const target = messages.value.find((item) => item.id === currentAssistantId.value)
    if (target) {
      target.content = error instanceof Error ? error.message : '请求失败'
    }
    ElMessage.error(target?.content || '请求失败')
  } finally {
    loading.value = false
    streamStatus.value = ''
    currentAssistantId.value = ''
    await scrollToBottom()
  }
}

onMounted(async () => {
  await ensureConversation()
})
</script>

<style scoped lang="scss">
.workspace-page {
  height: 100vh;
  overflow: hidden;
  position: relative;
  background:
    radial-gradient(circle at top, rgba(29, 122, 99, 0.08), transparent 30%),
    linear-gradient(180deg, #f8f6f1 0%, #f2eee5 100%);
}

.floating-actions {
  position: fixed;
  top: 16px;
  right: 18px;
  z-index: 20;
  display: flex;
  gap: 10px;
  padding: 6px;
  border-radius: 999px;
  background: rgba(248, 246, 241, 0.76);
  backdrop-filter: blur(18px);
  box-shadow: 0 14px 32px rgba(20, 34, 51, 0.08);
}

.workspace-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  height: 100vh;
  overflow: hidden;
}

.workspace-page.artifact-open .workspace-shell {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}

.chat-pane {
  display: flex;
  flex-direction: column;
  height: 100vh;
  min-height: 0;
  overflow: hidden;
  max-width: 920px;
  width: 100%;
  margin: 0 auto;
  padding: 22px 20px 22px;
}

.workspace-page.artifact-open .chat-pane {
  max-width: none;
  padding-right: 10px;
}

.floating-btn,
.prompt-chip,
.artifact-chip,
.send-btn {
  border: none;
  cursor: pointer;
  transition: background 0.18s ease, transform 0.18s ease, opacity 0.18s ease;
}

.floating-btn {
  padding: 10px 14px;
  border-radius: 999px;
  background: #182a3f;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
}

.floating-btn.ghost {
  background: rgba(20, 34, 51, 0.06);
  color: #22354a;
}

.floating-btn:hover,
.prompt-chip:hover,
.artifact-chip:hover,
.send-btn:hover {
  transform: translateY(-1px);
}

.floating-btn:disabled,
.send-btn:disabled {
  opacity: 0.56;
  cursor: not-allowed;
  transform: none;
}

.chat-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.landing {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 22px;
  min-height: 0;
  padding: 24px 0 28px;
  text-align: center;
  overflow-y: auto;
}

.landing h1 {
  margin: 0;
  max-width: 760px;
  color: #142233;
  font-size: clamp(28px, 4vw, 46px);
  line-height: 1.12;
  letter-spacing: -0.03em;
}

.prompt-list {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
  max-width: 860px;
}

.prompt-chip {
  padding: 14px 18px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.74);
  color: #213248;
  font-size: 14px;
  line-height: 1.5;
  box-shadow: 0 10px 30px rgba(20, 34, 51, 0.05);
}

.message-stream {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 24px 6px 20px 0;
}

.message-row {
  display: flex;
  margin-bottom: 14px;
}

.message-row.user {
  justify-content: flex-end;
}

.message-card {
  width: min(100%, 760px);
  padding: 16px 18px;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.82);
  color: #17273b;
  box-shadow: 0 14px 34px rgba(20, 34, 51, 0.05);
}

.message-row.user .message-card {
  background: linear-gradient(135deg, #163149 0%, #214a5e 100%);
  color: #f8f7f2;
}

.message-artifacts {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
}

.artifact-chip {
  padding: 8px 12px;
  border-radius: 999px;
  background: rgba(15, 122, 103, 0.1);
  color: #0f7a67;
  font-size: 12px;
  font-weight: 600;
}

.status-line {
  padding: 0 6px 10px;
  color: #728092;
  font-size: 13px;
}

.composer {
  flex-shrink: 0;
  padding-top: 10px;
}

.composer-shell {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 28px;
  background: rgba(255, 255, 255, 0.84);
  box-shadow: 0 18px 44px rgba(20, 34, 51, 0.08);
}

.composer-input {
  flex: 1;
  min-height: 48px;
  max-height: 220px;
  resize: vertical;
  border: none;
  outline: none;
  background: transparent;
  color: #142233;
  font: inherit;
  line-height: 1.7;
}

.send-btn {
  padding: 14px 20px;
  border-radius: 20px;
  background: #182a3f;
  color: #fff;
  font-weight: 600;
}

.artifact-pane {
  display: flex;
  flex-direction: column;
  height: 100vh;
  min-height: 0;
  overflow: hidden;
  padding: 22px 20px 22px 10px;
}

.artifact-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 6px 14px 18px;
  flex-shrink: 0;
}

.artifact-title {
  color: #142233;
  font-size: 14px;
  font-weight: 600;
}

.artifact-frame {
  flex: 1;
  width: 100%;
  height: 100%;
  min-height: 0;
  border: none;
  border-radius: 28px;
  background: #fff;
  box-shadow: 0 22px 50px rgba(20, 34, 51, 0.1);
}

.markdown-body {
  line-height: 1.85;
}

.markdown-body :deep(p) {
  margin: 0 0 12px;
}

.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0 0 12px;
  padding-left: 20px;
}

.markdown-body :deep(table) {
  width: 100%;
  margin: 12px 0;
  border-collapse: collapse;
  font-size: 13px;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  padding: 10px 12px;
  border-bottom: 1px solid rgba(20, 34, 51, 0.08);
  text-align: left;
}

.markdown-body :deep(th) {
  color: #5a6879;
  font-weight: 600;
}

.markdown-body :deep(code) {
  padding: 2px 6px;
  border-radius: 8px;
  background: rgba(20, 34, 51, 0.08);
  font-family: 'SFMono-Regular', 'JetBrains Mono', 'Menlo', monospace;
  font-size: 12px;
}

.markdown-body :deep(.code-block) {
  overflow: hidden;
  margin: 14px 0;
  border-radius: 18px;
  background: #101923;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.04);
}

.markdown-body :deep(.code-block__head) {
  padding: 10px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.62);
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.markdown-body :deep(.code-block pre) {
  margin: 0;
  padding: 16px;
  overflow-x: auto;
}

.markdown-body :deep(.code-block pre code) {
  padding: 0;
  border-radius: 0;
  background: transparent;
  color: #eef3f8;
  font-size: 12px;
  line-height: 1.7;
}

.message-row.user .markdown-body :deep(code) {
  background: rgba(255, 255, 255, 0.14);
  color: #fff;
}

@media (max-width: 1100px) {
  .workspace-page {
    height: auto;
    min-height: 100vh;
    overflow: auto;
  }

  .floating-actions {
    top: 12px;
    right: 12px;
  }

  .workspace-page.artifact-open .workspace-shell {
    grid-template-columns: 1fr;
  }

  .workspace-shell,
  .chat-pane,
  .artifact-pane {
    height: auto;
  }

  .chat-pane {
    min-height: 100vh;
  }

  .artifact-pane {
    min-height: 560px;
    padding: 0 20px 20px;
  }
}

@media (max-width: 720px) {
  .chat-pane {
    padding: 14px 14px 20px;
  }

  .landing {
    padding: 18px 0 32px;
  }

  .floating-actions {
    left: 14px;
    right: 14px;
    justify-content: flex-end;
  }

  .composer-shell {
    flex-direction: column;
    align-items: stretch;
  }

  .send-btn {
    width: 100%;
  }
}
</style>
