<template>
  <div class="strategy-center-page">
    <section class="page-toolbar">
      <div class="toolbar-filters">
        <el-input v-model="keyword" clearable placeholder="搜索策略名 / 描述" class="toolbar-search" />
        <el-select v-model="sceneFilter" class="toolbar-select">
          <el-option label="全部场景" value="all" />
          <el-option v-for="scene in sceneOptions" :key="scene.value" :label="scene.label" :value="scene.value" />
        </el-select>
        <span class="toolbar-count">共 {{ filteredStrategies.length }} 条</span>
      </div>
      <el-button type="primary" size="small" @click="openCreateDialog">创建策略</el-button>
    </section>

    <section class="page-body">
      <el-table :data="filteredStrategies" row-key="strategy_key" stripe size="small" class="strategy-table" empty-text="暂时还没有策略">
        <el-table-column label="策略名" min-width="220">
          <template #default="{ row }">
            <div class="strategy-name-cell">
              <strong>{{ row.name }}</strong>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="策略描述" min-width="420">
          <template #default="{ row }">
            <div class="strategy-description-cell">
              {{ row.description }}
            </div>
          </template>
        </el-table-column>

        <el-table-column label="跨日记忆" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="row.supports_state ? 'success' : 'info'" effect="plain" round>
              {{ row.supports_state ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="应用场景" width="180" align="center">
          <template #default="{ row }">
            <div class="scene-button-list">
              <el-tooltip
                v-for="scene in row.supported_scenes"
                :key="scene"
                :content="sceneLabel(scene)"
                placement="top"
              >
                <button type="button" class="scene-mini-button" @click="openViewDialog(row.strategy_key)">
                  {{ sceneShortLabel(scene) }}
                </button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="140" align="right">
          <template #default="{ row }">
            <el-dropdown trigger="click" @command="(command) => handleCommand(command, row.strategy_key)">
              <el-button size="small">
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

    <el-dialog v-model="formDialogVisible" :title="formDialogMode === 'create' ? '创建策略' : '编辑策略'" width="640px">
      <el-form label-position="top">
        <el-form-item label="策略名">
          <el-input v-model="formState.name" placeholder="请输入策略名" />
        </el-form-item>

        <el-form-item label="策略描述">
          <el-input v-model="formState.description" type="textarea" :rows="4" placeholder="请输入策略描述" />
        </el-form-item>

        <el-form-item label="是否跨日记忆">
          <el-switch v-model="formState.supports_state" />
        </el-form-item>

        <el-form-item label="应用场景">
          <el-checkbox-group v-model="formState.supported_scenes">
            <el-checkbox v-for="scene in sceneOptions" :key="scene.value" :label="scene.value">
              {{ scene.label }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="formDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="submitFormDialog">
            {{ formDialogMode === 'create' ? '创建' : '保存' }}
          </el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="viewDialogVisible" :title="selectedStrategy?.name || '查看策略'" width="760px" class="strategy-view-dialog">
      <template v-if="selectedStrategy">
        <div class="strategy-dialog-shell">
          <el-tabs v-model="viewActiveTab" class="strategy-detail-tabs">
            <el-tab-pane label="主要信息" name="overview">
              <section class="tab-section">
                <div class="tab-section-head">
                  <div>
                    <strong>策略信息</strong>
                  </div>
                  <button type="button" class="tab-action-button" @click="openEditDialog(selectedStrategy.strategy_key)">
                    编辑主要信息
                  </button>
                </div>

                <div class="overview-grid">
                  <div class="detail-block span-2">
                    <span>策略名称</span>
                    <p>{{ selectedStrategy.name }}</p>
                  </div>
                  <div class="detail-block span-2">
                    <span>策略描述</span>
                    <p>{{ selectedStrategy.description }}</p>
                  </div>
                  <div class="detail-block detail-pair-block">
                    <div class="detail-pair-row">
                      <span>跨日记忆</span>
                      <strong>{{ selectedStrategy.supports_state ? '支持' : '不支持' }}</strong>
                    </div>
                    <div class="detail-pair-row">
                      <span>当前版本</span>
                      <strong>v{{ selectedStrategy.version }}</strong>
                    </div>
                  </div>
                  <div class="detail-block detail-pair-block">
                    <div class="detail-pair-row">
                      <span>实现类型</span>
                      <strong>{{ selectedStrategy.impl_type }}</strong>
                    </div>
                    <div class="detail-pair-row">
                      <span>策略标识</span>
                      <strong>{{ selectedStrategy.strategy_key }}</strong>
                    </div>
                  </div>
                  <div class="detail-block span-2">
                    <span>应用场景</span>
                    <div class="info-tab-list">
                      <span v-for="scene in selectedStrategy.supported_scenes" :key="scene" class="info-tab-item">
                        {{ sceneLabelMap[scene] }}
                      </span>
                    </div>
                  </div>
                  <div class="detail-block span-2" v-if="selectedStrategy.tags.length > 0">
                    <span>标签</span>
                    <div class="info-tab-list">
                      <span v-for="tag in selectedStrategy.tags" :key="tag" class="info-tab-item info-tab-item-muted">
                        {{ tag }}
                      </span>
                    </div>
                  </div>
                </div>
              </section>
            </el-tab-pane>

            <el-tab-pane label="参数信息" name="params">
              <section class="tab-section">
                <div class="tab-section-head">
                  <div>
                    <strong>参数信息</strong>
                  </div>
                  <button type="button" class="tab-action-button" @click="saveViewStrategy">
                    保存参数信息
                  </button>
                </div>

                <el-table v-if="selectedStrategy.param_schema.length > 0" :data="selectedStrategy.param_schema" size="small" stripe class="param-table">
                  <el-table-column label="参数" min-width="180">
                    <template #default="{ row }">
                      <div class="param-name-cell">
                        <strong>{{ row.label }}</strong>
                        <small>{{ row.key }}</small>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="类型" width="100">
                    <template #default="{ row }">
                      {{ paramTypeLabel(row.type) }}
                    </template>
                  </el-table-column>
                  <el-table-column prop="description" label="说明" min-width="220" show-overflow-tooltip />
                  <el-table-column label="默认值" width="240">
                    <template #default="{ row }">
                      <el-select
                        v-if="row.type === 'select' && row.options"
                        :model-value="String(row.default)"
                        style="width: 100%"
                        @update:model-value="(value) => updateViewParamDefault(row.key, value)"
                      >
                        <el-option
                          v-for="option in row.options"
                          :key="String(option.value)"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>
                      <el-switch
                        v-else-if="row.type === 'boolean'"
                        :model-value="Boolean(row.default)"
                        @update:model-value="(value) => updateViewParamDefault(row.key, value)"
                      />
                      <el-input
                        v-else
                        :model-value="String(row.default)"
                        @update:model-value="(value) => updateViewParamDefault(row.key, castParamValue(row.type, value))"
                      />
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty v-else description="当前没有参数信息" :image-size="72" />
              </section>
            </el-tab-pane>

            <el-tab-pane label="相关任务" name="tasks">
              <section class="tab-section">
                <div class="tab-section-head">
                  <div>
                    <strong>相关任务列表</strong>
                  </div>
                  <button type="button" class="tab-action-button" @click="createRelatedTask">
                    创建任务
                  </button>
                </div>

                <el-table v-if="selectedRelatedTasks.length > 0" :data="selectedRelatedTasks" size="small" stripe class="related-task-table">
                  <el-table-column prop="name" label="任务名" min-width="180" />
                  <el-table-column label="场景" width="100">
                    <template #default="{ row }">
                      {{ sceneLabel(row.scene_type) }}
                    </template>
                  </el-table-column>
                  <el-table-column prop="target_scope_summary" label="范围" min-width="220" show-overflow-tooltip />
                  <el-table-column label="状态" width="100">
                    <template #default="{ row }">
                      <el-tag size="small" effect="plain" round>{{ taskStatusLabel(row.status) }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="schedule_label" label="调度" min-width="180" show-overflow-tooltip />
                  <el-table-column prop="last_signal_count" label="最近信号" width="90" align="center" />
                  <el-table-column label="操作" width="90" align="right">
                    <template #default="{ row }">
                    <el-button size="small" plain @click="openRelatedTask(row.task_id)">查看</el-button>
                  </template>
                </el-table-column>
                </el-table>
                <el-empty v-else description="当前没有关联任务" :image-size="72" />
              </section>
            </el-tab-pane>
          </el-tabs>
        </div>
      </template>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="viewDialogVisible = false">关闭</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowDown } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { STRATEGY_SCENE_LABELS, STRATEGY_TASK_STATUS_LABELS, listStrategyDefinitions, listStrategySceneTasks } from '@/mocks/strategyV2'
import type { StrategyDefinition, StrategySceneTask, StrategySceneType } from '@/types/strategy-v2'

const router = useRouter()

const sceneLabelMap = STRATEGY_SCENE_LABELS
const taskStatusLabelMap = STRATEGY_TASK_STATUS_LABELS
const sceneShortLabelMap: Record<StrategySceneType, string> = {
  scan: '选',
  listen: '监',
  backtest: '回',
  sim_trade: '模',
}

const sceneOptions = [
  { label: STRATEGY_SCENE_LABELS.scan, value: 'scan' as const },
  { label: STRATEGY_SCENE_LABELS.listen, value: 'listen' as const },
  { label: STRATEGY_SCENE_LABELS.backtest, value: 'backtest' as const },
  { label: STRATEGY_SCENE_LABELS.sim_trade, value: 'sim_trade' as const },
]

const strategies = ref<StrategyDefinition[]>([])
const tasks = ref<StrategySceneTask[]>([])
const selectedStrategy = ref<StrategyDefinition | null>(null)
const keyword = ref('')
const sceneFilter = ref<'all' | StrategySceneType>('all')
const formDialogVisible = ref(false)
const viewDialogVisible = ref(false)
const formDialogMode = ref<'create' | 'edit'>('create')
const editingStrategyKey = ref('')
const viewActiveTab = ref<'overview' | 'params' | 'tasks'>('overview')

const formState = reactive<{
  name: string
  description: string
  supports_state: boolean
  supported_scenes: StrategySceneType[]
}>({
  name: '',
  description: '',
  supports_state: false,
  supported_scenes: [],
})

onMounted(async () => {
  strategies.value = await listStrategyDefinitions()
  tasks.value = await listStrategySceneTasks()
})

const filteredStrategies = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  return strategies.value.filter((item) => {
    const matchesText = !text
      || item.name.toLowerCase().includes(text)
      || item.description.toLowerCase().includes(text)
    const matchesScene = sceneFilter.value === 'all' || item.supported_scenes.includes(sceneFilter.value)
    return matchesText && matchesScene
  })
})

const selectedRelatedTasks = computed(() => {
  if (!selectedStrategy.value) return []
  return tasks.value.filter((item) => item.strategy_key === selectedStrategy.value?.strategy_key)
})

function handleCommand(command: string, strategyKey: string): void {
  if (command === 'view') {
    openViewDialog(strategyKey)
    return
  }

  if (command === 'edit') {
    openEditDialog(strategyKey)
    return
  }

  if (command === 'tasks') {
    router.push({
      name: 'StrategyTaskCenterV2',
      query: {
        strategy: strategyKey,
      },
    })
    return
  }

  if (command === 'delete') {
    void deleteStrategy(strategyKey)
  }
}

function openCreateDialog(): void {
  formDialogMode.value = 'create'
  editingStrategyKey.value = ''
  resetForm()
  formDialogVisible.value = true
}

function openViewDialog(strategyKey: string): void {
  const strategy = findStrategy(strategyKey)
  if (!strategy) return
  selectedStrategy.value = cloneStrategy(strategy)
  viewActiveTab.value = 'overview'
  viewDialogVisible.value = true
}

function openEditDialog(strategyKey: string): void {
  const strategy = findStrategy(strategyKey)
  if (!strategy) return

  formDialogMode.value = 'edit'
  editingStrategyKey.value = strategyKey
  formState.name = strategy.name
  formState.description = strategy.description
  formState.supports_state = strategy.supports_state
  formState.supported_scenes = [...strategy.supported_scenes]
  formDialogVisible.value = true
  viewDialogVisible.value = false
}

function submitFormDialog(): void {
  if (!formState.name.trim()) {
    ElMessage.warning('请先填写策略名')
    return
  }

  if (!formState.description.trim()) {
    ElMessage.warning('请先填写策略描述')
    return
  }

  if (formState.supported_scenes.length === 0) {
    ElMessage.warning('请至少选择一个应用场景')
    return
  }

  if (formDialogMode.value === 'create') {
    const newStrategy: StrategyDefinition = {
      strategy_key: `custom_${Date.now()}`,
      name: formState.name.trim(),
      description: formState.description.trim(),
      impl_type: 'builtin_code',
      supported_scenes: [...formState.supported_scenes],
      supports_state: formState.supports_state,
      version: 1,
      tags: [],
      param_schema: [],
      sample_outputs: [],
    }
    strategies.value = [newStrategy, ...strategies.value]
    ElMessage.success('策略已创建')
  }
  else {
    strategies.value = strategies.value.map((item) => {
      if (item.strategy_key !== editingStrategyKey.value) return item
      return {
        ...item,
        name: formState.name.trim(),
        description: formState.description.trim(),
        supports_state: formState.supports_state,
        supported_scenes: [...formState.supported_scenes],
      }
    })
    ElMessage.success('策略已更新')
  }

  formDialogVisible.value = false
  resetForm()
}

async function deleteStrategy(strategyKey: string): Promise<void> {
  const strategy = findStrategy(strategyKey)
  if (!strategy) return

  try {
    await ElMessageBox.confirm(
      `确认删除策略“${strategy.name}”吗？当前仅做前端演示删除。`,
      '删除策略',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )

    strategies.value = strategies.value.filter((item) => item.strategy_key !== strategyKey)

    if (selectedStrategy.value?.strategy_key === strategyKey) {
      selectedStrategy.value = null
      viewDialogVisible.value = false
    }

    ElMessage.success('策略已删除')
  }
  catch {
    // User cancelled the confirmation dialog.
  }
}

function resetForm(): void {
  formState.name = ''
  formState.description = ''
  formState.supports_state = false
  formState.supported_scenes = []
}

function findStrategy(strategyKey: string): StrategyDefinition | undefined {
  return strategies.value.find((item) => item.strategy_key === strategyKey)
}

function cloneStrategy(strategy: StrategyDefinition): StrategyDefinition {
  return JSON.parse(JSON.stringify(strategy)) as StrategyDefinition
}

function sceneLabel(scene: StrategySceneType): string {
  return sceneLabelMap[scene]
}

function sceneShortLabel(scene: StrategySceneType): string {
  return sceneShortLabelMap[scene]
}

function paramTypeLabel(type: StrategyDefinition['param_schema'][number]['type']): string {
  if (type === 'number') return '整数'
  if (type === 'float') return '浮点'
  if (type === 'boolean') return '布尔'
  if (type === 'select') return '枚举'
  return '字符串'
}

function castParamValue(type: StrategyDefinition['param_schema'][number]['type'], value: string): string | number | boolean {
  if (type === 'number') return Number.parseInt(value || '0', 10)
  if (type === 'float') return Number.parseFloat(value || '0')
  return value
}

function updateViewParamDefault(key: string, value: string | number | boolean): void {
  if (!selectedStrategy.value) return
  selectedStrategy.value.param_schema = selectedStrategy.value.param_schema.map((item) => {
    if (item.key !== key) return item
    return {
      ...item,
      default: value,
    }
  })
}

function saveViewStrategy(): void {
  if (!selectedStrategy.value) return

  strategies.value = strategies.value.map((item) => {
    if (item.strategy_key !== selectedStrategy.value?.strategy_key) return item
    return cloneStrategy(selectedStrategy.value)
  })

  ElMessage.success('策略参数已保存')
}

function openRelatedTask(taskId: string): void {
  router.push({
    name: 'StrategyTaskDetailV2',
    params: { taskId },
  })
}

function createRelatedTask(): void {
  if (!selectedStrategy.value) return
  router.push({
    name: 'StrategyTaskCenterV2',
    query: {
      strategy: selectedStrategy.value.strategy_key,
      autoCreate: '1',
    },
  })
}

function taskStatusLabel(status: StrategySceneTask['status']): string {
  return taskStatusLabelMap[status]
}
</script>

<style scoped>
.strategy-center-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-toolbar,
.page-body {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 8px;
  background: #fff;
}

.page-toolbar {
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.page-body {
  padding: 4px 8px 8px;
}

.toolbar-filters {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.toolbar-search {
  width: 260px;
}

.toolbar-select {
  width: 144px;
}

.toolbar-count {
  font-size: 12px;
  color: #64748b;
  white-space: nowrap;
}

.strategy-table {
  width: 100%;
}

.strategy-table :deep(th.el-table__cell) {
  background: #f6f8fa;
  color: #475569;
  font-weight: 600;
}

.strategy-table :deep(td.el-table__cell) {
  padding-top: 8px;
  padding-bottom: 8px;
}

.strategy-name-cell strong {
  font-size: 14px;
  color: #0f172a;
  line-height: 1.4;
}

.strategy-description-cell {
  line-height: 1.6;
  color: #475569;
  white-space: normal;
}

.scene-button-list,
.full-scene-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-start;
}

.full-scene-list.align-start {
  justify-content: flex-start;
}

.info-tab-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.info-tab-item {
  display: inline-flex;
  align-items: center;
  height: 30px;
  padding: 0 12px;
  border: 1px solid #d8e1ea;
  border-bottom-color: #b8c6d8;
  border-radius: 8px 8px 0 0;
  background: #f8fbff;
  color: #1f3b63;
  font-size: 13px;
  line-height: 28px;
  white-space: nowrap;
}

.info-tab-item-muted {
  background: #f6f8fa;
  color: #475569;
}

.scene-mini-button {
  width: 26px;
  height: 26px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #fff;
  color: #334155;
  cursor: pointer;
}

.scene-mini-button:hover {
  border-color: #409eff;
  color: #409eff;
  background: #f8fbff;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.strategy-dialog-shell {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tab-section {
  padding-top: 4px;
}

.tab-section-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 10px;
}

.tab-section-head strong {
  display: block;
  font-size: 15px;
  color: #0f172a;
}

.tab-action-button {
  min-width: 116px;
  height: 32px;
  padding: 0 14px;
  border: 1px solid #d8e1ea;
  border-radius: 8px 8px 0 0;
  background: #f6f8fa;
  color: #334155;
  font-size: 13px;
  line-height: 30px;
  cursor: pointer;
}

.tab-action-button:hover {
  color: #1d4ed8;
  border-color: #bfd3f2;
  background: #f8fbff;
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.span-2 {
  grid-column: 1 / -1;
}

.detail-block span {
  display: block;
  margin-bottom: 6px;
  font-size: 12px;
  color: #64748b;
}

.detail-block strong {
  font-size: 14px;
  color: #0f172a;
}

.detail-block p {
  margin: 0;
  line-height: 1.6;
  color: #475569;
}

.detail-block,
.param-table,
.related-task-table {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 8px;
}

.detail-block {
  padding: 12px;
  background: #fff;
}

.detail-pair-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.detail-pair-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.detail-pair-row span {
  margin-bottom: 0;
}

.detail-pair-row strong {
  flex: 1;
  text-align: right;
  font-size: 13px;
  color: #334155;
  word-break: break-all;
}

.param-table :deep(th.el-table__cell),
.related-task-table :deep(th.el-table__cell) {
  background: #f6f8fa;
  color: #475569;
  font-weight: 600;
}

.param-table :deep(td.el-table__cell),
.related-task-table :deep(td.el-table__cell) {
  padding-top: 8px;
  padding-bottom: 8px;
}

.param-name-cell strong {
  display: block;
  font-size: 13px;
  color: #0f172a;
}

.param-name-cell small {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
}

@media (max-width: 768px) {
  .page-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar-filters {
    flex-wrap: wrap;
  }

  .toolbar-search,
  .toolbar-select {
    width: 100%;
  }

  .page-toolbar > :deep(.el-button) {
    width: 100%;
  }

  .overview-grid {
    grid-template-columns: 1fr;
  }

  .tab-section-head {
    flex-direction: column;
    align-items: stretch;
  }

  .tab-action-button {
    width: 100%;
    border-radius: 8px;
  }

  .detail-pair-row {
    align-items: flex-start;
    flex-direction: column;
    gap: 6px;
  }

  .detail-pair-row strong {
    text-align: left;
  }
}
</style>
