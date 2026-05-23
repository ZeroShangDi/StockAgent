<template>
  <div class="strategy-center-page">
    <section class="page-header">
      <div>
        <h1>策略中心</h1>
        <p>当前先只保留策略创建入口和策略列表，后续再按需要逐步扩展。</p>
      </div>
      <el-button type="primary" @click="handleCreateStrategy">创建策略</el-button>
    </section>

    <section class="page-body">
      <el-table :data="strategies" row-key="strategy_key" stripe class="strategy-table" empty-text="暂时还没有策略">
        <el-table-column label="策略名" min-width="220">
          <template #default="{ row }">
            <div class="strategy-name-cell">
              <strong>{{ row.name }}</strong>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="策略描述" min-width="520">
          <template #default="{ row }">
            <div class="strategy-description-cell">
              {{ row.description }}
            </div>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="140" align="right">
          <template #default="{ row }">
            <el-dropdown trigger="click" @command="(command) => handleCommand(command, row.strategy_key)">
              <el-button>
                操作
                <el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="view">查看</el-dropdown-item>
                  <el-dropdown-item command="edit">编辑</el-dropdown-item>
                  <el-dropdown-item command="delete">删除</el-dropdown-item>
                  <el-dropdown-item command="tasks">查看在运行任务</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowDown } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { listStrategyDefinitions } from '@/mocks/strategyV2'
import type { StrategyDefinition } from '@/types/strategy-v2'

const router = useRouter()

const strategies = ref<StrategyDefinition[]>([])

onMounted(async () => {
  strategies.value = await listStrategyDefinitions()
})

function handleCreateStrategy(): void {
  ElMessage.info('创建策略入口先预留，后续再接创建流程。')
}

async function handleCommand(command: string, strategyKey: string): Promise<void> {
  const strategy = strategies.value.find((item) => item.strategy_key === strategyKey)
  if (!strategy) return

  if (command === 'view') {
    ElMessage.info(`查看策略“${strategy.name}”功能后续补充。`)
    return
  }

  if (command === 'edit') {
    ElMessage.info(`编辑策略“${strategy.name}”功能后续补充。`)
    return
  }

  if (command === 'tasks') {
    router.push({
      name: 'StrategyTaskCenterV2',
      query: {
        strategy: strategy.strategy_key,
      },
    })
    return
  }

  if (command === 'delete') {
    await deleteStrategy(strategyKey, strategy.name)
  }
}

async function deleteStrategy(strategyKey: string, strategyName: string): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认删除策略“${strategyName}”吗？当前仅做前端演示删除。`,
      '删除策略',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )

    strategies.value = strategies.value.filter((item) => item.strategy_key !== strategyKey)
    ElMessage.success('策略已从当前列表移除')
  }
  catch {
    // User cancelled the confirmation dialog.
  }
}
</script>

<style scoped>
.strategy-center-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header,
.page-body {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
}

.page-header {
  padding: 20px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.page-header h1 {
  margin: 0;
  font-size: 24px;
  line-height: 1.2;
  color: #0f172a;
}

.page-header p {
  margin: 8px 0 0;
  font-size: 14px;
  line-height: 1.6;
  color: #475569;
}

.page-body {
  padding: 12px;
}

.strategy-table {
  width: 100%;
}

.strategy-name-cell strong {
  font-size: 14px;
  color: #0f172a;
}

.strategy-description-cell {
  line-height: 1.7;
  color: #475569;
  white-space: normal;
}

@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
