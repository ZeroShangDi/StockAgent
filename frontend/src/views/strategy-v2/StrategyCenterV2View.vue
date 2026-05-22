<template>
  <div class="strategy-v2-page">
    <section class="hero-card">
      <div>
        <p class="eyebrow">Strategy V2</p>
        <h1>策略中心 V2</h1>
        <p class="description">
          这里先把新策略体系的前端骨架搭起来。策略只负责输出统一信号，任务场景负责调度、动作和结果承接。
        </p>
      </div>
      <div class="hero-actions">
        <el-button type="primary" @click="goTaskCenter()">查看任务中心</el-button>
        <el-button @click="goTaskCenter('listen')">新建监听任务</el-button>
      </div>
    </section>

    <section class="stats-grid">
      <article class="stat-card">
        <span>内置策略</span>
        <strong>{{ overview.strategyCount }}</strong>
      </article>
      <article class="stat-card">
        <span>支持跨日状态</span>
        <strong>{{ overview.statefulCount }}</strong>
      </article>
      <article class="stat-card">
        <span>支持场景数</span>
        <strong>{{ uniqueSceneCount }}</strong>
      </article>
      <article class="stat-card">
        <span>现有任务数</span>
        <strong>{{ overview.taskCount }}</strong>
      </article>
    </section>

    <section class="workspace-grid">
      <aside class="list-card">
        <div class="toolbar">
          <el-input v-model="keyword" clearable placeholder="搜索策略名称 / 标签" />
          <el-select v-model="sceneFilter" placeholder="按场景筛选">
            <el-option label="全部场景" value="all" />
            <el-option v-for="item in sceneOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </div>

        <button
          v-for="strategy in filteredStrategies"
          :key="strategy.strategy_key"
          type="button"
          :class="['strategy-item', { active: strategy.strategy_key === selectedStrategyKey }]"
          @click="selectedStrategyKey = strategy.strategy_key"
        >
          <div class="strategy-item-head">
            <strong>{{ strategy.name }}</strong>
            <el-tag size="small" effect="plain" round>
              v{{ strategy.version }}
            </el-tag>
          </div>
          <p>{{ strategy.description }}</p>
          <div class="tag-row">
            <span v-for="tag in strategy.tags" :key="tag" class="tag-chip">{{ tag }}</span>
          </div>
        </button>
      </aside>

      <section class="detail-card" v-if="selectedStrategy">
        <header class="detail-header">
          <div>
            <p class="detail-type">纯函数策略定义</p>
            <h2>{{ selectedStrategy.name }}</h2>
            <p class="detail-desc">{{ selectedStrategy.description }}</p>
          </div>
          <div class="detail-actions">
            <el-button type="primary" @click="goTaskCenter('scan', selectedStrategy.strategy_key)">创建选股任务</el-button>
            <el-button @click="goTaskCenter('listen', selectedStrategy.strategy_key)">创建监听任务</el-button>
          </div>
        </header>

        <section class="info-section">
          <div class="section-head">
            <h3>支持场景</h3>
            <el-tag :type="selectedStrategy.supports_state ? 'success' : 'info'" effect="plain" round>
              {{ selectedStrategy.supports_state ? '支持跨日状态' : '无状态' }}
            </el-tag>
          </div>
          <div class="scene-row">
            <span v-for="scene in selectedStrategy.supported_scenes" :key="scene" class="scene-pill">
              {{ strategySceneLabels[scene] }}
            </span>
          </div>
        </section>

        <section class="info-section">
          <h3>参数定义</h3>
          <div class="param-grid">
            <article v-for="param in selectedStrategy.param_schema" :key="param.key" class="param-card">
              <div class="param-title-row">
                <strong>{{ param.label }}</strong>
                <code>{{ param.key }}</code>
              </div>
              <p>{{ param.description }}</p>
              <div class="param-meta">
                <span>{{ typeLabel(param.type) }}</span>
                <span>默认值 {{ param.default }}</span>
              </div>
            </article>
          </div>
        </section>

        <section class="info-section">
          <h3>统一输出预览</h3>
          <div class="signal-grid">
            <article v-for="sample in selectedStrategy.sample_outputs" :key="sample.title" class="signal-card">
              <div class="signal-head">
                <span :class="['signal-chip', signalClass(sample.signal)]">{{ signalLabel(sample.signal) }}</span>
                <strong>{{ sample.title }}</strong>
              </div>
              <p>{{ sample.summary }}</p>
            </article>
          </div>
        </section>
      </section>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getStrategyV2Overview, listStrategyDefinitions, STRATEGY_SCENE_LABELS } from '@/mocks/strategyV2'
import type { StrategyDefinition, StrategySceneType, StrategySignalValue } from '@/types/strategy-v2'

const router = useRouter()

const strategies = ref<StrategyDefinition[]>([])
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

const uniqueSceneCount = computed(() => {
  return new Set(strategies.value.flatMap((item) => item.supported_scenes)).size
})

onMounted(async () => {
  strategies.value = await listStrategyDefinitions()
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
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.hero-card,
.list-card,
.detail-card,
.stat-card {
  border: 1px solid var(--el-border-color-lighter);
  background:
    radial-gradient(circle at top right, rgba(46, 125, 255, 0.12), transparent 28%),
    linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(246, 248, 252, 0.96));
  box-shadow: 0 18px 44px rgba(15, 23, 42, 0.08);
}

.hero-card {
  border-radius: 28px;
  padding: 28px;
  display: flex;
  justify-content: space-between;
  gap: 24px;
}

.eyebrow {
  margin: 0 0 10px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.18em;
  color: #4b6cb7;
}

.hero-card h1 {
  margin: 0;
  font-size: 34px;
}

.description {
  max-width: 780px;
  margin: 10px 0 0;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}

.hero-actions {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.stat-card {
  border-radius: 22px;
  padding: 18px 20px;
}

.stat-card span {
  display: block;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.stat-card strong {
  display: block;
  margin-top: 8px;
  font-size: 28px;
}

.workspace-grid {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 18px;
}

.list-card,
.detail-card {
  border-radius: 24px;
  padding: 20px;
}

.toolbar {
  display: grid;
  gap: 12px;
  margin-bottom: 16px;
}

.strategy-item {
  width: 100%;
  margin-bottom: 12px;
  padding: 16px;
  border-radius: 18px;
  border: 1px solid var(--el-border-color);
  background: rgba(255, 255, 255, 0.76);
  text-align: left;
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}

.strategy-item:hover,
.strategy-item.active {
  transform: translateY(-2px);
  border-color: rgba(46, 125, 255, 0.4);
  box-shadow: 0 12px 24px rgba(46, 125, 255, 0.12);
}

.strategy-item-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.strategy-item p {
  margin: 8px 0 10px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.tag-row,
.scene-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag-chip,
.scene-pill {
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(46, 125, 255, 0.1);
  color: #305ec9;
  font-size: 12px;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: flex-start;
  margin-bottom: 20px;
}

.detail-type {
  margin: 0 0 8px;
  font-size: 12px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: #5f7ed6;
}

.detail-header h2 {
  margin: 0;
  font-size: 28px;
}

.detail-desc {
  margin: 10px 0 0;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}

.detail-actions {
  display: flex;
  gap: 10px;
}

.info-section + .info-section {
  margin-top: 24px;
}

.info-section h3 {
  margin: 0 0 14px;
  font-size: 18px;
}

.section-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-bottom: 14px;
}

.param-grid,
.signal-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.param-card,
.signal-card {
  border-radius: 18px;
  border: 1px solid var(--el-border-color-lighter);
  background: rgba(255, 255, 255, 0.82);
  padding: 16px;
}

.param-title-row,
.signal-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.param-card p,
.signal-card p {
  margin: 10px 0 0;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.param-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.signal-chip {
  min-width: 34px;
  text-align: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.signal-chip.positive {
  background: rgba(34, 197, 94, 0.14);
  color: #1f9f57;
}

.signal-chip.neutral {
  background: rgba(148, 163, 184, 0.18);
  color: #526072;
}

.signal-chip.negative {
  background: rgba(239, 68, 68, 0.14);
  color: #d14343;
}

@media (max-width: 1100px) {
  .stats-grid,
  .workspace-grid,
  .param-grid,
  .signal-grid {
    grid-template-columns: 1fr;
  }

  .hero-card,
  .detail-header {
    flex-direction: column;
  }
}
</style>
