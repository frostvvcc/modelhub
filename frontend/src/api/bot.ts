import api from "../utils/api";

export interface BotCreate {
  name: string;
  description?: string;
  avatar?: string;
  system_prompt?: string;
  greeting?: string;
  forbidden_topics?: string[];
  model_config_id?: number;
  vector_db_ids?: number[];
  organization_id?: number | null;
}

export interface BotResponse {
  id: number;
  name: string;
  description?: string;
  avatar?: string;
  system_prompt?: string;
  greeting?: string;
  forbidden_topics: string[];
  model_config_id?: number;
  vector_db_ids: number[];
  user_id: number;
  creator_name?: string;
  organization_id?: number | null;
  org_name?: string;
  created_at?: string;
  updated_at?: string;
}

export interface BotChatSource {
  content: string;
  source: string;
  chunk_id: string;
  similarity: number;
  vector_score: number;
  bm25_score: number;
  final_score: number;
  retrieval_method: string;
  vector_db_id: number;
  vector_db_name: string;
  retrieval_layer: string;
  citation_label: string;
  confidence_score: number;
  confidence_label: string;
}

export interface BotChatRagInfo {
  used_knowledge_base: boolean;
  vector_db_ids: number[];
  queried_vector_db_ids: number[];
  retrieval_layers: string[];
  fallback_used: boolean;
  total_results: number;
  avg_similarity: number;
  grounded_level: string;
}

export interface BotChatResponse {
  answer: string;
  conversation_id?: string;
  forbidden_topic_hit?: string;
  model_name?: string;
  rag_info?: BotChatRagInfo;
  sources?: BotChatSource[];
  grounded_ratio?: number;
  grounded_level?: string;
}

export const createBot = async (data: BotCreate): Promise<BotResponse> => {
  const response = await api.post("/bots", data);
  return response.data;
};

export const listBots = async (): Promise<BotResponse[]> => {
  const response = await api.get("/bots");
  return response.data.data;
};

export const listOwnBots = async (): Promise<BotResponse[]> => {
  const response = await api.get("/bots/own");
  return response.data.data;
};

export const getBot = async (id: number): Promise<BotResponse> => {
  const response = await api.get(`/bots/${id}`);
  return response.data;
};

export const updateBot = async (id: number, data: Partial<BotCreate>): Promise<BotResponse> => {
  const response = await api.put(`/bots/${id}`, data);
  return response.data;
};

export const deleteBot = async (id: number): Promise<void> => {
  await api.delete(`/bots/${id}`);
};

export const botChat = async (
  botId: number,
  message: string,
  conversationId?: string,
): Promise<BotChatResponse> => {
  const response = await api.post(`/bots/${botId}/chat`, {
    message,
    conversation_id: conversationId,
  });
  return response.data;
};
