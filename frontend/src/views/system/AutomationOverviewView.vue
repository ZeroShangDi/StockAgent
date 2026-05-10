<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { systemApi } from '@/api'
import type {
  AutomationOverviewItem,
  AutomationOverviewResponse,
  AutomationSectionKey,
} from '@/api/types'

const loading = ref(true)
const overview = ref<AutomationOverviewResponse | null>(null)

const sections = computed(() => {
  const data = overview.value?.sections
  return [
    {
      key: 'scheduled' as AutomationSectionKey,
      title: '定时任务',
      description: '由 DataSyncNode 通过 cron 调度自动执行。',
      items: data?.scheduled || [],
    },
    {
      key: 'daemon' as AutomationSectionKey,
      title: '持续运行',
      description: '节点启动后持续常驻执行，不依赖 cron。',
      items: data?.daemon || [],
    },
    {
      key: 'event' as AutomationSectionKey,
      title: '事件驱动',
      description: '在监听命中或访问股池等事件发生时自动触发。',
      items: data?.event || [],
    },
    {
      key: 'standby' as AutomationSectionKey,
      title: '预留未启用',
      description: '代码已存在，但当前未注册到自动运行主链路。',
      items: data?.standby || [],
    },
  ]
})

async function loadOverview() {
  loading.value = true
  try {
    overview.value = await systemApi.getAutomationOverview()
  } catch (error) {
    console.error('加载自动任务总览失败', error)
    ElMessage.error('加载自动任务总览失败')
  } finally {
    loading.value = false
  }
}

function getTypeLabel(item: AutomationOverviewItem): string {
  if (item.trigger_type === 'cron') return 'Cron'
  if (item.trigger_type === 'interval') return '轮询'
  return '事件'
}

onMounted(() => {
  loadOverview()
})
</script>

<template>
  <div class="automation-page">
    <section class="hero card">
      <div class="hero-copy">
        <p class="eyebrow">Automation Snapshot</p>
        <h1>自动任务总览</h1>
        <p class="description">
          这里只展示当前项目里已经接上的定时任务、持续运行自动机制和事件驱动自动流程，不提供任何操作入口。
        </p>
        <p v-if="overview" class="generated-at">
          生成时间：{{ new Date(overview.generated_at).toLocaleString('zh-CN') }}
        </p>
      </div>

      <button class="refresh-btn" type="button" @click="loadOverview">
        <el-icon><Refresh /></el-icon>
        重新读取
      </button>
    </section>

    <section v-if="overview" class="summary-grid">
      <article class="summary-card primary">
        <span class="summary-label">当前总数</span>
        <strong>{{ overview.summary.total_active }}</strong>
      </article>
      <article class="summary-card">
        <span class="summary-label">定时任务</span>
        <strong>{{ overview.summary.scheduled }}</strong>
      </article>
      <article class="summary-card">
        <span class="summary-label">持续运行</span>
        <strong>{{ overview.summary.daemon }}</strong>
      </article>
      <article class="summary-card">
        <span class="summary-label">事件驱动</span>
        <strong>{{ overview.summary.event }}</strong>
      </article>
      <article class="summary-card muted">
        <span class="summary-label">预留未启用</span>
        <strong>{{ overview.summary.standby }}</strong>
      </article>
    </section>

    <section v-if="loading" class="loading-grid">
      <div v-for="index in 4" :key="index" class="loading-card card" />
    </section>

    <section v-else class="section-list">
      <article v-for="section in sections" :key="section.key" class="section-card card">
        <header class="section-header">
          <div>
            <h2>{{ section.title }}</h2>
            <p>{{ section.description }}</p>
          </div>
          <span class="section-count">{{ section.items.length }} 项</span>
        </header>

        <div v-if="section.items.length === 0" class="empty-state">
          当前没有可展示的条目。
        </div>

        <div v-else class="item-grid">
          <article v-for="item in section.items" :key="item.key" class="item-card">
            <div class="item-topline">
              <strong>{{ item.name }}</strong>
              <span class="trigger-tag">{{ getTypeLabel(item) }}</span>
            </div>
            <p class="item-desc">{{ item.description }}</p>
            <dl class="item-meta">
              <div>
                <dt>触发方式</dt>
                <dd>{{ item.trigger_value }}</dd>
              </div>
              <div>
                <dt>来源</dt>
                <dd>{{ item.source }}</dd>
              </div>
              <div>
                <dt>启动时运行</dt>
                <dd>{{ item.run_at_startup ? '是' : '否' }}</dd>
              </div>
              <div>
                <dt>代码位置</dt>
                <dd class="mono">{{ item.file }}</dd>
              </div>
            </dl>
          </article>
        </div>
      </article>
    </section>
  </div>
</template>

<style scoped lang="scss">
.automation-page {
  display: grid;
  gap: 20px;
  padding: 1.5rem;
}

.card {
  border-radius: 24px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background:
    radial-gradient(circle at top right, rgba(14, 165, 233, 0.12), transparent 32%),
    linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.98));
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.07);
}

.hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 28px 32px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #0369a1;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

h1,
h2 {
  margin: 0;
  color: #0f172a;
}

.description,
.generated-at,
.section-header p,
.item-desc,
.empty-state {
  margin: 10px 0 0;
  color: #475569;
  line-height: 1.7;
}

.refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: none;
  border-radius: 999px;
  padding: 12px 18px;
  background: #0f172a;
  color: #fff;
  cursor: pointer;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 16px;
}

.summary-card {
  display: grid;
  gap: 8px;
  padding: 20px 22px;
  border-radius: 20px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  background: rgba(255, 255, 255, 0.92);
}

.summary-card.primary {
  background: linear-gradient(160deg, rgba(14, 165, 233, 0.96), rgba(2, 132, 199, 0.94));
  color: #fff;
}

.summary-card.muted {
  background: rgba(241, 245, 249, 0.96);
}

.summary-label {
  font-size: 13px;
  color: inherit;
  opacity: 0.8;
}

.summary-card strong {
  font-size: 30px;
  line-height: 1;
}

.section-list {
  display: grid;
  gap: 18px;
}

.section-card {
  padding: 22px 24px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 18px;
}

.section-count {
  align-self: flex-start;
  padding: 8px 12px;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.76);
  color: #334155;
  font-size: 13px;
  font-weight: 600;
}

.item-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 14px;
}

.item-card {
  padding: 18px;
  border-radius: 18px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  background: rgba(255, 255, 255, 0.9);
}

.item-topline {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.trigger-tag {
  flex-shrink: 0;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(14, 165, 233, 0.12);
  color: #0369a1;
  font-size: 12px;
  font-weight: 700;
}

.item-meta {
  display: grid;
  gap: 12px;
  margin: 14px 0 0;
}

.item-meta div {
  display: grid;
  gap: 4px;
}

.item-meta dt {
  color: #64748b;
  font-size: 12px;
}

.item-meta dd {
  margin: 0;
  color: #0f172a;
  line-height: 1.6;
}

.mono {
  font-family: 'SFMono-Regular', 'JetBrains Mono', monospace;
  font-size: 12px;
  word-break: break-all;
}

.loading-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.loading-card {
  min-height: 180px;
}

@media (max-width: 1200px) {
  .summary-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .hero,
  .section-header {
    flex-direction: column;
  }

  .summary-grid,
  .loading-grid {
    grid-template-columns: 1fr;
  }
}
</style>
