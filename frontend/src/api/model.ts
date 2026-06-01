import type { ModelInfo } from "../types/model_config"
import api from "../utils/api"
import { randomString } from "../utils/common"
export const getModelInfos = async () => { 
    const response = await api.get('/model/modelinfo/getlist')
    return response.data.data.filter((item:ModelInfo) => item.type === 'chatllm')
}

export const getEmbeddingModelInfos = async () => { 
    try {
        const response = await api.get('/model/modelinfo/getlist')
        console.log('获取所有模型信息:', response.data.data)
        const embeddingModels = response.data.data.filter((item:ModelInfo) => item.type === 'embedding')
        console.log('过滤后的嵌入模型:', embeddingModels)
        return embeddingModels
    } catch (error) {
        console.error('获取嵌入模型失败:', error)
        return []
    }
}

export const getModelInfo = async (id: number) => { 
    const response = await api.get(`/model/modelinfo/get/${id}`)
    return response.data.data
}
export const getModelConfig = async (id: number, options?: { silent?: boolean }) => {
    if (!id || id <= 0) {
        return null
    }
    try {
        const config: any = {}
        if (options?.silent) config._silent403 = true
        const response = await api.get(`/model/modelconfig/get/${id}`, config)
        return response.data.data
    } catch (error: any) {
        if (error.response?.status === 404 || error.response?.status === 500 || error.response?.status === 403) {
            return null
        }
        throw error
    }
}

export const getModelConfigs = async () => { 
    const response = await api.get('/model/modelconfig/getpublic')
    return response.data.data
}
export const fetchOwnConfigs = async () => { 
    const response = await api.get('/model/modelconfig/getuser')
    return response.data.data
}

export const getUserModelConfig = async (user_id: number) => { 
    const response = await api.get(`/model/modelconfig/getuser/${user_id}`)
    return response.data.data
}

export const createConfig = async (data: any) => { 
    data.share_id = randomString(10)
    data.scope = data.is_private ? 'private' : (data.scope || 'public')
    return await api.post('/model/modelconfig/create', data)
}

export const updateConfig = async (data: any) => { 
    data.scope = data.is_private ? 'private' : (data.scope || 'public')
    const response = await api.post('/model/modelconfig/update', data)
    return response.data.data
}

export const deleteModelConfig = async (id: number) => { 
    return await api.delete(`/model/modelconfig/delete/${id}`)
}

export const getModelConfigByShareId = async (share_id: string) => { 
    const response = await api.post(`/model/modelconfig/getshare`,{share_id:share_id})
    return response.data.data
}
