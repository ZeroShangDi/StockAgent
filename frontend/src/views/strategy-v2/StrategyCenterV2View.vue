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
                      <span>策略类型</span>
                      <strong>{{ strategyTypeLabel(selectedStrategy.impl_type) }}</strong>
                    </div>
                    <div class="detail-pair-row">
                      <span>内部标识</span>
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

    <el-dialog
      v-model="taskDialogVisible"
      title="创建任务"
      append-to-body
      width="720px"
      class="task-create-dialog"
      :close-on-click-modal="false"
    >
      <div class="task-dialog-shell">
        <el-steps :active="taskStepIndex" finish-status="success" align-center class="task-steps">
          <el-step
            v-for="step in taskStepItems"
            :key="step.title"
            :title="step.title"
            :description="step.description"
          />
        </el-steps>

        <section class="task-step-card">
          <div class="task-step-head">
            <strong>{{ currentTaskStep.title }}</strong>
            <p>{{ currentTaskStep.description }}</p>
          </div>

          <el-form label-position="top">
            <template v-if="taskStepIndex === 0">
              <el-form-item label="策略">
                <el-input :model-value="selectedStrategy?.name || ''" disabled />
              </el-form-item>
              <el-form-item label="任务名称">
                <el-input v-model="taskForm.name" placeholder="例如：5日线低吸候选入池" />
              </el-form-item>
              <el-form-item label="任务说明">
                <el-input
                  v-model="taskForm.notes"
                  type="textarea"
                  :rows="4"
                  placeholder="说明这个任务在链路里的职责。"
                />
              </el-form-item>
            </template>

            <template v-else-if="taskStepIndex === 1">
              <el-form-item label="覆盖策略默认参数">
                <el-switch v-model="overrideStrategyParams" active-text="覆盖" inactive-text="使用默认" />
              </el-form-item>
              <el-table
                v-if="overrideStrategyParams && selectedStrategy && selectedStrategy.param_schema.length > 0"
                :data="selectedStrategy.param_schema"
                size="small"
                stripe
                class="param-table"
              >
                <el-table-column label="参数" min-width="170">
                  <template #default="{ row }">
                    <div class="param-name-cell">
                      <strong>{{ row.label }}</strong>
                      <small>{{ row.description }}</small>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="当前任务值" width="220">
                  <template #default="{ row }">
                    <el-select
                      v-if="row.type === 'select' && row.options"
                      :model-value="String(taskParamValue(row.key))"
                      style="width: 100%"
                      @update:model-value="(value) => updateTaskParam(row.key, value)"
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
                      :model-value="Boolean(taskParamValue(row.key))"
                      @update:model-value="(value) => updateTaskParam(row.key, value)"
                    />
                    <el-input
                      v-else
                      :model-value="String(taskParamValue(row.key))"
                      @update:model-value="(value) => updateTaskParam(row.key, castParamValue(row.type, value))"
                    />
                  </template>
                </el-table-column>
              </el-table>
              <el-empty v-else description="当前任务使用策略默认参数" :image-size="72" />
            </template>

            <template v-else-if="taskStepIndex === 2">
              <el-form-item label="场景类型">
                <el-select v-model="taskForm.scene_type" style="width: 100%">
                  <el-option
                    v-for="scene in sceneOptions"
                    :key="scene.value"
                    :label="scene.label"
                    :value="scene.value"
                    :disabled="isTaskSceneDisabled(scene.value)"
                  >
                    <div class="task-option-line">
                      <span>{{ scene.label }}</span>
                      <small>{{ isTaskSceneDisabled(scene.value) ? '当前策略不支持该场景' : '当前策略支持该场景' }}</small>
                    </div>
                  </el-option>
                </el-select>
              </el-form-item>
              <el-form-item label="目标范围">
                <el-select v-model="taskForm.target_scope_option_key" style="width: 100%" @change="normalizeTaskScope">
                  <el-option
                    v-for="option in taskScopeOptions"
                    :key="option.option_key"
                    :label="option.label"
                    :value="option.option_key"
                    :disabled="isTaskScopeDisabled(option)"
                  >
                    <div class="task-option-line">
                      <span>{{ option.label }}</span>
                      <small>{{ taskScopeOptionHint(option) }}</small>
                    </div>
                  </el-option>
                </el-select>
              </el-form-item>
              <el-row v-if="taskForm.target_scope.scope_type === 'trade_account'" :gutter="12">
                <el-col :span="12">
                  <el-form-item label="交割单">
                    <el-select v-model="targetParams.trade_review_group_id" style="width: 100%" @change="normalizeTaskScope">
                      <el-option label="实盘训练账户" value="training_account" />
                      <el-option label="模拟观察账户" value="simulation_watch" />
                    </el-select>
                  </el-form-item>
                </el-col>
              </el-row>
              <el-row v-else-if="taskForm.target_scope.scope_type === 'stock_pool'" :gutter="12">
                <el-col :span="12">
                  <el-form-item label="股池分组">
                    <el-select v-model="targetParams.stock_pool_id" style="width: 100%" @change="normalizeTaskScope">
                      <el-option label="候选池" value="candidate_pool" />
                      <el-option label="观察池" value="watch_pool" />
                      <el-option label="确认池" value="confirm_pool" />
                    </el-select>
                  </el-form-item>
                </el-col>
              </el-row>
              <el-row v-else-if="taskForm.target_scope.scope_type === 'all_market'" :gutter="12">
                <el-col v-if="['scan', 'backtest'].includes(taskForm.scene_type)" :span="12">
                  <el-form-item label="时间段">
                    <el-date-picker
                      v-model="targetParams.date_range"
                      type="daterange"
                      value-format="YYYY-MM-DD"
                      start-placeholder="开始日期"
                      end-placeholder="结束日期"
                      style="width: 100%"
                      @change="normalizeTaskScope"
                    />
                  </el-form-item>
                </el-col>
                <el-col v-if="['backtest', 'sim_trade'].includes(taskForm.scene_type)" :span="12">
                  <el-form-item label="交割单账户">
                    <el-select v-model="targetParams.trade_review_group_id" style="width: 100%" @change="normalizeTaskScope">
                      <el-option label="创建新交割单账户" value="auto_create" />
                      <el-option label="实盘训练账户" value="training_account" />
                      <el-option label="模拟观察账户" value="simulation_watch" />
                    </el-select>
                  </el-form-item>
                </el-col>
              </el-row>
              <el-form-item v-else-if="taskForm.target_scope.scope_type === 'custom_stock_list'" label="股票列表">
                <el-input
                  v-model="targetParams.ts_codes_text"
                  type="textarea"
                  :rows="4"
                  placeholder="每行一个股票代码，例如 000001.SZ"
                  @change="normalizeTaskScope"
                />
              </el-form-item>
              <el-row v-else-if="taskForm.target_scope.scope_type === 'index'" :gutter="12">
                <el-col :span="12">
                  <el-form-item label="指数">
                    <el-select v-model="targetParams.index_code" style="width: 100%" @change="normalizeTaskScope">
                      <el-option label="上证指数" value="000001.SH" />
                      <el-option label="深证成指" value="399001.SZ" />
                      <el-option label="创业板指" value="399006.SZ" />
                    </el-select>
                  </el-form-item>
                </el-col>
              </el-row>
              <el-form-item label="调度方式">
                <el-select v-model="taskForm.schedule_option_key" style="width: 100%" @change="normalizeTaskSchedule">
                  <el-option
                    v-for="option in taskScheduleOptions"
                    :key="option.option_key"
                    :label="option.label"
                    :value="option.option_key"
                    :disabled="isTaskScheduleDisabled(option)"
                  >
                    <div class="task-option-line">
                      <span>{{ option.label }}</span>
                      <small>{{ taskScheduleOptionHint(option) }}</small>
                    </div>
                  </el-option>
                </el-select>
              </el-form-item>
            </template>

            <template v-else-if="taskStepIndex === 3">
              <div class="task-action-rule-toolbar">
                <div>
                  <strong>动作规则</strong>
                  <span>每条规则表示：策略返回值命中后，执行一个动作。</span>
                </div>
                <el-button size="small" type="primary" plain :disabled="!canAddTaskActionRule" @click="addTaskActionRule">新增规则</el-button>
              </div>

              <div v-if="taskForm.actions.length > 0" class="task-action-rule-list">
                <article v-for="(action, index) in taskForm.actions" :key="`action-${index}`" class="task-action-rule">
                  <div class="task-action-rule-head">
                    <strong>规则 {{ index + 1 }}</strong>
                    <el-button v-if="taskForm.actions.length > 1" link type="danger" @click="removeTaskActionRule(index)">
                      删除
                    </el-button>
                  </div>

                  <el-row :gutter="12">
                    <el-col :span="8">
                      <el-form-item label="策略返回值">
                        <el-select v-model="action.trigger_signals" multiple collapse-tags style="width: 100%">
                          <el-option :label="signalLabel(1)" :value="1" />
                          <el-option :label="signalLabel(0)" :value="0" />
                          <el-option :label="signalLabel(-1)" :value="-1" />
                        </el-select>
                      </el-form-item>
                    </el-col>
                    <el-col :span="8">
                      <el-form-item label="动作类型">
                        <el-select
                          :model-value="action.action_type"
                          style="width: 100%"
                          @update:model-value="(value) => handleTaskActionTypeChange(action, value)"
                        >
                          <el-option
                            v-for="item in taskActionOptions"
                            :key="item.value"
                            :label="item.label"
                            :value="item.value"
                            :disabled="isTaskActionDisabled(item.value)"
                          >
                            <div class="task-option-line">
                              <span>{{ item.label }}</span>
                              <small>{{ item.description }}</small>
                            </div>
                          </el-option>
                        </el-select>
                      </el-form-item>
                    </el-col>
                    <el-col :span="8">
                      <el-form-item label="启用">
                        <el-switch v-model="action.enabled" active-text="启用" inactive-text="停用" />
                      </el-form-item>
                    </el-col>
                  </el-row>

                  <template v-if="action.action_type === 'notify'">
                    <el-row :gutter="12">
                      <el-col :span="8">
                        <el-form-item label="通知渠道">
                          <el-select v-model="action.params.channel_id" style="width: 100%">
                            <el-option label="站内通知" value="in_app" />
                            <el-option label="企业微信" value="wechat_work" />
                          </el-select>
                        </el-form-item>
                      </el-col>
                      <el-col :span="8">
                        <el-form-item label="通知级别">
                          <el-select v-model="action.params.notify_level" style="width: 100%">
                            <el-option label="普通" value="normal" />
                            <el-option label="重要" value="important" />
                          </el-select>
                        </el-form-item>
                      </el-col>
                      <el-col :span="8">
                        <el-form-item label="冷却时间">
                          <el-select v-model="action.params.cooldown_minutes" style="width: 100%">
                            <el-option label="不限制" :value="0" />
                            <el-option label="5 分钟" :value="5" />
                            <el-option label="30 分钟" :value="30" />
                          </el-select>
                        </el-form-item>
                      </el-col>
                    </el-row>
                  </template>

                  <template v-else-if="action.action_type === 'add_to_pool'">
                    <el-row :gutter="12">
                      <el-col :span="12">
                        <el-form-item label="目标股池">
                          <el-select v-model="action.params.target_pool_id" style="width: 100%">
                            <el-option label="候选池" value="candidate_pool" />
                            <el-option label="观察池" value="watch_pool" />
                          </el-select>
                        </el-form-item>
                      </el-col>
                      <el-col :span="12">
                        <el-form-item label="重复处理">
                          <el-select v-model="action.params.duplicate_policy" style="width: 100%">
                            <el-option label="已存在则跳过" value="skip" />
                            <el-option label="已存在则刷新入池原因" value="refresh_reason" />
                          </el-select>
                        </el-form-item>
                      </el-col>
                    </el-row>
                  </template>

                  <template v-else-if="action.action_type === 'pool_transition'">
                    <el-row :gutter="12">
                      <el-col :span="12">
                        <el-form-item label="流转方向">
                          <el-select v-model="action.params.transition" style="width: 100%">
                            <el-option label="观察池 -> 确认池" value="watch_to_confirm" />
                            <el-option label="候选池 -> 淘汰池" value="candidate_to_rejected" />
                          </el-select>
                        </el-form-item>
                      </el-col>
                      <el-col :span="12">
                        <el-form-item label="流转原因">
                          <el-select v-model="action.params.reason_tag" style="width: 100%">
                            <el-option label="策略信号触发" value="strategy_signal" />
                            <el-option label="风险条件触发" value="risk_signal" />
                          </el-select>
                        </el-form-item>
                      </el-col>
                    </el-row>
                  </template>

                  <template v-else-if="action.action_type === 'temp_list'">
                    <el-row :gutter="12">
                      <el-col :span="12">
                        <el-form-item label="清单用途">
                          <el-select v-model="action.params.list_usage" style="width: 100%">
                            <el-option label="人工复筛" value="manual_review" />
                            <el-option label="交易计划候选" value="trade_plan" />
                          </el-select>
                        </el-form-item>
                      </el-col>
                      <el-col :span="12">
                        <el-form-item label="临时清单保留">
                          <el-select v-model="action.params.ttl_days" style="width: 100%">
                            <el-option label="当日有效" :value="1" />
                            <el-option label="保留 3 天" :value="3" />
                            <el-option label="保留 7 天" :value="7" />
                          </el-select>
                        </el-form-item>
                      </el-col>
                    </el-row>
                  </template>

                  <template v-else-if="action.action_type === 'paper_trade'">
                    <el-row :gutter="12">
                      <el-col :span="12">
                        <el-form-item label="结果分组">
                          <el-select v-model="action.params.trade_review_group_id" style="width: 100%">
                            <el-option label="使用目标范围中的交割单账户" value="use_scope_account" />
                            <el-option label="自动新建交割单分组" value="auto_create" />
                            <el-option label="实盘训练账户" value="training_account" />
                            <el-option label="模拟观察账户" value="simulation_watch" />
                          </el-select>
                        </el-form-item>
                      </el-col>
                      <el-col :span="12">
                        <el-form-item label="成交方向">
                          <el-select v-model="action.params.order_side" style="width: 100%">
                            <el-option label="跟随策略信号" value="follow_signal" />
                            <el-option label="只记录买入计划" value="buy_plan" />
                            <el-option label="只记录卖出计划" value="sell_plan" />
                          </el-select>
                        </el-form-item>
                      </el-col>
                      <el-col :span="12">
                        <el-form-item label="写入方式">
                          <el-select v-model="action.params.write_mode" style="width: 100%">
                            <el-option label="回测完成后一次性生成" value="backtest_final" />
                            <el-option label="模拟实盘每日更新" value="sim_daily_update" />
                          </el-select>
                        </el-form-item>
                      </el-col>
                    </el-row>
                  </template>

                </article>
              </div>
              <el-empty v-else description="还没有动作规则" :image-size="72">
                <el-button type="primary" plain :disabled="!canAddTaskActionRule" @click="addTaskActionRule">新增规则</el-button>
              </el-empty>
            </template>

            <template v-else>
              <div class="task-review-list">
                <article class="task-review-row">
                  <span>策略</span>
                  <strong>{{ selectedStrategy?.name || '-' }}</strong>
                </article>
                <article class="task-review-row">
                  <span>任务名称</span>
                  <strong>{{ taskForm.name || '未填写' }}</strong>
                </article>
                <article class="task-review-row">
                  <span>参数覆盖</span>
                  <strong>{{ overrideStrategyParams ? '已覆盖当前任务参数' : '使用策略默认参数' }}</strong>
                </article>
                <article class="task-review-row">
                  <span>场景类型</span>
                  <strong>{{ sceneLabel(taskForm.scene_type) }}</strong>
                </article>
                <article class="task-review-row">
                  <span>目标范围</span>
                  <strong>{{ taskForm.target_scope.summary || '未选择' }}</strong>
                </article>
                <article class="task-review-row">
                  <span>调度方式</span>
                  <strong>{{ taskForm.schedule.label || '未选择' }}</strong>
                </article>
                <article class="task-review-row">
                  <span>动作</span>
                  <strong>{{ taskActionSummary }}</strong>
                </article>
              </div>
            </template>
          </el-form>
        </section>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="taskDialogVisible = false">取消</el-button>
          <el-button v-if="taskStepIndex > 0" @click="prevTaskStep">上一步</el-button>
          <el-button v-if="taskStepIndex < taskStepItems.length - 1" type="primary" @click="nextTaskStep">下一步</el-button>
          <el-button v-else type="primary" :loading="taskSubmitting" @click="submitTaskDialog">创建任务</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowDown } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  createStrategySceneTask,
  listStrategyDefinitions,
  listStrategySceneTasks,
} from '@/api/modules/strategy-v2'
import {
  STRATEGY_ACTION_LABELS,
  STRATEGY_SCENE_LABELS,
  STRATEGY_TASK_STATUS_LABELS,
} from '@/mocks/strategyV2'
import type {
  StrategyActionType,
  StrategyDefinition,
  StrategyScheduleConfig,
  StrategyScheduleMode,
  StrategySceneTask,
  StrategySceneType,
  StrategySignalValue,
  StrategyTargetScope,
  StrategyTargetScopeType,
  StrategyTaskActionInput,
} from '@/types/strategy-v2'

interface TaskDialogForm {
  name: string
  scene_type: StrategySceneType
  strategy_key: string
  target_scope_option_key: string
  target_scope: StrategyTargetScope
  params: Record<string, unknown>
  schedule_option_key: string
  schedule: StrategyScheduleConfig
  notes: string
  actions: StrategyTaskActionInput[]
}

interface TaskTargetParams {
  trade_review_group_id: string
  stock_pool_id: string
  stock_pool_name: string
  date_range: string[]
  ts_codes_text: string
  index_code: string
}

interface TaskScopeOptionBase {
  label: string
  scope_type: StrategyTargetScopeType
  summary: string
  description: string
  scope_id?: string
  scope_name?: string
  supported_scenes: StrategySceneType[]
  disabled?: boolean
}

interface TaskScopeOption extends TaskScopeOptionBase {
  option_key: string
}

interface TaskScheduleOptionBase {
  label: string
  mode: StrategyScheduleMode
  description: string
  interval_seconds?: number
  times?: string[]
  slot?: string
  trading_day_only?: boolean
  supported_scenes: StrategySceneType[]
}

interface TaskScheduleOption extends TaskScheduleOptionBase {
  option_key: string
}

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
const taskDialogVisible = ref(false)
const formDialogMode = ref<'create' | 'edit'>('create')
const editingStrategyKey = ref('')
const viewActiveTab = ref<'overview' | 'params' | 'tasks'>('overview')
const taskStepIndex = ref(0)
const taskSubmitting = ref(false)
const overrideStrategyParams = ref(false)

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

const taskStepItems = [
  { title: '基础信息', description: '任务名、说明和绑定策略。' },
  { title: '策略参数', description: '可跳过，也可覆盖默认参数。' },
  { title: '场景信息', description: '场景类型、目标范围和调度方式。' },
  { title: '调度动作', description: '按策略返回值配置动作。' },
  { title: '确认创建', description: '确认当前任务配置。' },
]

const taskScopeCatalog: TaskScopeOption[] = [
  { option_key: 'watchlist', label: '自选股', scope_type: 'watchlist', summary: '当前用户自选股', description: '适合从熟悉标的中筛选或监听。', supported_scenes: ['scan', 'listen'] },
  { option_key: 'trade_account', label: '持仓股/交易账户', scope_type: 'trade_account', scope_id: 'training_account', scope_name: '实盘训练账户', summary: '交割单：实盘训练账户', description: '从交割单分组推导当前持仓。', supported_scenes: ['scan', 'listen'] },
  { option_key: 'stock_pool', label: '股池分组', scope_type: 'stock_pool', scope_id: 'watch_pool', scope_name: '观察池', summary: '股池：观察池', description: '适合候选池、观察池二次筛选与流转。', supported_scenes: ['scan', 'listen'] },
  { option_key: 'all_market', label: '全市场排除 ST', scope_type: 'all_market', summary: '全市场 · 排除 ST · 默认最近三个月', description: '选股/回测可选时间段；模拟需要绑定交易账户。', supported_scenes: ['scan', 'listen', 'backtest', 'sim_trade'] },
  { option_key: 'custom_stock_list', label: '自定义股票列表', scope_type: 'custom_stock_list', summary: '当前任务自定义股票列表', description: '列表存储在当前任务下，类似旧市场监听股票列表。', supported_scenes: ['listen'] },
  { option_key: 'index', label: '指数', scope_type: 'index', scope_id: '000001.SH', scope_name: '上证指数', summary: '指数：上证指数', description: '用于指数变化与市场情绪监听。', supported_scenes: ['listen'] },
  { option_key: 'event', label: '事件', scope_type: 'event', summary: '事件源：预留', description: '本期只保留，不开放创建。', supported_scenes: [], disabled: true },
]

const taskScheduleCatalog: TaskScheduleOption[] = [
  { option_key: 'once', label: '一次性运行', mode: 'once', description: '适合选股临时筛选和回测执行。', supported_scenes: ['scan', 'backtest'] },
  { option_key: 'manual', label: '手动运行', mode: 'manual', description: '只保存任务，由用户手动触发。', supported_scenes: ['scan', 'listen', 'backtest', 'sim_trade'] },
  { option_key: 'pre_market_0900', label: '盘前 9:00', mode: 'scheduled', slot: 'pre_market_0900', times: ['09:00'], trading_day_only: true, description: '交易日前置扫描。', supported_scenes: ['scan', 'listen', 'sim_trade'] },
  { option_key: 'call_auction_0925', label: '竞价 9:25', mode: 'scheduled', slot: 'call_auction_0925', times: ['09:25'], trading_day_only: true, description: '集合竞价阶段。', supported_scenes: ['scan', 'listen', 'sim_trade'] },
  { option_key: 'morning_turn_1000', label: '上午变盘 10:00', mode: 'scheduled', slot: 'morning_turn_1000', times: ['10:00'], trading_day_only: true, description: '上午行情初步确认。', supported_scenes: ['scan', 'listen', 'sim_trade'] },
  { option_key: 'intraday_1m', label: '盘中轮询 1 分钟', mode: 'scheduled', slot: 'intraday_1m', interval_seconds: 60, trading_day_only: true, description: '高频盘中监听。', supported_scenes: ['scan', 'listen', 'sim_trade'] },
  { option_key: 'intraday_5m', label: '盘中轮询 5 分钟', mode: 'scheduled', slot: 'intraday_5m', interval_seconds: 300, trading_day_only: true, description: '常规盘中监听。', supported_scenes: ['scan', 'listen', 'sim_trade'] },
  { option_key: 'intraday_30m', label: '盘中轮询 30 分钟', mode: 'scheduled', slot: 'intraday_30m', interval_seconds: 1800, trading_day_only: true, description: '低频盘中检查。', supported_scenes: ['scan', 'listen', 'sim_trade'] },
  { option_key: 'midday_close_1130', label: '中午收盘 11:30', mode: 'scheduled', slot: 'midday_close_1130', times: ['11:30'], trading_day_only: true, description: '午间复盘。', supported_scenes: ['scan', 'listen', 'sim_trade'] },
  { option_key: 'afternoon_turn_1400', label: '下午变盘 14:00', mode: 'scheduled', slot: 'afternoon_turn_1400', times: ['14:00'], trading_day_only: true, description: '尾盘前确认。', supported_scenes: ['scan', 'listen', 'sim_trade'] },
  { option_key: 'post_market_1505', label: '盘后 15:05', mode: 'scheduled', slot: 'post_market_1505', times: ['15:05'], trading_day_only: true, description: '收盘后整理。', supported_scenes: ['scan', 'listen', 'sim_trade'] },
  { option_key: 'weekly_sat_1200', label: '每周六 12:00', mode: 'scheduled', slot: 'weekly_sat_1200', times: ['12:00'], description: '周末复盘、训练或批处理。', supported_scenes: ['scan', 'listen', 'sim_trade'] },
]

const taskActionOptionsByScene: Record<StrategySceneType, StrategyActionType[]> = {
  scan: ['add_to_pool', 'temp_list'],
  listen: ['notify', 'add_to_pool', 'pool_transition'],
  backtest: ['paper_trade'],
  sim_trade: ['paper_trade'],
}

const taskActionCatalog: Array<{ value: StrategyActionType; label: string; description: string }> = [
  { value: 'notify', label: STRATEGY_ACTION_LABELS.notify, description: '发送提醒，用于监听和风险提示。' },
  { value: 'add_to_pool', label: STRATEGY_ACTION_LABELS.add_to_pool, description: '把候选结果送进现有股池。' },
  { value: 'pool_transition', label: STRATEGY_ACTION_LABELS.pool_transition, description: '在多个股池之间自动流转。' },
  { value: 'temp_list', label: STRATEGY_ACTION_LABELS.temp_list, description: '一次性运行后生成临时候选池，一天后删除。' },
  { value: 'paper_trade', label: STRATEGY_ACTION_LABELS.paper_trade, description: '写入模拟交易成交和持仓结果。' },
]

const taskForm = reactive<TaskDialogForm>({
  name: '',
  scene_type: 'listen',
  strategy_key: '',
  target_scope_option_key: '',
  target_scope: {
    scope_type: 'stock_pool',
    summary: '',
  },
  params: {},
  schedule_option_key: '',
  schedule: {
    mode: 'once',
    label: '',
  },
  notes: '',
  actions: [],
})

const targetParams = reactive<TaskTargetParams>({
  trade_review_group_id: 'training_account',
  stock_pool_id: 'watch_pool',
  stock_pool_name: '观察池',
  date_range: [],
  ts_codes_text: '',
  index_code: '000001.SH',
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
const currentTaskStep = computed(() => taskStepItems[taskStepIndex.value])
const taskScopeOptions = computed(() => taskScopeCatalog)
const taskScheduleOptions = computed(() => taskScheduleCatalog)
const taskActionOptions = computed(() => taskActionCatalog)
const taskActionSummary = computed(() => {
  if (taskForm.actions.length === 0) return '未选择动作'
  return taskForm.actions
    .map((item) => `${item.trigger_signals.map(signalLabel).join('/')} -> ${STRATEGY_ACTION_LABELS[item.action_type]}`)
    .join('；')
})
const canAddTaskActionRule = computed(() => taskActionOptionsByScene[taskForm.scene_type].length > 0)

watch(() => taskForm.scene_type, (scene) => {
  normalizeTaskForm(scene)
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
  resetTaskForm()
  taskForm.strategy_key = selectedStrategy.value.strategy_key
  taskForm.scene_type = selectedStrategy.value.supported_scenes[0] || 'listen'
  normalizeTaskForm(taskForm.scene_type)
  taskDialogVisible.value = true
}

function resetTaskForm(): void {
  overrideStrategyParams.value = false
  taskForm.name = ''
  taskForm.scene_type = 'listen'
  taskForm.strategy_key = ''
  taskForm.target_scope_option_key = ''
  taskForm.target_scope = {
    scope_type: 'stock_pool',
    summary: '',
  }
  taskForm.params = {}
  taskForm.schedule_option_key = ''
  taskForm.schedule = {
    mode: 'once',
    label: '',
  }
  taskForm.notes = ''
  taskForm.actions = []
  targetParams.trade_review_group_id = 'training_account'
  targetParams.stock_pool_id = 'watch_pool'
  targetParams.stock_pool_name = '观察池'
  targetParams.date_range = []
  targetParams.ts_codes_text = ''
  targetParams.index_code = '000001.SH'
  taskStepIndex.value = 0
}

function normalizeTaskForm(scene: StrategySceneType): void {
  const strategy = selectedStrategy.value
  if (!strategy) return

  taskForm.strategy_key = strategy.strategy_key

  if (!strategy.supported_scenes.includes(scene)) {
    taskForm.scene_type = strategy.supported_scenes[0] || 'listen'
  }

  const allowedScopeKeys = taskScopeCatalog
    .filter((item) => !item.disabled && item.supported_scenes.includes(taskForm.scene_type))
    .map((item) => item.option_key)
  if (!taskForm.target_scope_option_key || !allowedScopeKeys.includes(taskForm.target_scope_option_key)) {
    taskForm.target_scope_option_key = allowedScopeKeys[0] || ''
  }
  if (taskForm.target_scope_option_key) {
    taskForm.target_scope = buildTargetScope(taskForm.scene_type, taskForm.target_scope_option_key)
  }

  const allowedScheduleKeys = taskScheduleCatalog
    .filter((item) => item.supported_scenes.includes(taskForm.scene_type))
    .map((item) => item.option_key)
  if (!taskForm.schedule_option_key || !allowedScheduleKeys.includes(taskForm.schedule_option_key)) {
    taskForm.schedule_option_key = allowedScheduleKeys[0] || ''
  }
  if (taskForm.schedule_option_key) {
    taskForm.schedule = buildSchedule(taskForm.scene_type, taskForm.schedule_option_key)
  }

  const allowedActions = new Set(taskActionOptionsByScene[taskForm.scene_type])
  const nextActions = taskForm.actions.filter((item) => allowedActions.has(item.action_type))
  if (nextActions.length === 0) {
    taskForm.actions = defaultTaskActions(taskForm.scene_type)
  }
  else {
    taskForm.actions = nextActions
  }
}

function buildTargetScope(scene: StrategySceneType, optionKey?: string): StrategyTargetScope {
  const option = taskScopeCatalog.find((item) => item.option_key === optionKey && item.supported_scenes.includes(scene))
    || taskScopeCatalog.find((item) => item.supported_scenes.includes(scene) && !item.disabled)
    || taskScopeCatalog[0]
  const params = buildTargetParams(option.scope_type, scene)
  return {
    scope_type: option.scope_type,
    scope_id: params.scope_id || option.scope_id,
    scope_name: params.scope_name || option.scope_name,
    ts_codes: params.ts_codes,
    index_codes: params.index_codes,
    summary: buildTargetSummary(option, params),
    filters: option.scope_type === 'all_market'
      ? {
          exclude_st: true,
          start_date: params.start_date,
          end_date: params.end_date,
          recent_months: params.start_date && params.end_date ? undefined : 3,
        }
      : undefined,
    params,
  }
}

function normalizeTaskScope(): void {
  taskForm.target_scope = buildTargetScope(taskForm.scene_type, taskForm.target_scope_option_key)
}

function buildSchedule(scene: StrategySceneType, optionKey?: string): StrategyScheduleConfig {
  const option = taskScheduleCatalog.find((item) => item.option_key === optionKey && item.supported_scenes.includes(scene))
    || taskScheduleCatalog.find((item) => item.supported_scenes.includes(scene))
    || taskScheduleCatalog[0]
  return {
    mode: option.mode,
    label: option.label,
    timezone: 'Asia/Shanghai',
    interval_seconds: option.interval_seconds,
    times: option.times,
    slot: option.slot,
    trading_day_only: option.trading_day_only,
  }
}

function normalizeTaskSchedule(): void {
  taskForm.schedule = buildSchedule(taskForm.scene_type, taskForm.schedule_option_key)
}

function defaultTaskActions(scene: StrategySceneType): StrategyTaskActionInput[] {
  if (scene === 'scan') return (['add_to_pool', 'temp_list'] as StrategyActionType[]).map(makeTaskAction)
  if (scene === 'listen') return (['notify'] as StrategyActionType[]).map(makeTaskAction)
  if (scene === 'backtest' || scene === 'sim_trade') return (['paper_trade'] as StrategyActionType[]).map(makeTaskAction)
  return []
}

function makeTaskAction(actionType: StrategyActionType): StrategyTaskActionInput {
  const signalMap: Record<StrategyActionType, StrategySignalValue[]> = {
    notify: [1, -1],
    add_to_pool: [1],
    pool_transition: [1, -1],
    temp_list: [1],
    paper_trade: [1, -1],
    persist_result: [1, 0, -1],
  }
  return {
    action_type: actionType,
    enabled: true,
    trigger_signals: signalMap[actionType],
    params: defaultActionParams(actionType),
  }
}

function defaultActionParams(actionType: StrategyActionType): Record<string, string | number | boolean | undefined> {
  if (actionType === 'notify') return { channel_id: 'in_app', notify_level: 'normal', cooldown_minutes: 5 }
  if (actionType === 'add_to_pool') return { target_pool_id: 'candidate_pool', duplicate_policy: 'skip' }
  if (actionType === 'pool_transition') return { transition: 'watch_to_confirm', reason_tag: 'strategy_signal' }
  if (actionType === 'temp_list') return { list_usage: 'manual_review', ttl_days: 1 }
  if (actionType === 'paper_trade') {
    return {
      trade_review_group_id: 'use_scope_account',
      order_side: 'follow_signal',
      write_mode: taskForm.scene_type === 'backtest' ? 'backtest_final' : 'sim_daily_update',
    }
  }
  return { persist_mode: 'signal_and_items', dataset_usage: 'audit' }
}

function isTaskSceneDisabled(scene: StrategySceneType): boolean {
  return !selectedStrategy.value?.supported_scenes.includes(scene)
}

function isTaskScopeDisabled(option: TaskScopeOption): boolean {
  return Boolean(option.disabled) || !option.supported_scenes.includes(taskForm.scene_type)
}

function isTaskScheduleDisabled(option: TaskScheduleOption): boolean {
  return !option.supported_scenes.includes(taskForm.scene_type)
}

function isTaskActionDisabled(actionType: StrategyActionType): boolean {
  if (!taskActionOptionsByScene[taskForm.scene_type].includes(actionType)) return true
  if (actionType === 'notify') return taskForm.scene_type !== 'listen'
  if (actionType === 'add_to_pool') return !isStockScope(taskForm.target_scope.scope_type)
  if (actionType === 'pool_transition') return taskForm.target_scope.scope_type !== 'stock_pool'
  if (actionType === 'temp_list') return taskForm.schedule.mode !== 'once'
  if (actionType === 'paper_trade') return !['backtest', 'sim_trade'].includes(taskForm.scene_type)
  return true
}

function firstAllowedActionType(scene = taskForm.scene_type): StrategyActionType {
  return taskActionOptionsByScene[scene].find((actionType) => !isTaskActionDisabled(actionType)) || taskActionOptionsByScene[scene][0] || 'notify'
}

function addTaskActionRule(): void {
  if (!canAddTaskActionRule.value) return
  taskForm.actions.push(makeTaskAction(firstAllowedActionType()))
}

function removeTaskActionRule(index: number): void {
  taskForm.actions.splice(index, 1)
}

function updateTaskActionType(action: StrategyTaskActionInput, actionType: StrategyActionType): void {
  action.action_type = actionType
  action.params = defaultActionParams(actionType)
  if (action.trigger_signals.length === 0) {
    action.trigger_signals = makeTaskAction(actionType).trigger_signals
  }
}

function handleTaskActionTypeChange(action: StrategyTaskActionInput, value: string | number | boolean): void {
  updateTaskActionType(action, value as StrategyActionType)
}

function signalLabel(signal: StrategySignalValue): string {
  if (signal === 1) return '1 买入/正向'
  if (signal === -1) return '-1 卖出/反向'
  return '0 观察/无动作'
}

function taskScopeOptionHint(option: TaskScopeOption): string {
  if (isTaskScopeDisabled(option)) return `不可选：${option.description}`
  return `${option.summary}；${option.description}`
}

function taskScheduleOptionHint(option: TaskScheduleOption): string {
  if (isTaskScheduleDisabled(option)) return `不可选：${option.description}`
  return option.description
}

function isStockScope(scopeType: StrategyTargetScopeType): boolean {
  return ['watchlist', 'trade_account', 'stock_pool', 'all_market', 'custom_stock_list', 'stock_list', 'position_group'].includes(scopeType)
}

function buildTargetParams(scopeType: StrategyTargetScopeType, scene: StrategySceneType): Record<string, unknown> & {
  scope_id?: string
  scope_name?: string
  ts_codes?: string[]
  index_codes?: string[]
  start_date?: string
  end_date?: string
} {
  if (scopeType === 'trade_account') {
    return {
      scope_id: targetParams.trade_review_group_id,
      scope_name: tradeAccountLabel(targetParams.trade_review_group_id),
      trade_review_group_id: targetParams.trade_review_group_id,
    }
  }
  if (scopeType === 'stock_pool') {
    return {
      scope_id: targetParams.stock_pool_id,
      scope_name: stockPoolLabel(targetParams.stock_pool_id),
      stock_pool_id: targetParams.stock_pool_id,
    }
  }
  if (scopeType === 'all_market') {
    return {
      start_date: targetParams.date_range[0],
      end_date: targetParams.date_range[1],
      exclude_st: true,
      ...(['backtest', 'sim_trade'].includes(scene) ? { trade_review_group_id: targetParams.trade_review_group_id } : {}),
    }
  }
  if (scopeType === 'custom_stock_list') {
    const tsCodes = targetParams.ts_codes_text
      .split(/\s|,|，/)
      .map((item) => item.trim())
      .filter(Boolean)
    return { ts_codes: tsCodes }
  }
  if (scopeType === 'index') {
    return {
      scope_id: targetParams.index_code,
      scope_name: indexLabel(targetParams.index_code),
      index_codes: [targetParams.index_code],
    }
  }
  return {}
}

function buildTargetSummary(option: TaskScopeOption, params: Record<string, unknown>): string {
  if (option.scope_type === 'trade_account') return `交割单：${params.scope_name || option.scope_name || ''}`
  if (option.scope_type === 'stock_pool') return `股池：${params.scope_name || option.scope_name || ''}`
  if (option.scope_type === 'all_market') {
    const range = params.start_date && params.end_date ? `${params.start_date} 至 ${params.end_date}` : '默认最近三个月'
    return `全市场 · 排除 ST · ${range}`
  }
  if (option.scope_type === 'custom_stock_list') {
    const count = Array.isArray(params.ts_codes) ? params.ts_codes.length : 0
    return `自定义股票列表 · ${count} 只`
  }
  if (option.scope_type === 'index') return `指数：${params.scope_name || '上证指数'}`
  return option.summary
}

function tradeAccountLabel(groupId: string): string {
  if (groupId === 'simulation_watch') return '模拟观察账户'
  if (groupId === 'auto_create') return '创建新交割单账户'
  return '实盘训练账户'
}

function stockPoolLabel(poolId: string): string {
  if (poolId === 'candidate_pool') return '候选池'
  if (poolId === 'confirm_pool') return '确认池'
  return '观察池'
}

function indexLabel(indexCode: string): string {
  if (indexCode === '399001.SZ') return '深证成指'
  if (indexCode === '399006.SZ') return '创业板指'
  return '上证指数'
}

function taskParamValue(key: string): string | number | boolean {
  if (taskForm.params && key in taskForm.params) {
    return taskForm.params[key] as string | number | boolean
  }
  const param = selectedStrategy.value?.param_schema.find((item) => item.key === key)
  return param?.default ?? ''
}

function updateTaskParam(key: string, value: string | number | boolean): void {
  taskForm.params = {
    ...(taskForm.params || {}),
    [key]: value,
  }
}

function validateTaskStep(step = taskStepIndex.value): boolean {
  if (step === 0) {
    if (!taskForm.name.trim()) {
      ElMessage.warning('请先填写任务名称')
      return false
    }
  }
  if (step === 2 && !taskForm.target_scope?.summary) {
    ElMessage.warning('请选择目标范围')
    return false
  }
  if (step === 2 && taskForm.target_scope.scope_type === 'custom_stock_list' && !targetParams.ts_codes_text.trim()) {
    ElMessage.warning('请填写自定义股票列表')
    return false
  }
  if (step === 2 && ['backtest', 'sim_trade'].includes(taskForm.scene_type) && taskForm.target_scope.scope_type === 'all_market' && !targetParams.trade_review_group_id) {
    ElMessage.warning('回测/模拟任务需要选择交割单账户')
    return false
  }
  if (step === 3) {
    if (!taskForm.schedule?.label) {
      ElMessage.warning('请选择调度方式')
      return false
    }
    if (taskForm.scene_type !== 'backtest' && taskForm.actions.length === 0) {
      ElMessage.warning('请至少选择一个动作')
      return false
    }
    if (taskForm.actions.some((action) => isTaskActionDisabled(action.action_type))) {
      ElMessage.warning('当前场景下存在不可用动作')
      return false
    }
    if (taskForm.actions.some((action) => action.trigger_signals.length === 0)) {
      ElMessage.warning('每个动作至少选择一个触发信号')
      return false
    }
  }
  return true
}

function nextTaskStep(): void {
  if (!validateTaskStep()) return
  taskStepIndex.value = Math.min(taskStepIndex.value + 1, taskStepItems.length - 1)
}

function prevTaskStep(): void {
  taskStepIndex.value = Math.max(taskStepIndex.value - 1, 0)
}

async function submitTaskDialog(): Promise<void> {
  if (!selectedStrategy.value) return
  if (!validateTaskStep(0) || !validateTaskStep(2) || !validateTaskStep(3)) return

  taskSubmitting.value = true
  try {
    const task = await createStrategySceneTask({
      name: taskForm.name.trim(),
      scene_type: taskForm.scene_type,
      strategy_key: selectedStrategy.value.strategy_key,
      target_scope: taskForm.target_scope,
      params: overrideStrategyParams.value ? taskForm.params : {},
      schedule: taskForm.schedule,
      notes: taskForm.notes?.trim(),
      actions: [...taskForm.actions],
    })
    tasks.value = await listStrategySceneTasks()
    taskDialogVisible.value = false
    taskStepIndex.value = 0
    ElMessage.success(`任务“${task.name}”已创建`)
    viewActiveTab.value = 'tasks'
  }
  finally {
    taskSubmitting.value = false
  }
}

function strategyTypeLabel(type: StrategyDefinition['impl_type']): string {
  if (type === 'builtin_code') return '内置策略'
  return type
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

.task-dialog-shell {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.task-steps {
  margin-bottom: 4px;
}

.task-step-card {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 8px;
  background: #fff;
  padding: 16px;
}

.task-step-head {
  margin-bottom: 16px;
}

.task-step-head strong {
  display: block;
  font-size: 15px;
  color: #0f172a;
}

.task-step-head p {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: #64748b;
}

.task-option-line {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.task-option-line span {
  color: #0f172a;
}

.task-option-line small {
  color: #64748b;
  line-height: 1.5;
}

.task-action-rule-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.task-action-rule-toolbar strong {
  display: block;
  font-size: 14px;
  color: #0f172a;
}

.task-action-rule-toolbar span {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
}

.task-action-rule-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-action-rule {
  padding: 12px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 8px;
  background: #fff;
}

.task-action-rule-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.task-action-rule-head strong {
  color: #0f172a;
  font-size: 14px;
}

.task-review-list {
  display: grid;
  gap: 10px;
}

.task-review-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 12px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 8px;
  background: #fff;
}

.task-review-row span {
  color: #64748b;
  font-size: 12px;
}

.task-review-row strong {
  flex: 1;
  text-align: right;
  font-size: 13px;
  line-height: 1.5;
  color: #0f172a;
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

  .task-action-rule-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .task-action-rule-toolbar :deep(.el-button) {
    width: 100%;
  }

  .task-review-row {
    flex-direction: column;
    gap: 6px;
  }

  .task-review-row strong {
    text-align: left;
  }
}
</style>
