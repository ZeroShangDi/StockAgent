<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/hooks/useAuth'
import type { FormInstance, FormRules } from 'element-plus'

const router = useRouter()
const { register, isLoading } = useAuth()

// 表单引用
const formRef = ref<FormInstance>()

// 表单数据
const formData = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
  nickname: '',
  agree: false,
})

// 验证规则
const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 20, message: '用户名长度在 3 到 20 个字符', trigger: 'blur' },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入正确的邮箱格式', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, message: '密码长度不能少于 8 个字符', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== formData.password) {
          callback(new Error('两次输入的密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
  agree: [
    {
      validator: (_rule, value, callback) => {
        if (!value) {
          callback(new Error('请阅读并同意服务条款'))
        } else {
          callback()
        }
      },
      trigger: 'change',
    },
  ],
}

// 提交注册
async function handleSubmit() {
  const valid = await formRef.value?.validate()
  if (!valid) return
  
  await register({
    username: formData.username,
    email: formData.email,
    password: formData.password,
    nickname: formData.nickname || undefined,
  })
}
</script>

<template>
  <div class="register-page">
    <div class="register-card">
      <div class="hero">
        <div class="hero-badge">新用户</div>
        <h2 class="title">创建账户</h2>
        <p class="subtitle">配置一个专属账号，开始你的智能投资工作台。</p>
      </div>

      <el-form
        ref="formRef"
        :model="formData"
        :rules="rules"
        size="large"
        class="register-form"
        @submit.prevent="handleSubmit"
      >
        <div class="grid-row">
          <el-form-item prop="username">
            <el-input
              v-model="formData.username"
              placeholder="用户名"
              :prefix-icon="User"
            />
          </el-form-item>

          <el-form-item prop="nickname">
            <el-input
              v-model="formData.nickname"
              placeholder="昵称（可选）"
              :prefix-icon="UserFilled"
            />
          </el-form-item>
        </div>

        <el-form-item prop="email">
          <el-input
            v-model="formData.email"
            placeholder="邮箱"
            :prefix-icon="Message"
          />
        </el-form-item>

        <div class="grid-row">
          <el-form-item prop="password">
            <el-input
              v-model="formData.password"
              type="password"
              placeholder="密码（至少8位）"
              :prefix-icon="Lock"
              show-password
            />
          </el-form-item>

          <el-form-item prop="confirmPassword">
            <el-input
              v-model="formData.confirmPassword"
              type="password"
              placeholder="确认密码"
              :prefix-icon="Lock"
              show-password
            />
          </el-form-item>
        </div>

        <div class="security-note">
          建议使用字母、数字和符号组合，便于后续在不同设备安全登录。
        </div>

        <el-form-item prop="agree" class="agree-item">
          <el-checkbox v-model="formData.agree">
            我已阅读并同意
            <el-link type="primary" :underline="false">服务条款</el-link>
            和
            <el-link type="primary" :underline="false">隐私政策</el-link>
          </el-checkbox>
        </el-form-item>

        <el-form-item class="submit-item">
          <el-button
            type="primary"
            native-type="submit"
            :loading="isLoading"
            class="submit-btn"
          >
            创建并登录
          </el-button>
        </el-form-item>
      </el-form>

      <div class="login-link">
        <span>已有账户?</span>
        <el-link type="primary" @click="router.push('/login')">
          立即登录
        </el-link>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { User, UserFilled, Lock, Message } from '@element-plus/icons-vue'
export default {
  data() {
    return { User, UserFilled, Lock, Message }
  }
}
</script>

<style lang="scss" scoped>
.register-page {
  display: flex;
  align-items: center;
  justify-content: center;
  padding-top: 18px;

  @media (max-width: 768px) {
    padding-top: 10px;
  }
}

.register-card {
  width: 100%;
  max-width: 396px;
  padding: 30px 28px 26px;
  border-radius: 24px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(247, 250, 255, 0.98));
  box-shadow:
    0 28px 56px rgba(15, 23, 42, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(148, 163, 184, 0.18);

  @media (max-width: 768px) {
    max-width: 100%;
    padding: 24px 20px 22px;
    border-radius: 20px;
  }

  .hero {
    margin-bottom: 24px;
  }

  .hero-badge {
    display: inline-flex;
    align-items: center;
    padding: 6px 10px;
    margin-bottom: 14px;
    border-radius: 999px;
    background: rgba(37, 99, 235, 0.08);
    color: #1d4ed8;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.04em;
  }

  .title {
    font-size: 30px;
    font-weight: 700;
    color: var(--text-primary);
    line-height: 1.1;
    margin-bottom: 10px;
  }
  
  .subtitle {
    color: var(--text-secondary);
    line-height: 1.6;
  }

  .register-form {
    .el-form-item {
      margin-bottom: 16px;
    }

    :deep(.el-input__wrapper) {
      min-height: 46px;
      border-radius: 14px;
      padding: 4px 14px;
      background: rgba(255, 255, 255, 0.88);
    }
  }

  .grid-row {
    display: grid;
    grid-template-columns: 1fr;
    gap: 0 14px;

    @media (min-width: 860px) {
      grid-template-columns: 1fr 1fr;
    }
  }

  .security-note {
    margin: 4px 0 18px;
    padding: 10px 12px;
    border-radius: 14px;
    background: rgba(248, 250, 252, 0.9);
    color: var(--text-tertiary);
    font-size: 12px;
    line-height: 1.6;
  }

  .agree-item {
    margin-bottom: 18px;
  }

  :deep(.el-checkbox) {
    line-height: 1.6;
    white-space: normal;
  }

  .submit-item {
    margin-bottom: 8px;
  }

  .submit-btn {
    width: 100%;
    height: 50px;
    border-radius: 14px;
    font-size: 15px;
    font-weight: 700;
    box-shadow: 0 12px 30px rgba(37, 99, 235, 0.26);
  }

  .login-link {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 6px;
    margin-top: 10px;
    color: var(--text-secondary);
    font-size: 14px;
  }
}
</style>
