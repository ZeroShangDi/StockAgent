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

  createTask(payload: CreateStrategySceneTaskInput): Promise<StrategySceneTask> {
    return api.post('/strategy-v2/tasks', payload)
  },
}

export async function listStrategyDefinitions(): Promise<StrategyDefinition[]> {
  return strategyV2Api.listStrategies()
}

export async function listStrategySceneTasks(): Promise<StrategySceneTask[]> {
  return strategyV2Api.listTasks()
}

export async function createStrategySceneTask(input: CreateStrategySceneTaskInput): Promise<StrategySceneTask> {
  return strategyV2Api.createTask(input)
}
