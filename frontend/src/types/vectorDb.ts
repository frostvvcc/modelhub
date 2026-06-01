import type { document } from "./document";

// types/vectorDb.ts
export class VectorDbBase {
  id!: number;
  name!: string;
  describe!: string;
  user_id?: number;
  creator_name?: string;
  organization_id?: number | null;
  org_name?: string | null;
  created_at!: string;
  updated_at!: string;
}

export interface VectorDbForm {
  id: number
  name: string
  describe: string
  embedding_id: number
  document_similarity: number
  user_id?: number
  organization_id?: number | null
  created_at: string
  updated_at: string
  documents: document[]
}
