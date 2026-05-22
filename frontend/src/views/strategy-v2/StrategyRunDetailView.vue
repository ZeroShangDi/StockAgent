<template>
  <div v-if="run" class="run-detail-page">
    <section class="hero-card">
      <div>
        <p class="eyebrow">Run Detail V2</p>
        <h1>{{ run.title }}</h1>
        <p class="description">{{ run.summary }}</p>
      </div>
      <div class="hero-actions">
        <el-tag :type="runStatusTagType(run.run_status)" effect="plain" round>
          {{ runStatusLabel(run.run_status) }}
        </el-tag>
        <el-button @click="openTask">返回任务</el-button>
        <el-button v-if="run.related_trade_review_group_name" type="primary" plain @click="router.push('/trade-review')">
          打开交割单分析
        </el-button>
      </div>
    </section>

    <section class="summary-strip">
      <article v-for="metric in run.summary_metrics" :key="metric.label" class="strip-card" :class="metric.tone || 'default'">
        <span>{{ metric.label }}</span>
        <strong>{{ metric.value }}</strong>
      </article>
    </section>

    <section class="workspace-shell">
      <main class="results-column">
        <section class="console-panel">
          <div class="section-title-row">
            <div>
              <span class="section-kicker">信号全景</span>
              <h2>这次运行最后给出了什么判断</h2>
            </div>
          </div>

          <div class="signal-grid">
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
          </div>

          <div class="table-filters">
            <button type="button" :class="['filter-pill', { active: itemFilter === 'all' }]" @click="itemFilter = 'all'">全部</button>
            <button type="button" :class="['filter-pill', { active: itemFilter === 'positive' }]" @click="itemFilter = 'positive'">正向</button>
            <button type="button" :class="['filter-pill', { active: itemFilter === 'review' }]" @click="itemFilter = 'review'">待复核</button>
            <button type="button" :class="['filter-pill', { active: itemFilter === 'skipped' }]" @click="itemFilter = 'skipped'">无动作/跳过</button>
          </div>

          <el-table :data="filteredItems" stripe class="result-table">
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
            <el-table-column label="标签" min-width="160">
              <template #default="{ row }">
                <div class="tag-cloud">
                  <span v-for="tag in row.tags" :key="tag" class="mini-tag">{{ tag }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="reason" label="原因" min-width="260" show-overflow-tooltip />
            <el-table-column prop="action_result" label="动作结果" min-width="180" />
            <el-table-column label="状态写回" width="110">
              <template #default="{ row }">
                {{ row.state_writeback ? '已写回' : '未写回' }}
              </template>
            </el-table-column>
          </el-table>
        </section>
      </main>

      <aside class="inspector-column">
        <section class="console-panel">
          <div class="section-title-row compact">
            <div>
              <span class="section-kicker">运行上下文</span>
              <h3>{{ sceneLabels[run.scene_type] }}</h3>
            </div>
          </div>
          <div class="context-list">
            <div class="context-row">
              <span>策略</span>
              <strong>{{ run.strategy_name }}</strong>
            </div>
            <div class="context-row">
              <span>触发来源</span>
              <strong>{{ triggerSourceLabel(run.trigger_source) }}</strong>
            </div>
            <div class="context-row">
              <span>开始时间</span>
              <strong>{{ run.started_at }}</strong>
            </div>
            <div class="context-row" v-if="run.finished_at">
              <span>完成时间</span>
              <strong>{{ run.finished_at }}</strong>
            </div>
            <div class="context-row" v-if="run.related_trade_review_group_name">
              <span>关联交割单</span>
              <strong>{{ run.related_trade_review_group_name }}</strong>
            </div>
          </div>
        </section>

        <section class="console-panel">
          <div class="section-title-row compact">
            <div>
              <span class="section-kicker">动作复核</span>
              <h3>这轮执行留下了什么</h3>
            </div>
          </div>
          <div class="review-grid">
            <article class="review-card">
              <span>状态写回</span>
              <strong>{{ stateWritebackCount }}</strong>
              <small>个对象已写入跨日状态</small>
            </article>
            <article class="review-card">
              <span>需复核对象</span>
              <strong>{{ reviewNeededCount }}</strong>
              <small>动作结果里带人工确认意味</small>
            </article>
            <article class="review-card">
              <span>无动作 / 跳过</span>
              <strong>{{ skippedCount }}</strong>
              <small>便于核对冷却、过滤和未命中情况</small>
            </article>
          </div>
          <div v-if="run.next_action_hint" class="next-action-card">
            <strong>下一步建议</strong>
            <p>{{ run.next_action_hint }}</p>
          </div>
        </section>

        <section class="console-panel">
          <div class="section-title-row compact">
            <div>
              <span class="section-kicker">重点对象</span>
              <h3>适合先看的明细</h3>
            </div>
          </div>
          <div class="focus-list">
            <article v-for="item in prioritizedItems" :key="item.item_id" class="focus-card">
              <div class="focus-head">
                <strong>{{ item.entity_name }}</strong>
                <span :class="['signal-pill', signalClass(item.signal)]">{{ signalLabel(item.signal) }}</span>
              </div>
              <p>{{ item.reason }}</p>
              <small>{{ item.action_result }}</small>
            </article>
          </div>
        </section>
      </aside>
    </section>
  </div>
  <el-empty v-else description="运行记录不存在或尚未生成" />
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getRunItems, getTaskRun, STRATEGY_SCENE_LABELS } from '@/mocks/strategyV2'
import type { StrategyRunStatus, StrategySignalValue, StrategyTaskRun, StrategyTaskRunItem } from '@/types/strategy-v2'

const route = useRoute()
const router = useRouter()

const run = ref<StrategyTaskRun | null>(null)
const items = ref<StrategyTaskRunItem[]>([])
const itemFilter = ref<'all' | 'positive' | 'review' | 'skipped'>('all')
const sceneLabels = STRATEGY_SCENE_LABELS

const stateWritebackCount = computed(() => items.value.filter((item) => item.state_writeback).length)
const reviewNeededCount = computed(() => items.value.filter((item) => item.action_result.includes('待') || item.action_result.includes('建议')).length)
const skippedCount = computed(() => items.value.filter((item) => item.action_result.includes('无动作') || item.action_result.includes('跳过')).length)
const filteredItems = computed(() => {
  if (itemFilter.value === 'positive') return items.value.filter((item) => item.signal === 1)
  if (itemFilter.value === 'review') return items.value.filter((item) => item.action_result.includes('待') || item.action_result.includes('建议'))
  if (itemFilter.value === 'skipped') return items.value.filter((item) => item.action_result.includes('无动作') || item.action_result.includes('跳过'))
  return items.value
})
const prioritizedItems = computed(() => {
  return [...items.value]
    .sort((a, b) => b.score - a.score)
    .slice(0, 4)
})

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
  --surface-1: linear-gradient(180deg, rgba(252, 253, 255, 0.98), rgba(246, 248, 252, 0.95));
  --line-soft: rgba(15, 23, 42, 0.08);
  --line-strong: rgba(42, 82, 190, 0.22);
  --accent: #2f5fd0;
  --ink-soft: #5b6473;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.hero-card,
.strip-card,
.signal-card,
.console-panel,
.review-card,
.focus-card {
  border: 1px solid var(--line-soft);
  background: var(--surface-1);
  box-shadow: 0 18px 38px rgba(15, 23, 42, 0.07);
}

.hero-card {
  border-radius: 28px;
  padding: 28px;
  display: flex;
  justify-content: space-between;
  gap: 24px;
}

.eyebrow,
.section-kicker {
  margin: 0 0 10px;
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #6274b7;
}

.hero-card h1,
.section-title-row h2 {
  margin: 0;
  font-size: 34px;
}

.description,
.next-action-card p,
.focus-card p {
  line-height: 1.7;
  color: var(--ink-soft);
}

.hero-actions {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  flex-wrap: wrap;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.strip-card,
.signal-card,
.review-card {
  border-radius: 20px;
  padding: 16px 18px;
}

.strip-card span,
.signal-card span,
.context-row span,
.review-card span,
.focus-card small {
  display: block;
  color: var(--ink-soft);
  font-size: 12px;
}

.strip-card strong,
.signal-card strong,
.review-card strong {
  display: block;
  margin-top: 8px;
  font-size: 24px;
}

.strip-card.positive strong,
.signal-card.positive strong {
  color: #16a34a;
}

.strip-card.negative strong,
.signal-card.negative strong {
  color: #dc2626;
}

.strip-card.warning strong {
  color: #d97706;
}

.workspace-shell {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 18px;
}

.console-panel {
  border-radius: 28px;
  padding: 20px;
}

.section-title-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 16px;
}

.section-title-row h2,
.section-title-row h3 {
  margin: 0;
}

.section-title-row h3 {
  font-size: 20px;
}

.table-filters,
.tag-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.table-filters {
  margin: 0 0 16px;
}

.filter-pill,
.mini-tag {
  border-radius: 999px;
  border: 1px solid var(--line-soft);
  background: rgba(255, 255, 255, 0.82);
  padding: 6px 10px;
  font-size: 12px;
  color: var(--ink-soft);
}

.filter-pill.active {
  border-color: var(--line-strong);
  background: rgba(47, 95, 208, 0.1);
  color: var(--accent);
}

.signal-grid,
.review-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.context-list,
.focus-list {
  display: grid;
  gap: 12px;
}

.context-row {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line-soft);
}

.context-row:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.context-row strong {
  display: block;
  margin-top: 6px;
  line-height: 1.6;
}

.review-card small {
  display: block;
  margin-top: 6px;
}

.next-action-card {
  margin-top: 14px;
  border-radius: 18px;
  border: 1px solid var(--line-strong);
  background: rgba(47, 95, 208, 0.08);
  padding: 14px 16px;
}

.focus-card {
  border-radius: 18px;
  padding: 14px;
}

.focus-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.focus-head strong {
  display: block;
}

.focus-card small {
  margin-top: 10px;
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

@media (max-width: 1200px) {
  .summary-strip,
  .workspace-shell,
  .signal-grid,
  .review-grid {
    grid-template-columns: 1fr;
  }

  .hero-card,
  .section-title-row {
    flex-direction: column;
  }
}
</style>
