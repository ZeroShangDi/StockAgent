import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { practiceApi, type PracticeSessionState, type PracticeTradeRequest } from '@/api'

export function usePracticeSession() {
  const session = ref<PracticeSessionState | null>(null)
  const loading = ref(false)
  const starting = ref(false)
  const stepping = ref(false)
  const finishing = ref(false)
  const tradingAction = ref('')

  const hasActiveSession = computed(() => session.value?.status === 'active')
  const actionBusy = computed(() => (
    loading.value
    || starting.value
    || stepping.value
    || finishing.value
    || tradingAction.value !== ''
  ))

  async function loadLatestSession(): Promise<void> {
    loading.value = true
    try {
      session.value = await practiceApi.getLatestSession()
    } catch {
      session.value = null
    } finally {
      loading.value = false
    }
  }

  async function loadSession(sessionId: string): Promise<void> {
    loading.value = true
    try {
      session.value = await practiceApi.getSession(sessionId)
    } catch {
      session.value = null
    } finally {
      loading.value = false
    }
  }

  async function startSession(forceConfirm = true): Promise<void> {
    if (forceConfirm && hasActiveSession.value) {
      try {
        await ElMessageBox.confirm(
          '开始新的一局会自动结束当前练习并平掉剩余持仓，确定继续吗？',
          '重新开局确认',
          {
            type: 'warning',
            confirmButtonText: '继续',
            cancelButtonText: '取消',
          },
        )
      } catch {
        return
      }
    }

    starting.value = true
    try {
      session.value = await practiceApi.startSession({})
      ElMessage.success('新的练习样本已就绪')
    } catch {
      ElMessage.error('重开失败，请稍后重试')
      await loadLatestSession()
    } finally {
      starting.value = false
    }
  }

  async function stepSession(steps: number): Promise<void> {
    if (!session.value) return
    stepping.value = true
    try {
      session.value = await practiceApi.stepSession(session.value.session_id, steps)
      if (session.value.status === 'completed') {
        ElMessage.success('练习样本已走完，结果已揭晓')
      }
    } finally {
      stepping.value = false
    }
  }

  async function trade(action: PracticeTradeRequest['action'], allocationPct: number): Promise<void> {
    if (!session.value) return
    tradingAction.value = `${action}-${allocationPct}`
    try {
      session.value = await practiceApi.trade(session.value.session_id, {
        action,
        allocation_pct: allocationPct,
      })
      const actionMap: Record<string, string> = {
        buy: '买入',
        sell: '卖出',
        close: '平仓',
      }
      ElMessage.success(`${actionMap[action] || action}操作已记录`)
    } finally {
      tradingAction.value = ''
    }
  }

  async function finishSession(): Promise<void> {
    if (!session.value) return
    try {
      await ElMessageBox.confirm(
        '结束后会立即揭晓真实股票，并对剩余持仓自动平仓。确定结束本局吗？',
        '结束练习',
        {
          type: 'warning',
          confirmButtonText: '结束并揭晓',
          cancelButtonText: '继续练习',
        },
      )
    } catch {
      return
    }

    finishing.value = true
    try {
      session.value = await practiceApi.finishSession(session.value.session_id)
      ElMessage.success('本局练习已结束')
    } finally {
      finishing.value = false
    }
  }

  return {
    session,
    loading,
    starting,
    stepping,
    finishing,
    tradingAction,
    hasActiveSession,
    actionBusy,
    loadLatestSession,
    loadSession,
    startSession,
    stepSession,
    trade,
    finishSession,
  }
}
