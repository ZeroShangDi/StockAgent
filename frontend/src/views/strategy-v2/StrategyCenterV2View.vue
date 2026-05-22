<template>
  <div class="strategy-v2-page">
    <section class="hero-card">
      <div class="hero-copy">
        <p class="eyebrow">Strategy V2</p>
        <h1>策略定义台</h1>
        <p class="description">
          V2 先把“策略”和“任务”拆开。策略只负责判断与统一信号，任务负责目标范围、调度、动作和最终结果承接。
        </p>
      </div>
      <div class="hero-flow">
        <div class="flow-node">
          <span>01</span>
          <strong>定义策略</strong>
          <small>纯函数 · 统一输出</small>
        </div>
        <div class="flow-arrow">→</div>
        <div class="flow-node">
          <span>02</span>
          <strong>组装任务</strong>
          <small>选股 / 监听 / 回测 / 模拟</small>
        </div>
        <div class="flow-arrow">→</div>
        <div class="flow-node accent">
          <span>03</span>
          <strong>运行与动作</strong>
          <small>通知 · 入池 · 流转 · 模拟成交</small>
        </div>
      </div>
    </section>

    <section class="stats-grid">
      <article class="stat-card">
        <span>策略总数</span>
        <strong>{{ overview.strategyCount }}</strong>
        <small>当前内置目录</small>
      </article>
      <article class="stat-card">
        <span>可记忆策略</span>
        <strong>{{ overview.statefulCount }}</strong>
        <small>支持跨日状态</small>
      </article>
      <article class="stat-card">
        <span>挂载任务</span>
        <strong>{{ overview.taskCount }}</strong>
        <small>策略被任务复用</small>
      </article>
      <article class="stat-card">
        <span>已覆盖场景</span>
        <strong>{{ uniqueSceneCount }}</strong>
        <small>定义和执行已分层</small>
      </article>
    </section>

    <section class="workspace-shell">
      <aside class="library-panel">
        <div class="panel-head">
          <div>
            <span class="panel-label">策略目录</span>
            <h2>Library</h2>
          </div>
        </div>

        <div class="filter-stack">
          <el-input v-model="keyword" clearable placeholder="搜索策略名称 / 标签" />
          <el-select v-model="sceneFilter" placeholder="按场景过滤">
            <el-option label="全部场景" value="all" />
            <el-option v-for="item in sceneOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </div>

        <div class="strategy-list">
          <button
            v-for="strategy in filteredStrategies"
            :key="strategy.strategy_key"
            type="button"
            :class="['strategy-row', { active: strategy.strategy_key === selectedStrategyKey }]"
            @click="selectedStrategyKey = strategy.strategy_key"
          >
            <div class="strategy-row-head">
              <strong>{{ strategy.name }}</strong>
              <span class="version-badge">v{{ strategy.version }}</span>
            </div>
            <p>{{ strategy.description }}</p>
            <div class="mini-meta">
              <span>{{ strategy.supports_state ? '有状态' : '无状态' }}</span>
              <span>{{ strategy.supported_scenes.length }} 个场景</span>
            </div>
          </button>
        </div>
      </aside>

      <section v-if="selectedStrategy" class="definition-stage">
        <header class="definition-header">
          <div>
            <p class="detail-type">Pure Strategy Definition</p>
            <h2>{{ selectedStrategy.name }}</h2>
            <p class="detail-desc">{{ selectedStrategy.description }}</p>
          </div>
          <div class="header-actions">
            <el-button type="primary" @click="goTaskCenter('scan', selectedStrategy.strategy_key)">创建选股任务</el-button>
            <el-button @click="goTaskCenter('listen', selectedStrategy.strategy_key)">创建监听任务</el-button>
          </div>
        </header>

        <div class="definition-grid">
          <section class="console-panel signal-panel">
            <div class="section-title-row">
              <div>
                <span class="section-kicker">核心语义</span>
                <h3>统一信号，不直接执行业务动作</h3>
              </div>
              <el-tag :type="selectedStrategy.supports_state ? 'success' : 'info'" effect="plain" round>
                {{ selectedStrategy.supports_state ? '支持跨日状态' : '当前为无状态策略' }}
              </el-tag>
            </div>

            <div class="signal-ladder">
              <article
                v-for="sample in selectedStrategy.sample_outputs"
                :key="sample.title"
                class="signal-lane"
                :class="signalClass(sample.signal)"
              >
                <div class="signal-badge">{{ signalLabel(sample.signal) }}</div>
                <div>
                  <strong>{{ sample.title }}</strong>
                  <p>{{ sample.summary }}</p>
                </div>
              </article>
            </div>

            <div class="principle-strip">
              <span>策略输出：`1 / 0 / -1`</span>
              <span>任务解释：决定通知、入池、流转或模拟成交</span>
            </div>
          </section>

          <section class="console-panel deploy-panel">
            <div class="section-title-row compact">
              <div>
                <span class="section-kicker">使用方式</span>
                <h3>可挂载场景与当前落点</h3>
              </div>
            </div>

            <div class="scene-cloud">
              <span v-for="scene in selectedStrategy.supported_scenes" :key="scene" class="scene-chip">
                {{ strategySceneLabels[scene] }}
              </span>
            </div>

            <div class="usage-stack">
              <article class="usage-card emphasis">
                <span>已挂载任务</span>
                <strong>{{ relatedTasks.length }}</strong>
                <small>这个策略当前在多少个任务里被复用</small>
              </article>
              <article class="usage-card">
                <span>适合的节奏</span>
                <strong>{{ suggestedRhythm }}</strong>
                <small>从现有场景和参数结构推导</small>
              </article>
            </div>

            <div class="task-preview-list">
              <div v-if="relatedTasks.length === 0" class="empty-inline">
                这个策略还没有被挂到任何 V2 任务上，适合先创建一个监听或选股任务验证流程。
              </div>
              <button
                v-for="task in relatedTasks.slice(0, 3)"
                :key="task.task_id"
                type="button"
                class="task-preview"
                @click="openTask(task.task_id)"
              >
                <strong>{{ task.name }}</strong>
                <span>{{ strategySceneLabels[task.scene_type] }} · {{ task.target_scope_summary }}</span>
              </button>
            </div>
          </section>
        </div>

        <div class="parameter-shell">
          <section class="console-panel parameter-panel">
            <div class="section-title-row compact">
              <div>
                <span class="section-kicker">参数矩阵</span>
                <h3>策略关注什么，任务再如何覆盖它</h3>
              </div>
            </div>

            <div class="param-table">
              <article v-for="param in selectedStrategy.param_schema" :key="param.key" class="param-row">
                <div class="param-main">
                  <div class="param-head">
                    <strong>{{ param.label }}</strong>
                    <code>{{ param.key }}</code>
                  </div>
                  <p>{{ param.description }}</p>
                </div>
                <div class="param-side">
                  <span>{{ typeLabel(param.type) }}</span>
                  <strong>默认 {{ param.default }}</strong>
                </div>
              </article>
            </div>
          </section>

          <section class="console-panel guidance-panel">
            <div class="section-title-row compact">
              <div>
                <span class="section-kicker">落地建议</span>
                <h3>从定义到任务的最短路径</h3>
              </div>
            </div>

            <div class="guidance-steps">
              <article class="guidance-step">
                <span>01</span>
                <div>
                  <strong>先定义用途</strong>
                  <p>先判断它是拿来做候选扫描、盘中监听还是回测，不要一上来混用动作。</p>
                </div>
              </article>
              <article class="guidance-step">
                <span>02</span>
                <div>
                  <strong>再挂任务</strong>
                  <p>同一个策略可以被多个任务复用，但任务目标范围和动作应该分开维护。</p>
                </div>
              </article>
              <article class="guidance-step">
                <span>03</span>
                <div>
                  <strong>最后看结果</strong>
                  <p>运行页重点看信号强度、动作执行和后续建议，不要只看有没有触发。</p>
                </div>
              </article>
            </div>
          </section>
        </div>
      </section>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  getStrategyV2Overview,
  listStrategyDefinitions,
  listStrategySceneTasks,
  STRATEGY_SCENE_LABELS,
} from '@/mocks/strategyV2'
import type { StrategyDefinition, StrategySceneTask, StrategySceneType, StrategySignalValue } from '@/types/strategy-v2'

const router = useRouter()

const strategies = ref<StrategyDefinition[]>([])
const tasks = ref<StrategySceneTask[]>([])
const selectedStrategyKey = ref('')
const keyword = ref('')
const sceneFilter = ref<'all' | StrategySceneType>('all')
const overview = ref({
  strategyCount: 0,
  statefulCount: 0,
  taskCount: 0,
  activeTaskCount: 0,
  runCount: 0,
})

const strategySceneLabels = STRATEGY_SCENE_LABELS

const sceneOptions = [
  { label: STRATEGY_SCENE_LABELS.scan, value: 'scan' as const },
  { label: STRATEGY_SCENE_LABELS.listen, value: 'listen' as const },
  { label: STRATEGY_SCENE_LABELS.backtest, value: 'backtest' as const },
  { label: STRATEGY_SCENE_LABELS.sim_trade, value: 'sim_trade' as const },
]

const filteredStrategies = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  return strategies.value.filter((item) => {
    const matchesText =
      !text ||
      item.name.toLowerCase().includes(text) ||
      item.tags.some((tag) => tag.toLowerCase().includes(text))
    const matchesScene = sceneFilter.value === 'all' || item.supported_scenes.includes(sceneFilter.value)
    return matchesText && matchesScene
  })
})

const selectedStrategy = computed(() => {
  return filteredStrategies.value.find((item) => item.strategy_key === selectedStrategyKey.value)
    || strategies.value.find((item) => item.strategy_key === selectedStrategyKey.value)
    || filteredStrategies.value[0]
    || null
})

const relatedTasks = computed(() => {
  if (!selectedStrategy.value) return []
  return tasks.value.filter((item) => item.strategy_key === selectedStrategy.value?.strategy_key)
})

const uniqueSceneCount = computed(() => {
  return new Set(strategies.value.flatMap((item) => item.supported_scenes)).size
})

const suggestedRhythm = computed(() => {
  if (!selectedStrategy.value) return '-'
  if (selectedStrategy.value.supported_scenes.includes('listen')) return '盘中轮询 + 复盘复用'
  if (selectedStrategy.value.supported_scenes.includes('scan')) return '扫描候选 + 池内确认'
  return '以离线回放为主'
})

onMounted(async () => {
  strategies.value = await listStrategyDefinitions()
  tasks.value = await listStrategySceneTasks()
  overview.value = await getStrategyV2Overview()
  selectedStrategyKey.value = strategies.value[0]?.strategy_key || ''
})

function goTaskCenter(scene?: StrategySceneType, strategyKey?: string): void {
  router.push({
    name: 'StrategyTaskCenterV2',
    query: {
      ...(scene ? { scene } : {}),
      ...(strategyKey ? { strategy: strategyKey } : {}),
      autoCreate: scene && strategyKey ? '1' : undefined,
    },
  })
}

function openTask(taskId: string): void {
  router.push({ name: 'StrategyTaskDetailV2', params: { taskId } })
}

function signalLabel(value: StrategySignalValue): string {
  if (value > 0) return '1'
  if (value < 0) return '-1'
  return '0'
}

function signalClass(value: StrategySignalValue): string {
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return 'neutral'
}

function typeLabel(type: string): string {
  if (type === 'number') return '整数'
  if (type === 'float') return '浮点'
  if (type === 'boolean') return '布尔'
  if (type === 'select') return '枚举'
  return '字符串'
}
</script>

<style scoped>
.strategy-v2-page {
  --surface-1: linear-gradient(180deg, rgba(252, 253, 255, 0.98), rgba(246, 248, 252, 0.95));
  --surface-2: rgba(255, 255, 255, 0.78);
  --line-strong: rgba(42, 82, 190, 0.22);
  --line-soft: rgba(15, 23, 42, 0.08);
  --accent: #2f5fd0;
  --ink-soft: #5b6473;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.hero-card,
.stat-card,
.library-panel,
.console-panel {
  border: 1px solid var(--line-soft);
  background: var(--surface-1);
  box-shadow: 0 18px 38px rgba(15, 23, 42, 0.07);
}

.hero-card {
  border-radius: 28px;
  padding: 28px;
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: 24px;
}

.eyebrow,
.detail-type,
.panel-label,
.section-kicker {
  margin: 0 0 10px;
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #6274b7;
}

.hero-card h1,
.definition-header h2 {
  margin: 0;
  font-size: 34px;
  line-height: 1.1;
}

.description,
.detail-desc {
  margin: 12px 0 0;
  max-width: 760px;
  line-height: 1.75;
  color: var(--ink-soft);
}

.hero-flow {
  display: grid;
  grid-template-columns: repeat(5, auto);
  align-items: center;
  gap: 10px;
}

.flow-node {
  min-height: 122px;
  padding: 16px;
  border-radius: 22px;
  border: 1px solid var(--line-soft);
  background: var(--surface-2);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.flow-node.accent {
  border-color: rgba(47, 95, 208, 0.34);
  background: linear-gradient(180deg, rgba(47, 95, 208, 0.1), rgba(255, 255, 255, 0.82));
}

.flow-node span {
  font-size: 11px;
  color: var(--ink-soft);
}

.flow-node strong {
  font-size: 17px;
}

.flow-node small,
.flow-arrow {
  color: var(--ink-soft);
}

.flow-arrow {
  font-size: 24px;
  text-align: center;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.stat-card {
  border-radius: 22px;
  padding: 16px 18px;
}

.stat-card span,
.stat-card small {
  display: block;
  color: var(--ink-soft);
}

.stat-card strong {
  display: block;
  margin: 8px 0 6px;
  font-size: 28px;
}

.stat-card small {
  font-size: 12px;
}

.workspace-shell {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.library-panel {
  border-radius: 28px;
  padding: 18px;
  position: sticky;
  top: 84px;
}

.panel-head h2 {
  margin: 0;
  font-size: 24px;
}

.filter-stack {
  display: grid;
  gap: 12px;
  margin-top: 16px;
}

.strategy-list {
  margin-top: 18px;
  display: grid;
  gap: 10px;
}

.strategy-row {
  width: 100%;
  padding: 14px;
  border-radius: 18px;
  border: 1px solid var(--line-soft);
  background: rgba(255, 255, 255, 0.72);
  text-align: left;
  transition: transform 0.2s ease, border-color 0.2s ease, background-color 0.2s ease;
}

.strategy-row:hover,
.strategy-row.active {
  transform: translateY(-2px);
  border-color: var(--line-strong);
  background: linear-gradient(180deg, rgba(47, 95, 208, 0.07), rgba(255, 255, 255, 0.88));
}

.strategy-row-head,
.param-head,
.section-title-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.strategy-row p,
.guidance-step p,
.param-row p,
.signal-lane p,
.task-preview span,
.empty-inline {
  margin: 8px 0 0;
  line-height: 1.6;
  color: var(--ink-soft);
}

.version-badge,
.mini-meta span,
.scene-chip,
.task-preview span,
.principle-strip span {
  font-size: 12px;
}

.mini-meta {
  margin-top: 10px;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: var(--ink-soft);
}

.definition-stage {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.definition-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.header-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.definition-grid,
.parameter-shell {
  display: grid;
  grid-template-columns: 1.08fr 0.92fr;
  gap: 18px;
}

.console-panel {
  border-radius: 28px;
  padding: 20px;
}

.section-title-row h3 {
  margin: 0;
  font-size: 22px;
}

.section-title-row.compact h3 {
  font-size: 18px;
}

.signal-ladder,
.guidance-steps,
.task-preview-list,
.param-table {
  display: grid;
  gap: 12px;
}

.signal-lane,
.guidance-step,
.task-preview,
.param-row,
.usage-card {
  border-radius: 18px;
  border: 1px solid var(--line-soft);
  background: rgba(255, 255, 255, 0.76);
}

.signal-lane {
  padding: 14px;
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}

.signal-lane.positive {
  border-color: rgba(28, 163, 84, 0.24);
}

.signal-lane.neutral {
  border-color: rgba(100, 116, 139, 0.18);
}

.signal-lane.negative {
  border-color: rgba(220, 38, 38, 0.18);
}

.signal-badge {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  font-weight: 700;
  background: rgba(47, 95, 208, 0.1);
}

.signal-lane.positive .signal-badge {
  color: #18884b;
  background: rgba(34, 197, 94, 0.14);
}

.signal-lane.neutral .signal-badge {
  color: #526072;
  background: rgba(148, 163, 184, 0.18);
}

.signal-lane.negative .signal-badge {
  color: #d14343;
  background: rgba(239, 68, 68, 0.14);
}

.principle-strip {
  margin-top: 14px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.principle-strip span,
.scene-chip {
  padding: 7px 12px;
  border-radius: 999px;
  background: rgba(47, 95, 208, 0.1);
  color: #2f5fd0;
}

.scene-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.usage-stack {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.usage-card {
  padding: 14px;
}

.usage-card.emphasis {
  background: linear-gradient(180deg, rgba(47, 95, 208, 0.08), rgba(255, 255, 255, 0.82));
}

.usage-card span,
.usage-card small {
  display: block;
  color: var(--ink-soft);
}

.usage-card strong {
  display: block;
  margin: 8px 0;
  font-size: 24px;
}

.task-preview {
  padding: 14px;
  text-align: left;
}

.task-preview strong {
  display: block;
}

.empty-inline {
  padding: 14px;
  border-radius: 18px;
  border: 1px dashed var(--line-strong);
}

.param-row {
  padding: 14px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 138px;
  gap: 14px;
  align-items: start;
}

.param-side {
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: var(--ink-soft);
  font-size: 12px;
  text-align: right;
}

.guidance-step {
  padding: 14px;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 12px;
}

.guidance-step span {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 700;
  background: rgba(47, 95, 208, 0.1);
  color: var(--accent);
}

@media (max-width: 1200px) {
  .hero-card,
  .definition-grid,
  .parameter-shell,
  .workspace-shell,
  .stats-grid,
  .usage-stack {
    grid-template-columns: 1fr;
  }

  .hero-flow,
  .definition-header {
    flex-direction: column;
  }

  .hero-flow {
    display: flex;
  }

  .flow-arrow {
    transform: rotate(90deg);
  }

  .library-panel {
    position: static;
  }
}
</style>
