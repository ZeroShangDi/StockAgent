import { api } from '../client'

import type {
  CreateStrategySceneTaskInput,
  StrategyActionAudit,
  StrategyDefinition,
  StrategySceneTask,
  StrategyTaskRun,
  StrategyTaskRunItem,
  StrategyTaskRunLog,
} from '@/types/strategy-v2'

interface ListResponse<T> {
  items: T[]
}

export const strategyV2Api = {
  listStrategies(): Promise<StrategyDefinition[]> {
    return api.get<ListResponse<StrategyDefinition>>('/strategy-v2/strategies').then((response) => response.items)
  },

  listTasks(): Promise<StrategySceneTask[]> {
    return api.get<ListResponse<StrategySceneTask>>('/strategy-v2/tasks').then((response) => response.items)
  },

  getTask(taskId: string): Promise<StrategySceneTask> {
    return api.get(`/strategy-v2/tasks/${taskId}`)
  },

  createTask(payload: CreateStrategySceneTaskInput): Promise<StrategySceneTask> {
    return api.post('/strategy-v2/tasks', payload)
  },

  deleteTask(taskId: string): Promise<{ message: string }> {
    return api.delete(`/strategy-v2/tasks/${taskId}`)
  },

  listTaskRuns(taskId: string): Promise<StrategyTaskRun[]> {
    return api.get<ListResponse<StrategyTaskRun>>(`/strategy-v2/tasks/${taskId}/runs`).then((response) => response.items)
  },

  runTask(taskId: string): Promise<StrategyTaskRun> {
    return api.post(`/strategy-v2/tasks/${taskId}/runs`)
  },

  cancelRun(runId: string): Promise<StrategyTaskRun> {
    return api.post(`/strategy-v2/runs/${runId}/cancel`)
  },

  retryRun(runId: string): Promise<StrategyTaskRun> {
    return api.post(`/strategy-v2/runs/${runId}/retry`)
  },

  getRun(runId: string): Promise<StrategyTaskRun> {
    return api.get(`/strategy-v2/runs/${runId}`)
  },

  getRunItems(runId: string): Promise<StrategyTaskRunItem[]> {
    return api.get<ListResponse<StrategyTaskRunItem>>(`/strategy-v2/runs/${runId}/items`).then((response) => response.items)
  },

  getRunLogs(runId: string): Promise<StrategyTaskRunLog[]> {
    return api.get<ListResponse<StrategyTaskRunLog>>(`/strategy-v2/runs/${runId}/logs`).then((response) => response.items)
  },

  getRunActionAudits(runId: string): Promise<StrategyActionAudit[]> {
    return api.get<ListResponse<StrategyActionAudit>>(`/strategy-v2/runs/${runId}/action-audits`).then((response) => response.items)
  },

  addStockToTask(taskId: string, tsCode: string, config?: Record<string, unknown>): Promise<StrategySceneTask> {
    return api.post(`/strategy-v2/tasks/${taskId}/stocks`, {
      ts_code: tsCode.toUpperCase(),
      config,
    })
  },

  updateTaskStockConfig(taskId: string, tsCode: string, config: Record<string, unknown>): Promise<StrategySceneTask> {
    return api.put(`/strategy-v2/tasks/${taskId}/stocks/${tsCode.toUpperCase()}/config`, {
      config,
    })
  },
}

export async function listStrategyDefinitions(): Promise<StrategyDefinition[]> {
  return strategyV2Api.listStrategies()
}

export async function listStrategySceneTasks(): Promise<StrategySceneTask[]> {
  return strategyV2Api.listTasks()
}

export async function getStrategySceneTask(taskId: string): Promise<StrategySceneTask> {
  return strategyV2Api.getTask(taskId)
}

export async function createStrategySceneTask(input: CreateStrategySceneTaskInput): Promise<StrategySceneTask> {
  return strategyV2Api.createTask(input)
}

export async function deleteStrategySceneTask(taskId: string): Promise<{ message: string }> {
  return strategyV2Api.deleteTask(taskId)
}

export async function listTaskRuns(taskId: string): Promise<StrategyTaskRun[]> {
  return strategyV2Api.listTaskRuns(taskId)
}

export async function runStrategySceneTask(taskId: string): Promise<StrategyTaskRun> {
  return strategyV2Api.runTask(taskId)
}

export async function cancelTaskRun(runId: string): Promise<StrategyTaskRun> {
  return strategyV2Api.cancelRun(runId)
}

export async function retryTaskRun(runId: string): Promise<StrategyTaskRun> {
  return strategyV2Api.retryRun(runId)
}

export async function getTaskRun(runId: string): Promise<StrategyTaskRun> {
  return strategyV2Api.getRun(runId)
}

export async function getRunItems(runId: string): Promise<StrategyTaskRunItem[]> {
  return strategyV2Api.getRunItems(runId)
}

export async function getRunLogs(runId: string): Promise<StrategyTaskRunLog[]> {
  return strategyV2Api.getRunLogs(runId)
}

export async function getRunActionAudits(runId: string): Promise<StrategyActionAudit[]> {
  return strategyV2Api.getRunActionAudits(runId)
}

export async function addStockToStrategySceneTask(
  taskId: string,
  tsCode: string,
  config?: Record<string, unknown>,
): Promise<StrategySceneTask> {
  return strategyV2Api.addStockToTask(taskId, tsCode, config)
}

export async function updateStrategySceneTaskStockConfig(
  taskId: string,
  tsCode: string,
  config: Record<string, unknown>,
): Promise<StrategySceneTask> {
  return strategyV2Api.updateTaskStockConfig(taskId, tsCode, config)
}
