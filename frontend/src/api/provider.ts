import api from "../utils/api";

export interface Provider {
  id: number;
  name: string;
  code: string;
  provider_type: string;
  is_active: boolean;
}

/**
 * 获取所有供应商列表
 */
export const getProviders = async (is_active?: boolean): Promise<Provider[]> => {
  const params: Record<string, string | number> = {};
  if (is_active !== undefined) {
    params.is_active = is_active;
  }
  const response = await api.get('/provider/providers', { params });
  return response.data.data;
};

