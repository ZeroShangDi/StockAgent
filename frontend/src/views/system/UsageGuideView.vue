<template>
  <div class="usage-guide-page">
    <section class="guide-hero">
      <p class="eyebrow">Usage Guide</p>
      <h1>使用说明</h1>
      <p>
        菜单按程序模块组织，实际使用时按完整交易流程推进。这里先提供一版流程地图，
        后续可以继续拆成更细的操作手册。
      </p>
    </section>

    <section class="guide-grid">
      <article v-for="step in flowSteps" :key="step.title" class="guide-card">
        <span class="step-index">{{ step.index }}</span>
        <div>
          <h2>{{ step.title }}</h2>
          <p>{{ step.description }}</p>
          <div class="module-list">
            <el-tag v-for="module in step.modules" :key="module" effect="plain" round>
              {{ module }}
            </el-tag>
          </div>
        </div>
      </article>
    </section>
  </div>
</template>

<script setup lang="ts">
const flowSteps = [
  {
    index: '01',
    title: '模式准备',
    description: '先明确要打磨的交易模式、策略规则、适用环境和失效条件。',
    modules: ['策略中心 V2', '盘感练习', '单股回测'],
  },
  {
    index: '02',
    title: '市场与择时',
    description: '判断市场环境是否适合出手，观察指数、市场宽度、板块和热点。',
    modules: ['市场晴雨表', '股票统计', '板块分析', '热点追踪'],
  },
  {
    index: '03',
    title: '机会发现',
    description: '用一句话选股、因子选股或策略任务发现候选股票，先进入候选池。',
    modules: ['一句话选股', '因子选股', '场景任务 V2'],
  },
  {
    index: '04',
    title: '候选管理',
    description: '在股池中复盘、流转、淘汰、加入监听，并逐步形成交易计划清单。',
    modules: ['股池管理', '自选股', '股池流转任务'],
  },
  {
    index: '05',
    title: '执行与监控',
    description: '通过监听任务观察计划股、持仓股和市场风险，触发通知或模拟成交。',
    modules: ['场景任务 V2', '自动任务总览', '能力状态'],
  },
  {
    index: '06',
    title: '复盘与迭代',
    description: '用交割单、运行结果和报告回顾分析表现，再反向修正模式与策略。',
    modules: ['交割单复盘', '报告回顾', '策略运行结果'],
  },
]
</script>

<style scoped>
.usage-guide-page {
  display: grid;
  gap: 18px;
}

.guide-hero,
.guide-card {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 12px;
  background: #fff;
}

.guide-hero {
  padding: 22px 24px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.guide-hero h1,
.guide-card h2 {
  margin: 0;
  color: #0f172a;
}

.guide-hero p,
.guide-card p {
  margin: 10px 0 0;
  color: #475569;
  line-height: 1.7;
}

.guide-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.guide-card {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 14px;
  padding: 18px;
}

.step-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: rgba(37, 99, 235, 0.1);
  color: #1d4ed8;
  font-weight: 800;
}

.module-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

@media (max-width: 900px) {
  .guide-grid {
    grid-template-columns: 1fr;
  }
}
</style>
