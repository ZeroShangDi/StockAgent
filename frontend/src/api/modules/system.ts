/**
 * 系统状态 API
 */

import { api } from '../client'
import type { SystemStatusOverview, SystemStatusReport, SystemStatusSectionResponse } from '../types'

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
}

export default systemApi
