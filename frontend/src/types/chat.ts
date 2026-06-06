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

/** Agent 工具调用记录 */
export interface ToolCallRecord {
  tool: string;
  args: Record<string, unknown>;
  result?: Record<string, unknown>;
  callId: string;
  latencyMs?: number;
  status: 'calling' | 'done' | 'error';
}

/** Agent Trace Span */
export interface TraceSpan {
  span_id: string;
  name: string;
  type: string;
  latency_ms: number;
  tokens_used: number;
  status: string;
  error?: string;
}

/** Agent 追踪信息 */
export interface TraceInfo {
  trace_id: string;
  total_latency_ms: number;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  llm_calls: number;
  tool_calls: number;
  spans: TraceSpan[];
}

/** 检索过程步骤 */
export interface RetrievalStep {
  step: string;
  [key: string]: unknown;
}

/** 记忆管理统计 */
export interface MemoryStats {
  total_tokens: number;
  max_tokens: number;
  usage_ratio: number;
  message_count: number;
  needs_compression: boolean;
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
  /** 检索过程（展示给用户的思考步骤） */
  retrievalProcess?: RetrievalStep[];
  /** 流式计时与 token 统计 */
  streamStartTime?: number;
  streamTokenCount?: number;
  /** Agent 相关字段 */
  isStreaming?: boolean;
  agentState?: string;
  agentStateLabel?: string;
  toolCalls?: ToolCallRecord[];
  thinkingContent?: string;
  trace?: TraceInfo;
  memoryStats?: MemoryStats;
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
