// types/model.ts

export class ModelInfo {
  id!: number;
  model_name!: string;
  describe?: string | null;
  type!: string;
}

export class ModelConfigResponse {
  id!: number;
  name!: string;
  author!: string;
  base_model_name!: string;
  describe?: string | null;
  updated_at!: string;
}

export class ModelConfigBase{
  id!: number;
  name!: string;
  author!: string;
  base_model_name!: string;
  provider_name?: string | null;
  provider_code?: string | null;
  isFeatured!: boolean;
  describe!: string | null;
  avatar!: string | null;
  date!: string;
}
export class ModelConfig {
  id!: number;
  user_id!: number;
  name!: string;
  describe!: string | null;
  share_id!: string;
  base_model_id!: number;
  temperature!: number;
  top_p!: number;
  prompt!: string | null;
  prompt_variables?: string | null;
  knowledge_context_template?: string | null;
  citation_template?: string | null;
  refusal_strategy?: string | null;
  max_context_chars?: number;
  answer_with_citations?: boolean;
  created_at!: string;
  updated_at!: string;
  is_private!: boolean;
}

// 相关类型定义
export interface ModelConfigForm {
  id?: number | null;
  name: string;
  describe: string | null;
  base_model_id: number | null;
  temperature: number;
  top_p: number;
  prompt: string | null;
  prompt_variables?: string | null;
  knowledge_context_template?: string | null;
  citation_template?: string | null;
  refusal_strategy?: string | null;
  max_context_chars?: number;
  answer_with_citations?: boolean;
  is_private: boolean;
}

export const config_info_map : Record<string, string[]> = { 
  "通义": ["qwen-plus", "qwen-turbo", "qwen-max", "qwen-max-plus", "qwen-max-turbo", "qwen-max-plus-turbo", "qwen-max-pro", "qwen-max-pro-turbo", "qwen-max-pro-plus", "qwen-max-pro-plus-turbo"],
  "DeepSeek": ["deepseek-r1", "deepseek-v3"]
}
