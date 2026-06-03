/**
 * 系统状态 API
 */

import { api } from '../client'
import type {
  AutomationOverviewResponse,
  SystemCozePluginStatusResponse,
  SystemDataSyncBackfillJobAction,
  SystemDataSyncBackfillJob,
  SystemDataSyncStatusPanel,
  SystemManualSyncTask,
  SystemStatusOverview,
  SystemStatusReport,
  SystemStatusSectionResponse,
} from '../types'

export const systemApi = {
  getSystemStatus(): Promise<SystemStatusReport> {
    return api.get('/system/status')
  },

  getSystemStatusOverview(forceRefresh = false): Promise<SystemStatusOverview> {
    return api.get('/system/status/overview', {
      params: { force_refresh: forceRefresh },
    })
  },

  getSystemStatusSection(
    section: 'services' | 'data_sources' | 'datasets' | 'features',
    forceRefresh = false,
  ): Promise<SystemStatusSectionResponse> {
    return api.get(`/system/status/sections/${section}`, {
      params: { force_refresh: forceRefresh },
    })
  },

  getCozePluginStatus(forceRefresh = false): Promise<SystemCozePluginStatusResponse> {
    return api.get('/system/status/coze', {
      params: { force_refresh: forceRefresh },
    })
  },

  getAutomationOverview(): Promise<AutomationOverviewResponse> {
    return api.get('/system/automations')
  },

  getDataSyncStatus(): Promise<SystemDataSyncStatusPanel> {
    return api.get('/system/datasync/status')
  },

  enqueueDataSyncBackfillJob(dataset: string, tradeDate: string, priority = 100): Promise<SystemDataSyncBackfillJob> {
    return api.post('/system/datasync/backfill-jobs', {
      dataset,
      trade_date: tradeDate,
      priority,
    })
  },

  operateDataSyncBackfillJob(
    jobId: string,
    action: SystemDataSyncBackfillJobAction,
  ): Promise<SystemDataSyncBackfillJob> {
    return api.patch(`/system/datasync/backfill-jobs/${jobId}/action`, {
      action,
    })
  },

  startManualGapFillSync(lookbackDays = 3): Promise<SystemManualSyncTask> {
    return api.post('/system/manual-sync/gap-fill', {
      lookback_days: lookbackDays,
    })
  },

  getLatestManualGapFillSync(): Promise<SystemManualSyncTask> {
    return api.get('/system/manual-sync/latest', {
      skipErrorToast: true,
    })
  },

  getManualGapFillSyncTask(taskId: string): Promise<SystemManualSyncTask> {
    return api.get(`/system/manual-sync/tasks/${taskId}`, {
      skipErrorToast: true,
    })
  },
}

export default systemApi
