<script setup lang="ts">
import { useBuildVersion } from '@/hooks/useBuildVersion'

const {
  currentBuild,
  buildSummary,
  updateDetected,
  countdown,
  remoteBuildSummary,
  reloadPage,
} = useBuildVersion()
</script>

<template>
  <div class="build-version-widget">
    <div class="build-version-badge" :title="`构建分支：${currentBuild.branch || 'unknown'}`">
      <span class="build-version-label">当前版本</span>
      <span class="build-version-value">{{ buildSummary }}</span>
    </div>

    <Transition name="build-update">
      <div v-if="updateDetected" class="build-update-banner" role="alert">
        <div class="build-update-text">
          <strong>检测到新版本已部署</strong>
          <span>最新构建：{{ remoteBuildSummary }}</span>
          <span>{{ countdown }} 秒后自动刷新页面</span>
        </div>
        <button class="build-update-button" type="button" @click="reloadPage">
          立即刷新
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped lang="scss">
.build-version-widget {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 3000;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 12px;
  pointer-events: none;
}

.build-version-badge,
.build-update-banner {
  pointer-events: auto;
}

.build-version-badge {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 10px 14px;
  border-radius: 999px;
  color: #ecfdf5;
  background:
    linear-gradient(135deg, rgba(10, 22, 43, 0.92), rgba(21, 128, 61, 0.9));
  box-shadow: 0 14px 34px rgba(15, 23, 42, 0.22);
  backdrop-filter: blur(16px);
  font-size: 12px;
}

.build-version-label {
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.78);
}

.build-version-value {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.build-update-banner {
  display: flex;
  align-items: center;
  gap: 16px;
  max-width: min(520px, calc(100vw - 36px));
  padding: 16px 18px;
  border-radius: 20px;
  background: rgba(255, 248, 235, 0.98);
  border: 1px solid rgba(245, 158, 11, 0.28);
  box-shadow: 0 18px 40px rgba(120, 53, 15, 0.18);
  color: #7c2d12;
}

.build-update-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  line-height: 1.45;
}

.build-update-button {
  border: none;
  border-radius: 999px;
  background: #b45309;
  color: #fff;
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.build-update-button:hover {
  background: #92400e;
}

.build-update-enter-active,
.build-update-leave-active {
  transition: all 0.24s ease;
}

.build-update-enter-from,
.build-update-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

@media (max-width: 768px) {
  .build-version-widget {
    right: 12px;
    left: 12px;
    bottom: 12px;
    align-items: stretch;
  }

  .build-version-badge {
    justify-content: space-between;
  }

  .build-update-banner {
    flex-direction: column;
    align-items: stretch;
  }

  .build-update-button {
    width: 100%;
  }
}
</style>
