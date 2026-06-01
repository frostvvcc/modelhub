export interface SourceCitation {
  content: string;
  source: string;
  chunk_id: string;
  similarity: number;
  vector_score: number;
  bm25_score: number;
  final_score?: number;
  retrieval_method: string;
  document_id?: string | number;
  vector_db_id?: number;
  vector_db_name?: string;
  retrieval_layer?: string;
  citation_label?: string;
  confidence_score?: number;
  confidence_label?: string;
}

export interface QuoteInfo {
  content: string;
  role: 'user' | 'assistant';
}

export class ChatMessage {
  role!: "system" | "user" | "assistant";
  content!: string;
  create_at!: string;
  quote?: QuoteInfo;
  sources?: SourceCitation[];
  grounded_ratio?: number;
  grounded_level?: string;
  rag_info?: {
    used_knowledge_base: boolean;
    vector_db_id: number | null;
    vector_db_ids?: number[];
    queried_vector_db_ids?: number[];
    retrieval_layers?: string[];
    fallback_used?: boolean;
    total_results: number;
    avg_similarity: number;
    grounded_level?: string;
  };
  attachment_info?: {
    vector_db_id: number | null;
    vector_db_name: string | null;
    document_ids: number[];
    filenames: string[];
    errors?: string[];
  } | null;
}
export class Conversation {
  id!: number;
  name!: string;
  chat_history!: number;
  model_config_id!: number;
  create_at!: string;
  update_at!: string;
  type!: number;
  count?: number;
  messages!: ChatMessage[];
  last_message?: ChatMessage;
}
