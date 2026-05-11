<script setup lang="ts">
import { computed, ref } from 'vue'
import { useUserStore } from '@/stores/user'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import type { NotificationChannel, NotificationProvider } from '@/api/types'

const userStore = useUserStore()

const activeTab = ref('profile')

const profileFormRef = ref<FormInstance>()
const profileForm = ref({
  nickname: userStore.nickname,
  email: userStore.userInfo?.email || '',
})
const profileSaving = ref(false)

const preferences = ref({
  theme: (userStore.preferences as any)?.theme || 'light',
  notification_enabled: (userStore.preferences as any)?.notification_enabled ?? true,
})
const prefSaving = ref(false)

const passwordFormRef = ref<FormInstance>()
const passwordForm = ref({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})
const passwordSaving = ref(false)

const passwordRules: FormRules = {
  oldPassword: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '密码长度不能少于 8 个字符', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请确认新密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== passwordForm.value.newPassword) {
          callback(new Error('两次输入的密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
}

const notificationChannels = computed(() => userStore.notificationChannels)
const channelDialogVisible = ref(false)
const channelSaving = ref(false)
const editingChannelId = ref('')
const channelFormRef = ref<FormInstance>()
const channelForm = ref({
  name: '',
  provider: 'wecom' as NotificationProvider,
  webhook: '',
})
const channelRules: FormRules = {
  name: [{ required: true, message: '请输入机器人名称', trigger: 'blur' }],
  provider: [{ required: true, message: '请选择渠道类型', trigger: 'change' }],
  webhook: [{ required: true, message: '请输入 Webhook 地址', trigger: 'blur' }],
}

const providerOptions: Array<{ label: string; value: NotificationProvider }> = [
  { label: '企业微信', value: 'wecom' },
  { label: '钉钉', value: 'dingtalk' },
]

function getProviderLabel(provider: NotificationProvider): string {
  return provider === 'dingtalk' ? '钉钉' : '企业微信'
}

function resetChannelForm(): void {
  editingChannelId.value = ''
  channelForm.value = {
    name: '',
    provider: 'wecom',
    webhook: '',
  }
}

function openCreateChannelDialog(): void {
  resetChannelForm()
  channelDialogVisible.value = true
}

function openEditChannelDialog(channel: NotificationChannel): void {
  editingChannelId.value = channel.channel_id
  channelForm.value = {
    name: channel.name,
    provider: channel.provider,
    webhook: channel.webhook,
  }
  channelDialogVisible.value = true
}

async function saveChannel(): Promise<void> {
  const valid = await channelFormRef.value?.validate()
  if (!valid) return

  channelSaving.value = true
  try {
    const payload = {
      name: channelForm.value.name.trim(),
      provider: channelForm.value.provider,
      webhook: channelForm.value.webhook.trim(),
    }
    const success = editingChannelId.value
      ? await userStore.updateNotificationChannel(editingChannelId.value, payload)
      : await userStore.createNotificationChannel(payload)
    if (!success) {
      ElMessage.error('保存通知机器人失败')
      return
    }
    ElMessage.success(editingChannelId.value ? '通知机器人已更新' : '通知机器人已添加')
    channelDialogVisible.value = false
  } finally {
    channelSaving.value = false
  }
}

async function removeChannel(channel: NotificationChannel): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认删除通知机器人“${channel.name}”吗？`,
      '删除通知机器人',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      }
    )
  } catch {
    return
  }
  const success = await userStore.deleteNotificationChannel(channel.channel_id)
  if (!success) {
    ElMessage.error('删除通知机器人失败')
    return
  }
  ElMessage.success('通知机器人已删除')
}

async function saveProfile() {
  profileSaving.value = true
  try {
    ElMessage.success('保存成功')
  } finally {
    profileSaving.value = false
  }
}

async function savePreferences() {
  prefSaving.value = true
  try {
    await userStore.updatePreferences(preferences.value)
    ElMessage.success('设置已保存')
  } finally {
    prefSaving.value = false
  }
}

async function changePassword() {
  const valid = await passwordFormRef.value?.validate()
  if (!valid) return

  passwordSaving.value = true
  try {
    ElMessage.success('密码修改成功')
    passwordForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
  } finally {
    passwordSaving.value = false
  }
}
</script>

<template>
  <div class="settings-view">
    <h1>设置</h1>

    <el-tabs v-model="activeTab" class="settings-tabs">
      <el-tab-pane label="个人信息" name="profile">
        <div class="settings-section card">
          <el-form
            ref="profileFormRef"
            :model="profileForm"
            label-width="100px"
            size="large"
          >
            <el-form-item label="用户名">
              <el-input :value="userStore.username" disabled />
            </el-form-item>

            <el-form-item label="昵称">
              <el-input v-model="profileForm.nickname" placeholder="输入昵称" />
            </el-form-item>

            <el-form-item label="邮箱">
              <el-input v-model="profileForm.email" disabled />
            </el-form-item>

            <el-form-item>
              <el-button type="primary" :loading="profileSaving" @click="saveProfile">
                保存修改
              </el-button>
            </el-form-item>
          </el-form>
        </div>
      </el-tab-pane>

      <el-tab-pane label="偏好设置" name="preferences">
        <div class="settings-section card">
          <el-form label-width="100px" size="large">
            <el-form-item label="主题">
              <el-radio-group v-model="preferences.theme">
                <el-radio value="light">浅色</el-radio>
                <el-radio value="dark">深色</el-radio>
              </el-radio-group>
            </el-form-item>

            <el-form-item label="消息通知">
              <el-switch v-model="preferences.notification_enabled" />
            </el-form-item>

            <el-form-item>
              <el-button type="primary" :loading="prefSaving" @click="savePreferences">
                保存设置
              </el-button>
            </el-form-item>
          </el-form>
        </div>
      </el-tab-pane>

      <el-tab-pane label="通知机器人" name="notifications">
        <div class="settings-section card">
          <div class="section-head">
            <div>
              <h3>通知机器人</h3>
              <p class="section-desc">在这里维护你自己的企业微信或钉钉 Webhook，监听策略里可以直接选择使用。</p>
            </div>
            <el-button type="primary" @click="openCreateChannelDialog">新增机器人</el-button>
          </div>

          <div v-if="notificationChannels.length" class="channel-list">
            <article
              v-for="channel in notificationChannels"
              :key="channel.channel_id"
              class="channel-card"
            >
              <div class="channel-main">
                <div class="channel-title-row">
                  <strong>{{ channel.name }}</strong>
                  <el-tag size="small" effect="plain">{{ getProviderLabel(channel.provider) }}</el-tag>
                </div>
                <div class="channel-webhook">{{ channel.webhook }}</div>
                <div class="channel-meta">
                  更新于 {{ new Date(channel.updated_at).toLocaleString() }}
                </div>
              </div>
              <div class="channel-actions">
                <el-button link type="primary" @click="openEditChannelDialog(channel)">编辑</el-button>
                <el-button link type="danger" @click="removeChannel(channel)">删除</el-button>
              </div>
            </article>
          </div>

          <el-empty v-else description="还没有配置通知机器人" />
        </div>
      </el-tab-pane>

      <el-tab-pane label="安全设置" name="security">
        <div class="settings-section card">
          <h3>修改密码</h3>

          <el-form
            ref="passwordFormRef"
            :model="passwordForm"
            :rules="passwordRules"
            label-width="100px"
            size="large"
            style="max-width: 400px"
          >
            <el-form-item label="当前密码" prop="oldPassword">
              <el-input
                v-model="passwordForm.oldPassword"
                type="password"
                show-password
              />
            </el-form-item>

            <el-form-item label="新密码" prop="newPassword">
              <el-input
                v-model="passwordForm.newPassword"
                type="password"
                show-password
              />
            </el-form-item>

            <el-form-item label="确认密码" prop="confirmPassword">
              <el-input
                v-model="passwordForm.confirmPassword"
                type="password"
                show-password
              />
            </el-form-item>

            <el-form-item>
              <el-button type="primary" :loading="passwordSaving" @click="changePassword">
                修改密码
              </el-button>
            </el-form-item>
          </el-form>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="channelDialogVisible"
      :title="editingChannelId ? '编辑通知机器人' : '新增通知机器人'"
      width="560px"
      :close-on-click-modal="false"
      @closed="resetChannelForm"
    >
      <el-form
        ref="channelFormRef"
        :model="channelForm"
        :rules="channelRules"
        label-width="92px"
      >
        <el-form-item label="名称" prop="name">
          <el-input v-model="channelForm.name" placeholder="例如：主力钉钉群 / 企业微信告警" />
        </el-form-item>
        <el-form-item label="渠道" prop="provider">
          <el-radio-group v-model="channelForm.provider">
            <el-radio
              v-for="option in providerOptions"
              :key="option.value"
              :value="option.value"
            >
              {{ option.label }}
            </el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="Webhook" prop="webhook">
          <el-input
            v-model="channelForm.webhook"
            type="textarea"
            :rows="4"
            placeholder="请输入企业微信或钉钉机器人 Webhook 地址"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="channelDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="channelSaving" @click="saveChannel">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style lang="scss" scoped>
.settings-view {
  max-width: 960px;
  margin: 0 auto;

  h1 {
    font-size: 24px;
    font-weight: 600;
    margin-bottom: 24px;
  }
}

.settings-tabs {
  :deep(.el-tabs__content) {
    padding-top: 20px;
  }
}

.settings-section {
  padding: 24px;

  h3 {
    margin: 0 0 8px;
  }
}

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.section-desc {
  margin: 0;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.channel-list {
  display: grid;
  gap: 12px;
}

.channel-card {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
  background: var(--el-fill-color-blank);
}

.channel-main {
  min-width: 0;
  flex: 1;
}

.channel-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.channel-webhook {
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
  word-break: break-all;
}

.channel-meta {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.channel-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
</style>
