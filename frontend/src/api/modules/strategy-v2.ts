import { api } from '../client'

import type {
  CreateStrategySceneTaskInput,
  StrategyDefinition,
  StrategySceneTask,
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
