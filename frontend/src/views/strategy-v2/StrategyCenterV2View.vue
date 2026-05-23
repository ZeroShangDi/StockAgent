<template>
  <div class="strategy-center-page">
    <section class="page-toolbar">
      <el-button type="primary" @click="openCreateDialog">创建策略</el-button>
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

    <el-dialog v-model="viewDialogVisible" title="查看策略" width="680px">
      <template v-if="selectedStrategy">
        <div class="detail-block">
          <span>策略名</span>
          <strong>{{ selectedStrategy.name }}</strong>
        </div>

        <div class="detail-block">
          <span>策略描述</span>
          <p>{{ selectedStrategy.description }}</p>
        </div>

        <div class="detail-inline-grid">
          <div class="detail-block">
            <span>跨日记忆</span>
            <strong>{{ selectedStrategy.supports_state ? '支持' : '不支持' }}</strong>
          </div>
          <div class="detail-block">
            <span>版本</span>
            <strong>v{{ selectedStrategy.version }}</strong>
          </div>
        </div>

        <div class="detail-block">
          <span>应用场景</span>
          <div class="full-scene-list">
            <el-tag v-for="scene in selectedStrategy.supported_scenes" :key="scene" effect="plain" round>
              {{ sceneLabelMap[scene] }}
            </el-tag>
          </div>
        </div>

        <div class="detail-block" v-if="selectedStrategy.tags.length > 0">
          <span>标签</span>
          <div class="full-scene-list">
            <el-tag v-for="tag in selectedStrategy.tags" :key="tag" type="info" effect="plain" round>
              {{ tag }}
            </el-tag>
          </div>
        </div>

        <div class="detail-block">
          <span>参数信息</span>
          <div v-if="selectedStrategy.param_schema.length > 0" class="param-detail-list">
            <article v-for="param in selectedStrategy.param_schema" :key="param.key" class="param-detail-card">
              <div class="param-detail-head">
                <div>
                  <strong>{{ param.label }}</strong>
                  <small>{{ param.key }} · {{ paramTypeLabel(param.type) }}</small>
                </div>
              </div>

              <p>{{ param.description }}</p>

              <div class="param-edit-row">
                <span>默认值</span>
                <el-select
                  v-if="param.type === 'select' && param.options"
                  :model-value="String(param.default)"
                  style="width: 220px"
                  @update:model-value="(value) => updateViewParamDefault(param.key, value)"
                >
                  <el-option
                    v-for="option in param.options"
                    :key="String(option.value)"
                    :label="option.label"
                    :value="option.value"
                  />
                </el-select>
                <el-switch
                  v-else-if="param.type === 'boolean'"
                  :model-value="Boolean(param.default)"
                  @update:model-value="(value) => updateViewParamDefault(param.key, value)"
                />
                <el-input
                  v-else
                  :model-value="String(param.default)"
                  style="width: 220px"
                  @update:model-value="(value) => updateViewParamDefault(param.key, castParamValue(param.type, value))"
                />
              </div>
            </article>
          </div>
          <el-empty v-else description="当前没有参数信息" :image-size="72" />
        </div>
      </template>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="viewDialogVisible = false">关闭</el-button>
          <el-button v-if="selectedStrategy" type="success" plain @click="saveViewStrategy">保存参数</el-button>
          <el-button v-if="selectedStrategy" type="primary" @click="openEditDialog(selectedStrategy.strategy_key)">编辑</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowDown } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { STRATEGY_SCENE_LABELS, listStrategyDefinitions } from '@/mocks/strategyV2'
import type { StrategyDefinition, StrategySceneType } from '@/types/strategy-v2'

const router = useRouter()

const sceneLabelMap = STRATEGY_SCENE_LABELS
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
const selectedStrategy = ref<StrategyDefinition | null>(null)
const formDialogVisible = ref(false)
const viewDialogVisible = ref(false)
const formDialogMode = ref<'create' | 'edit'>('create')
const editingStrategyKey = ref('')

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
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
}

.page-toolbar {
  padding: 16px 20px;
  display: flex;
  justify-content: flex-end;
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

.scene-button-list,
.full-scene-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}

.scene-mini-button {
  width: 28px;
  height: 28px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #f8fafc;
  color: #334155;
  cursor: pointer;
  transition: all 0.2s ease;
}

.scene-mini-button:hover {
  border-color: #409eff;
  color: #409eff;
  background: #ecf5ff;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.detail-block + .detail-block {
  margin-top: 18px;
}

.detail-block span {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  color: #64748b;
}

.detail-block strong {
  font-size: 15px;
  color: #0f172a;
}

.detail-block p {
  margin: 0;
  line-height: 1.7;
  color: #475569;
}

.detail-inline-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.param-detail-list {
  display: grid;
  gap: 12px;
}

.param-detail-card {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 12px;
  padding: 14px;
  background: #f8fafc;
}

.param-detail-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.param-detail-head strong {
  display: block;
}

.param-detail-head small {
  display: block;
  margin-top: 4px;
  color: #64748b;
}

.param-detail-card p {
  margin: 10px 0 0;
  color: #475569;
  line-height: 1.7;
}

.param-edit-row {
  margin-top: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.param-edit-row span {
  margin: 0;
}

@media (max-width: 768px) {
  .page-toolbar {
    justify-content: stretch;
  }

  .page-toolbar :deep(.el-button) {
    width: 100%;
  }

  .detail-inline-grid {
    grid-template-columns: 1fr;
  }

  .param-edit-row {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
