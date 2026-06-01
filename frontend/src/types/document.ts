export class document { 
    id!: number;
    original_name!: string;
    type!: string;
    size!: number;
    save_path!: string;
    describe!: string;
    status?: 'processing' | 'success' | 'failed' | 'archived';
    error_message?: string | null;
    archived_at?: string | null;
    upload_at!: string;
}
