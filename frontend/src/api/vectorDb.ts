import api from "../utils/api";
export const createVectorDb = async (data: Record<string, unknown>) => {
    const formData = new FormData()
    formData.append('name', data.name)
    formData.append('embedding_id', data.embedding_id.toString())
    if (data.describe) formData.append('describe', data.describe)
    formData.append('document_similarity', data.document_similarity.toString())
    if (data.organization_id != null) formData.append('organization_id', data.organization_id.toString())

    return await api.post('/vector/create', formData, {
        headers: {
            'Content-Type': 'multipart/form-data'
        }
    })
}

export const fetchOwnVectors = async (organizationId?: number) => {
    const params: Record<string, string | number> = {}
    if (organizationId) params.organization_id = organizationId
    const response = await api.get('/vector/list', { params })
    return response.data.data
}

export const fetchMyCreatedVectors = async () => {
    const response = await api.get('/vector/list/own')
    return response.data.data
}

export const getVectorDb = async (id: number) => { 
    const response = await api.get(`/vector/get/${id}`)
    return response.data.data
}

export const updateVectorDb = async (id: number, data: Record<string, unknown>) => { 
    return await api.post(`/vector/update/${id}`, data);
}


export const uploadDocument = async (formData: FormData) => {
    const response = await api.post('/vector/upload', formData);
    return response.data.data;
};

export const DownloadFile = async (id: number) => {
    const response = await api.get(`/vector/download_file/${id}`, {
      responseType: 'blob', // 指定响应类型为二进制数据
    });
    return response;
}
export const deleteDocument = async (id: number) => { 
    return await api.delete(`/vector/delete_file/${id}`)
}

export const archiveDocument = async (id: number) => {
    const response = await api.post(`/vector/document/${id}/archive`)
    return response.data.data
}

export const restoreDocument = async (id: number) => {
    const response = await api.post(`/vector/document/${id}/restore`)
    return response.data.data
}

export const deleteVectorDb = async (id: number) => { 
    const response = await api.delete(`/vector/delete/${id}`)
    return response.data.data
}

export const testConnect = async (id: number) => { 
    const response = await api.get(`/vector/connect/${id}`)
    return response.status === 200
}

export const queryVector = async (id: number, query_text: string, n_results: number) => { 
    const response = await api.post(`/vector/query/${id}`, {
        query_text: query_text,
        n_results: n_results
    })
    return response.data.data
}

// 获取文档树形结构
export const getDocumentsTree = async (vectorDbId: number) => {
    const response = await api.get(`/vector/${vectorDbId}/documents/tree`)
    return response.data.data
}

// 创建文件夹
export const createFolder = async (vectorDbId: number, name: string, parentId?: number) => {
    const formData = new FormData()
    formData.append('vector_db_id', vectorDbId.toString())
    formData.append('name', name)
    if (parentId) {
        formData.append('parent_id', parentId.toString())
    }
    const response = await api.post('/vector/folder/create', formData, {
        headers: {
            'Content-Type': 'multipart/form-data'
        }
    })
    return response.data.data
}

// 检索调试
export const debugQuery = async (vectorId: number, query: string, nResults: number = 10, alpha: number = 0.7, useHybrid: boolean = true) => {
    const response = await api.post(`/vector/${vectorId}/debug-query`, {
        query,
        n_results: nResults,
        alpha,
        use_hybrid: useHybrid
    })
    return response.data
}

// 重命名文档或文件夹
export const renameDocument = async (documentId: number, newName: string) => {
    const formData = new FormData()
    formData.append('new_name', newName)
    const response = await api.post(`/vector/document/${documentId}/rename`, formData, {
        headers: {
            'Content-Type': 'multipart/form-data'
        }
    })
    return response.data.data
}
