<template>
  <div v-if="run" class="run-detail-page">
    <section class="hero-card">
      <div>
        <p class="eyebrow">Run Detail V2</p>
        <h1>{{ run.title }}</h1>
        <p class="description">{{ run.summary }}</p>
      </div>
      <div class="hero-actions">
        <el-button @click="openTask">返回任务</el-button>
        <el-button v-if="run.related_trade_review_group_name" type="primary" plain @click="router.push('/trade-review')">
          打开交割单分析
        </el-button>
      </div>
    </section>

    <section class="summary-grid">
      <article v-for="metric in run.summary_metrics" :key="metric.label" class="summary-card" :class="metric.tone || 'default'">
        <span>{{ metric.label }}</span>
        <strong>{{ metric.value }}</strong>
      </article>
    </section>

    <section class="signal-grid">
      <article class="signal-card positive">
        <span>正向信号</span>
        <strong>{{ run.signal_breakdown.positive }}</strong>
      </article>
      <article class="signal-card neutral">
        <span>中性信号</span>
        <strong>{{ run.signal_breakdown.neutral }}</strong>
      </article>
      <article class="signal-card negative">
        <span>负向信号</span>
        <strong>{{ run.signal_breakdown.negative }}</strong>
      </article>
    </section>

    <section class="panel-card">
      <header class="panel-header">
        <div>
          <h2>运行上下文</h2>
          <p>{{ sceneLabels[run.scene_type] }} · {{ run.strategy_name }} · {{ run.started_at }}</p>
        </div>
        <el-tag :type="runStatusTagType(run.run_status)" effect="plain" round>
          {{ runStatusLabel(run.run_status) }}
        </el-tag>
      </header>
      <div class="context-meta">
        <span>触发来源：{{ triggerSourceLabel(run.trigger_source) }}</span>
        <span v-if="run.finished_at">完成时间：{{ run.finished_at }}</span>
        <span v-if="run.related_trade_review_group_name">关联交割单：{{ run.related_trade_review_group_name }}</span>
      </div>
      <div v-if="run.next_action_hint" class="next-action-card">
        <strong>下一步建议</strong>
        <p>{{ run.next_action_hint }}</p>
      </div>
    </section>

    <section class="panel-card">
      <header class="panel-header">
        <div>
          <h2>标的明细</h2>
          <p>这里展示这次运行中每个对象的统一信号、强度和动作结果。</p>
        </div>
      </header>
      <el-table :data="items" stripe>
        <el-table-column prop="entity_key" label="标的代码" width="140" />
        <el-table-column prop="entity_name" label="名称" min-width="140" />
        <el-table-column label="信号" width="100">
          <template #default="{ row }">
            <span :class="['signal-pill', signalClass(row.signal)]">{{ signalLabel(row.signal) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="强度" width="100">
          <template #default="{ row }">
            {{ Math.round(row.score * 100) }}%
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="原因" min-width="280" show-overflow-tooltip />
        <el-table-column label="标签" min-width="180">
          <template #default="{ row }">
            <div class="tag-row">
              <span v-for="tag in row.tags" :key="tag" class="tag-chip">{{ tag }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="action_result" label="动作结果" min-width="180" />
        <el-table-column label="状态写回" width="110">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="row.state_writeback ? 'success' : 'info'">
              {{ row.state_writeback ? '已写回' : '无' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
  <el-empty v-else description="运行记录不存在或尚未生成" />
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getRunItems, getTaskRun, STRATEGY_SCENE_LABELS } from '@/mocks/strategyV2'
import type { StrategyRunStatus, StrategySignalValue, StrategyTaskRun, StrategyTaskRunItem } from '@/types/strategy-v2'

const route = useRoute()
const router = useRouter()

const run = ref<StrategyTaskRun | null>(null)
const items = ref<StrategyTaskRunItem[]>([])
const sceneLabels = STRATEGY_SCENE_LABELS

onMounted(async () => {
  const runId = String(route.params.runId || '')
  run.value = (await getTaskRun(runId)) || null
  items.value = await getRunItems(runId)
})

function openTask(): void {
  if (!run.value) return
  router.push({ name: 'StrategyTaskDetailV2', params: { taskId: run.value.task_id } })
}

function runStatusLabel(status: StrategyRunStatus): string {
  if (status === 'success') return '成功'
  if (status === 'partial_success') return '部分成功'
  if (status === 'failed') return '失败'
  return '运行中'
}

function runStatusTagType(status: StrategyRunStatus): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'success') return 'success'
  if (status === 'partial_success') return 'warning'
  if (status === 'failed') return 'danger'
  return 'info'
}

function triggerSourceLabel(value: string): string {
  if (value === 'manual') return '手动触发'
  if (value === 'schedule') return '定时触发'
  return '历史回放'
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
</script>

<style scoped>
.run-detail-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.hero-card,
.summary-card,
.signal-card,
.panel-card {
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
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #4b6cb7;
}

.hero-card h1 {
  margin: 0;
  font-size: 34px;
}

.description {
  margin: 10px 0 0;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}

.hero-actions {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.summary-grid,
.signal-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.summary-card,
.signal-card {
  border-radius: 22px;
  padding: 18px 20px;
}

.summary-card span,
.signal-card span {
  display: block;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.summary-card strong,
.signal-card strong {
  display: block;
  margin-top: 8px;
  font-size: 28px;
}

.summary-card.positive strong,
.signal-card.positive strong {
  color: #16a34a;
}

.summary-card.negative strong,
.signal-card.negative strong {
  color: #dc2626;
}

.summary-card.warning strong {
  color: #d97706;
}

.panel-card {
  border-radius: 24px;
  padding: 20px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 16px;
}

.panel-header h2 {
  margin: 0;
  font-size: 20px;
}

.panel-header p,
.next-action-card p {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.context-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.next-action-card {
  margin-top: 16px;
  border-radius: 18px;
  border: 1px solid rgba(46, 125, 255, 0.2);
  background: rgba(46, 125, 255, 0.08);
  padding: 14px 16px;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag-chip {
  padding: 4px 9px;
  border-radius: 999px;
  background: rgba(46, 125, 255, 0.1);
  color: #305ec9;
  font-size: 12px;
}

.signal-pill {
  min-width: 34px;
  padding: 4px 10px;
  border-radius: 999px;
  text-align: center;
  font-size: 12px;
  font-weight: 700;
}

.signal-pill.positive {
  background: rgba(34, 197, 94, 0.14);
  color: #1f9f57;
}

.signal-pill.neutral {
  background: rgba(148, 163, 184, 0.18);
  color: #526072;
}

.signal-pill.negative {
  background: rgba(239, 68, 68, 0.14);
  color: #d14343;
}

@media (max-width: 1100px) {
  .summary-grid,
  .signal-grid {
    grid-template-columns: 1fr;
  }

  .hero-card,
  .panel-header {
    flex-direction: column;
  }
}
</style>
