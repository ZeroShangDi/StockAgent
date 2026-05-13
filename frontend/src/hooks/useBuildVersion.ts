import { computed, onBeforeUnmount, reactive } from 'vue'

interface BuildInfo {
  buildId: string
  buildTime: string
  commitSha: string
  branch: string
}

interface RemoteBuildInfo {
  buildId?: string
  buildTime?: string
  commitSha?: string
  branch?: string
}

const CURRENT_BUILD: BuildInfo = __APP_BUILD_INFO__
const POLL_INTERVAL_MS = 30000
const AUTO_REFRESH_SECONDS = 10

const state = reactive({
  started: false,
  updateDetected: false,
  countdown: AUTO_REFRESH_SECONDS,
  remoteBuild: null as BuildInfo | null,
})

let pollTimer: number | null = null
let countdownTimer: number | null = null

function normalizeRemoteBuild(payload: RemoteBuildInfo): BuildInfo | null {
  if (!payload?.buildId || !payload?.buildTime) {
    return null
  }

  return {
    buildId: String(payload.buildId),
    buildTime: String(payload.buildTime),
    commitSha: String(payload.commitSha || ''),
    branch: String(payload.branch || ''),
  }
}

function formatBuildTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

async function fetchRemoteBuild(): Promise<BuildInfo | null> {
  const response = await fetch(`/version.json?t=${Date.now()}`, {
    cache: 'no-store',
  })

  if (!response.ok) {
    throw new Error(`Failed to fetch version info: ${response.status}`)
  }

  const payload = (await response.json()) as RemoteBuildInfo
  return normalizeRemoteBuild(payload)
}

function stopCountdown(): void {
  if (countdownTimer) {
    clearInterval(countdownTimer)
    countdownTimer = null
  }
}

function reloadPage(): void {
  window.location.reload()
}

function startCountdown(): void {
  stopCountdown()
  state.countdown = AUTO_REFRESH_SECONDS

  countdownTimer = window.setInterval(() => {
    state.countdown -= 1

    if (state.countdown <= 0) {
      stopCountdown()
      reloadPage()
    }
  }, 1000)
}

async function checkForUpdate(): Promise<void> {
  try {
    const remoteBuild = await fetchRemoteBuild()
    if (!remoteBuild) {
      return
    }

    state.remoteBuild = remoteBuild

    if (!state.updateDetected && remoteBuild.buildId !== CURRENT_BUILD.buildId) {
      state.updateDetected = true
      startCountdown()
    }
  } catch (error) {
    console.warn('[BuildVersion] Failed to check remote version', error)
  }
}

function stopMonitoring(): void {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  stopCountdown()
  state.started = false
}

function startMonitoring(): void {
  if (state.started || typeof window === 'undefined' || import.meta.env.DEV) {
    return
  }

  state.started = true
  void checkForUpdate()
  pollTimer = window.setInterval(() => {
    void checkForUpdate()
  }, POLL_INTERVAL_MS)
}

export function useBuildVersion() {
  startMonitoring()

  onBeforeUnmount(() => {
    // 根组件卸载时清理；正常 SPA 生命周期里只会发生一次
    stopMonitoring()
  })

  const buildTimeLabel = computed(() => formatBuildTime(CURRENT_BUILD.buildTime))
  const buildSummary = computed(() => {
    const sha = CURRENT_BUILD.commitSha ? CURRENT_BUILD.commitSha.slice(0, 7) : 'local'
    return `${buildTimeLabel.value} · ${sha}`
  })
  const remoteBuildSummary = computed(() => {
    if (!state.remoteBuild) {
      return ''
    }
    const sha = state.remoteBuild.commitSha ? state.remoteBuild.commitSha.slice(0, 7) : 'remote'
    return `${formatBuildTime(state.remoteBuild.buildTime)} · ${sha}`
  })

  return {
    currentBuild: CURRENT_BUILD,
    buildSummary,
    updateDetected: computed(() => state.updateDetected),
    countdown: computed(() => state.countdown),
    remoteBuildSummary,
    reloadPage,
  }
}
