<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useRoute } from 'vue-router';
import { Connection, Delete, Edit, Back, Upload, Folder, FolderOpened, Document, Plus, QuestionFilled } from '@element-plus/icons-vue';
import type { VectorDbForm } from '../types/vectorDb';
import { getVectorDb, updateVectorDb, uploadDocument, deleteDocument, archiveDocument, restoreDocument, deleteVectorDb, DownloadFile, previewDocument, getDocumentsTree, createFolder, renameDocument, debugQuery } from '../api/vectorDb';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useRouter } from 'vue-router';
import type { ModelInfo } from '../types/model_config';
import { getEmbeddingModelInfos } from '../api/model';
import { queryVector } from '../api/vectorDb';
import { Search } from '@element-plus/icons-vue';
import { useUserStore } from '../stores/user';
import { ArrowRight } from '@element-plus/icons-vue';

const baseModels = ref<ModelInfo[]>([]);
const activeTab = ref('docs');

const orgDisplayName = computed(() => {
  if (!vectorDb.value.organization_id) return '私有';
  const orgName = (vectorDb.value as Record<string, unknown>).org_name;
  if (orgName) return orgName;
  const org = userStore.userOrganizations.find(o => o.id === vectorDb.value.organization_id);
  return org?.name || '组织';
});

const visibilityType = computed<'success' | 'warning' | 'info'>(() => {
  if (!vectorDb.value.organization_id) return 'info';
  const org = userStore.userOrganizations.find(o => o.id === vectorDb.value.organization_id);
  if (org?.type === 'school') return 'success';
  return 'warning';
});
const embeddingModelName = computed(() => baseModels.value.find(m => m.id == vectorDb.value.embedding_id)?.model_name || '未设置');
const totalDocCount = computed(() => getFlatDocuments(documentTree.value).length);
const route = useRoute();
const loading = ref(true);
const uploadLoading = ref(false);
const vectorDbId = ref<number>(parseInt(route.params.id as string));
const router = useRouter();
const queryInput = ref('');
const goBack = () => router.go(-1);
const userStore = useUserStore();

const canManage = computed(() => {
  const role = userStore.user?.role;
  if (role === 'admin') return true;
  return vectorDb.value.user_id === Number(userStore.user?.id);
});

const vectorDb = ref<VectorDbForm>({
  id: 0,
  name: '',
  describe: '',
  embedding_id: 0,
  document_similarity: 0,
  created_at: '',
  updated_at: '',
  documents: []
});

const documentTree = ref<Record<string, unknown>[]>([]);
const selectedParentId = ref<number | null>(null);
const viewMode = ref<'tree' | 'list'>('list');
const selectedDocument = ref<number | null>(null);

const uploadDialogVisible = ref(false);
const uploadFormRef = ref();
const uploadForm = ref({
  files: [] as File[],
  describe: '',
  parent_id: null as number | null,
  chunk_strategy: 'fixed',
  chunk_size: 800,
  chunk_overlap: 150
});

const chunkStrategyOptions = [
  { label: '固定长度', value: 'fixed' },
  { label: '句子边界', value: 'sentence' },
  { label: 'Markdown标题', value: 'markdown' }
];

const folderDialogVisible = ref(false);
const folderForm = ref({
  name: '',
  parent_id: null as number | null
});
const renameDialogVisible = ref(false);
const renameForm = ref({
  id: null as number | null,
  name: ''
});

const uploadRules = {
  files: [
    {
      required: true,
      validator: (rule: unknown, value: string, callback: (error?: Error) => void) => {
        if (uploadForm.value.files.length === 0) {
          callback(new Error('请至少选择一个文件'));
        } else {
          callback();
        }
      },
      trigger: 'change'
    }
  ],
  describe: [
    { required: true, message: '请输入文件描述', trigger: 'blur' }
  ]
};

const folderCount = computed(() => {
  let count = 0;
  const traverse = (nodes: Record<string, unknown>[]) => {
    for (const node of nodes) {
      if (node.is_folder) {
        count++;
        if (node.children?.length) traverse(node.children);
      }
    }
  };
  traverse(documentTree.value);
  return count;
});

const totalSize = computed(() => {
  let size = 0;
  const traverse = (nodes: Record<string, unknown>[]) => {
    for (const node of nodes) {
      if (!node.is_folder && node.size) size += node.size;
      if (node.children?.length) traverse(node.children);
    }
  };
  traverse(documentTree.value);
  return size;
});

const fetchVectorDbDetail = async () => {
  loading.value = true;
  try {
    vectorDb.value = await getVectorDb(vectorDbId.value);
    await fetchDocumentTree();
    loading.value = false;
  } catch (error) {
    console.error('获取知识库详情失败:', error);
    loading.value = false;
  }
};

const fetchDocumentTree = async () => {
  try {
    documentTree.value = await getDocumentsTree(vectorDbId.value);
  } catch (error) {
    console.error('获取文档树失败:', error);
    ElMessage.error('获取文档树失败');
  }
};

const handleFileChange = (uploadFile: { raw: File; name: string }, uploadFiles: Record<string, unknown>[]) => {
  uploadForm.value.files = uploadFiles.map(file => file.raw || file);
  return false;
};

const submitUpload = async () => {
  try {
    await uploadFormRef.value.validate();
    if (uploadForm.value.files.length === 0) {
      ElMessage.error('请选择要上传的文件');
      return;
    }
    uploadLoading.value = true;
    const formData = new FormData();
    uploadForm.value.files.forEach(file => {
      formData.append('files', file);
    });
    formData.append('describe', uploadForm.value.describe);
    formData.append('vector_db_id', vectorDbId.value.toString());
    formData.append('chunk_strategy', uploadForm.value.chunk_strategy);
    formData.append('chunk_size', uploadForm.value.chunk_size.toString());
    formData.append('chunk_overlap', uploadForm.value.chunk_overlap.toString());
    if (uploadForm.value.parent_id) {
      formData.append('parent_id', uploadForm.value.parent_id.toString());
    }
    await uploadDocument(formData);
    fetchVectorDbDetail();
    ElMessage.success(`成功上传 ${uploadForm.value.files.length} 个文档`);
    uploadDialogVisible.value = false;
    resetUploadForm();
  } catch (error) {
    console.error('上传文档失败:', error);
    ElMessage.error('上传文档失败');
  } finally {
    uploadLoading.value = false;
  }
};

const resetUploadForm = () => {
  uploadForm.value = {
    files: [],
    describe: '',
    parent_id: null,
    chunk_strategy: 'fixed',
    chunk_size: 800,
    chunk_overlap: 150
  };
  if (uploadFormRef.value) {
    uploadFormRef.value.resetFields();
  }
};

const handleCreateFolder = (parentId?: number) => {
  folderForm.value = { name: '', parent_id: parentId || null };
  folderDialogVisible.value = true;
};

const submitCreateFolder = async () => {
  if (!folderForm.value.name.trim()) {
    ElMessage.error('请输入文件夹名称');
    return;
  }
  try {
    await createFolder(vectorDbId.value, folderForm.value.name, folderForm.value.parent_id || undefined);
    ElMessage.success('文件夹创建成功');
    folderDialogVisible.value = false;
    await fetchDocumentTree();
  } catch (error: unknown) {
    console.error('创建文件夹失败:', error);
    ElMessage.error(error.response?.data?.message || '创建文件夹失败');
  }
};

const handleRename = (node: Record<string, unknown>) => {
  renameForm.value = { id: node.id, name: node.name };
  renameDialogVisible.value = true;
};

const submitRename = async () => {
  if (!renameForm.value.id || !renameForm.value.name.trim()) {
    ElMessage.error('请输入新名称');
    return;
  }
  try {
    await renameDocument(renameForm.value.id, renameForm.value.name);
    ElMessage.success('重命名成功');
    renameDialogVisible.value = false;
    await fetchDocumentTree();
  } catch (error: unknown) {
    console.error('重命名失败:', error);
    ElMessage.error(error.response?.data?.message || '重命名失败');
  }
};

const handleDeleteDocument = async (documentId: number) => {
  try {
    await ElMessageBox.confirm('确定要删除吗？', '提示', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    });
    await deleteDocument(documentId);
    ElMessage.success('删除成功');
    await fetchDocumentTree();
  } catch (error: unknown) {
    if (error !== 'cancel') {
      console.error('删除失败:', error);
      ElMessage.error(error.response?.data?.message || '删除失败');
    }
  }
};

const getDocumentStatusLabel = (status?: string) => {
  const labels: Record<string, string> = { processing: '处理中', success: '成功', failed: '失败', archived: '已归档' };
  return labels[status || 'success'] || '成功';
};

const getDocumentStatusType = (status?: string): 'primary' | 'success' | 'warning' | 'danger' | 'info' => {
  const types: Record<string, 'primary' | 'success' | 'warning' | 'danger' | 'info'> = { processing: 'warning', success: 'success', failed: 'danger', archived: 'info' };
  return types[status || 'success'] || 'success';
};

const handleArchiveDocument = async (doc: Record<string, unknown>) => {
  try {
    await ElMessageBox.confirm(
      doc.is_folder ? '确定要归档该文件夹及其所有子文档吗？归档后不参与检索。' : '确定要归档该文档吗？归档后不参与检索。',
      '归档确认', { confirmButtonText: '归档', cancelButtonText: '取消', type: 'warning' }
    );
    await archiveDocument(doc.id);
    ElMessage.success('归档成功');
    await fetchDocumentTree();
  } catch (error: unknown) {
    if (error !== 'cancel') {
      console.error('归档失败:', error);
      ElMessage.error(error.response?.data?.message || '归档失败');
    }
  }
};

const handleRestoreDocument = async (doc: Record<string, unknown>) => {
  try {
    await restoreDocument(doc.id);
    ElMessage.success('恢复成功，文档已重新加入检索');
    await fetchDocumentTree();
  } catch (error: unknown) {
    console.error('恢复失败:', error);
    ElMessage.error(error.response?.data?.message || '恢复失败');
  }
};

const formatFileSize = (size: number) => {
  if (!size) return '0 B';
  if (size < 1024) return size + ' B';
  if (size < 1024 * 1024) return (size / 1024).toFixed(2) + ' KB';
  return (size / (1024 * 1024)).toFixed(2) + ' MB';
};

const treeProps = { children: 'children', label: 'name' };

const getAllFolders = (tree: Record<string, unknown>[]): Record<string, unknown>[] => {
  const folders: Record<string, unknown>[] = [];
  const traverse = (nodes: Record<string, unknown>[]) => {
    for (const node of nodes) {
      if (node.is_folder) {
        folders.push({ id: node.id, name: node.name });
        if (node.children?.length) traverse(node.children);
      }
    }
  };
  traverse(tree);
  return folders;
};

const getFlatDocuments = (tree: Record<string, unknown>[]): Record<string, unknown>[] => {
  const documents: Record<string, unknown>[] = [];
  const traverse = (nodes: Record<string, unknown>[], parentPath: string = '') => {
    for (const node of nodes) {
      if (!node.is_folder) {
        documents.push({ ...node, displayPath: parentPath ? `${parentPath} / ${node.name}` : node.name });
      } else if (node.children?.length) {
        traverse(node.children, parentPath ? `${parentPath} / ${node.name}` : node.name);
      }
    }
  };
  traverse(tree);
  return documents;
};

const handleDownloadDocument = async (id: number) => {
  try {
    const response = await DownloadFile(id);
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = url;
    const contentDisposition = response.headers['content-disposition'];
    let fileName = 'document';
    if (contentDisposition) {
      const fileNameMatch = contentDisposition.match(/filename\*?=(?:UTF-8'')?"?([^"]+)"?/i);
      if (fileNameMatch && fileNameMatch[1]) {
        let extractedName = fileNameMatch[1];
        if (extractedName.startsWith("UTF-8''")) extractedName = extractedName.substring(7);
        try { fileName = decodeURIComponent(extractedName); } catch { fileName = extractedName; }
      } else {
        const fallbackMatch = contentDisposition.match(/filename="?([^"]+)"?/i);
        if (fallbackMatch && fallbackMatch[1]) fileName = fallbackMatch[1];
      }
    }
    link.setAttribute('download', fileName);
    document.body.appendChild(link);
    link.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(link);
  } catch (error) {
    console.error('下载文档失败:', error);
    ElMessage.error('下载文档失败');
  }
};

const viewDialogVisible = ref(false);
const currentDocumentContent = ref('');
const currentDocumentTitle = ref('');
const handleViewDocument = (text: string) => {
  currentDocumentContent.value = text;
  currentDocumentTitle.value = '内容详情';
  viewDialogVisible.value = true;
};

const previewLoading = ref(false);
const handlePreviewDocument = async (id: number) => {
  previewLoading.value = true;
  try {
    const data = await previewDocument(id);
    currentDocumentContent.value = data.content;
    currentDocumentTitle.value = data.name + (data.truncated ? '（前 5000 字）' : '');
    viewDialogVisible.value = true;
  } catch (error) {
    ElMessage.error('预览失败');
  } finally {
    previewLoading.value = false;
  }
};

const dialogVisible = ref(false);
const form = ref({
  id: vectorDbId.value,
  name: '',
  describe: '',
  embedding_id: vectorDb.value.embedding_id,
  document_similarity: 0.5,
  organization_id: null as number | null,
});
const formRules = {
  name: [{ required: true, message: '请输入知识库名称', trigger: 'blur' }],
};

const availableOrganizations = computed(() => {
  const userRole = userStore.user?.role || 'student';
  if (userRole === 'student') return [];
  return userStore.userOrganizations.filter(o => !userStore.isVirtualOrganization(o));
});

const initForm = () => {
  form.value = {
    id: vectorDb.value.id,
    name: vectorDb.value.name,
    describe: vectorDb.value.describe,
    embedding_id: vectorDb.value.embedding_id,
    document_similarity: Number(vectorDb.value.document_similarity),
    organization_id: vectorDb.value.organization_id || null,
  };
};

const submitForm = async () => {
  loading.value = true;
  try { await updateVectorDb(vectorDbId.value, form.value); } catch (error) { console.error('保存失败:', error); }
  loading.value = false;
  fetchVectorDbDetail();
  dialogVisible.value = false;
};

const handleEditForm = () => { initForm(); dialogVisible.value = true; };

const handleDeleteVectorDb = async () => {
  try {
    await ElMessageBox.confirm('确定要删除此知识库吗？删除后无法恢复', '警告', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    });
    await deleteVectorDb(vectorDbId.value);
    ElMessage.success('知识库删除成功');
    router.push('/database');
  } catch (error) {}
};

interface QueryResult {
  document_name: string;
  document_id: number;
  score: number;
  text: string;
}
const queryResult = ref<QueryResult[]>([]);
const queryLoading = ref(false);

const handleQuery = async () => {
  if (!queryInput.value.trim()) { ElMessage.warning('请输入检索内容'); return; }
  try {
    queryLoading.value = true;
    const res = await queryVector(vectorDbId.value, queryInput.value, 5);
    if (!res || res.length === 0) { ElMessage.warning('未找到相关结果'); return; }
    queryResult.value = res;
    ElMessage.success(`找到 ${res.length} 条相关结果`);
  } catch (error) {
    console.error('检索失败:', error);
    ElMessage.error('检索失败');
  } finally { queryLoading.value = false; }
};

// 检索测试（合并普通检索 + 调试模式）
const searchInput = ref('');
const searchDebugMode = ref(false);
const debugAlpha = ref(0.7);
const debugUseHybrid = ref(true);
const debugLoading = ref(false);
const debugResult = ref<Record<string, unknown> | null>(null);

const getDebugMethodLabel = (method?: string) => {
  const labels: Record<string, string> = { vector: '语义检索', bm25: '关键词检索', hybrid: '混合检索' };
  return method ? labels[method] || method : '检索';
};

const handleSearch = async () => {
  if (!searchInput.value.trim()) { ElMessage.warning('请输入检索内容'); return; }
  if (searchDebugMode.value) {
    debugLoading.value = true;
    try {
      debugResult.value = await debugQuery(vectorDbId.value, searchInput.value, 10, debugAlpha.value, debugUseHybrid.value);
    } catch (error: unknown) {
      ElMessage.error(error.response?.data?.detail || '检索失败');
    } finally { debugLoading.value = false; }
  } else {
    queryLoading.value = true;
    queryResult.value = [];
    try {
      const res = await queryVector(vectorDbId.value, searchInput.value, 5);
      if (!res || res.length === 0) { ElMessage.warning('未找到相关结果'); return; }
      queryResult.value = res;
    } catch (error) {
      console.error('检索失败:', error);
      ElMessage.error('检索失败');
    } finally { queryLoading.value = false; }
  }
};

const escapeHtml = (s: string) => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

const highlightContent = (content: string, query: string) => {
  if (!query || !content) return escapeHtml(content || '');
  const cleanQ = query.replace(/[\s，。、；：！？""''（）\[\]【】\n\r]/g, '');
  if (!cleanQ) return escapeHtml(content);

  const terms: string[] = [];
  for (let len = cleanQ.length; len >= 2; len--) {
    for (let i = 0; i <= cleanQ.length - len; i++) {
      const sub = cleanQ.slice(i, i + len);
      if (!terms.some(t => t.includes(sub))) terms.push(sub);
    }
  }
  if (!terms.length) return escapeHtml(content);

  const escaped = escapeHtml(content);
  const escapedTerms = terms.map(t => escapeHtml(t).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const pattern = new RegExp(`(${escapedTerms.join('|')})`, 'gi');
  return escaped.replace(pattern, '<span class="highlight">$1</span>');
};

onMounted(async () => {
  fetchVectorDbDetail();
  baseModels.value = await getEmbeddingModelInfos();
});
</script>

<template>
  <div class="page-container" v-loading="loading">
    <!-- 更新知识库对话框 -->
    <ElDialog v-model="dialogVisible" title="更新知识库" width="50%" style="font-size: larger;">
      <ElForm :model="form" :rules="formRules" label-width="120px" ref="formRef" class="dialog-form">
        <ElFormItem label="知识库名称" prop="name">
          <ElInput v-model="form.name" placeholder="请输入知识库名称" />
        </ElFormItem>
        <ElFormItem label="描述" prop="describe">
          <ElInput v-model="form.describe" placeholder="请输入描述" />
        </ElFormItem>
        <ElFormItem label="嵌入模型" prop="embedding_id">
          <ElSelect disabled v-model="form.embedding_id" placeholder="请选择嵌入模型" style="width: 100%">
            <ElOption v-for="model in baseModels" :key="model.id" :label="model.model_name" :value="model.id" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="相似度">
          <ElSlider v-model="form.document_similarity" :min="0" :max="1" :step="0.1" show-input />
        </ElFormItem>
        <ElFormItem label="可见范围">
          <ElSelect v-model="form.organization_id" placeholder="私有（仅自己可见）" clearable style="width: 100%">
            <ElOption :value="null" label="私有（仅自己可见）" />
            <ElOption v-for="org in availableOrganizations" :key="org.id" :label="org.name" :value="org.id" />
          </ElSelect>
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="dialogVisible = false">取消</ElButton>
        <ElButton type="primary" @click="submitForm" :loading="loading">保存</ElButton>
      </template>
    </ElDialog>

    <!-- 文档内容查看对话框 -->
    <el-dialog v-model="viewDialogVisible" :title="currentDocumentTitle || '文档内容'" width="70%" top="5vh">
      <pre class="full-content" style="white-space: pre-wrap; word-break: break-word; max-height: 70vh; overflow-y: auto;">{{ currentDocumentContent }}</pre>
      <template #footer>
        <el-button @click="viewDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 上传文档对话框 -->
    <el-dialog v-model="uploadDialogVisible" title="上传文档" @closed="resetUploadForm">
      <el-form ref="uploadFormRef" :model="uploadForm" :rules="uploadRules" label-width="80px">
        <el-form-item label="文件" prop="files">
          <el-upload class="upload-demo" drag multiple :auto-upload="false" :show-file-list="false" :on-change="handleFileChange" :file-list="uploadForm.files.map(file => ({ name: file.name }))">
            <el-icon class="el-icon--upload"><upload /></el-icon>
            <div class="el-upload__text">拖拽文件到此处或<em>点击选择文件</em></div>
            <template #tip>
              <div class="el-upload__tip">
                <div>支持PDF、Word、TXT等文档格式，大小不超过50MB</div>
                <div class="upload-tip-line">支持上传压缩包（ZIP、TAR、TAR.GZ），系统将自动解压并按目录结构组织文件</div>
                <div class="upload-tip-line success">支持图片格式（JPG、PNG、GIF、BMP、WEBP等），系统将自动进行OCR文字识别</div>
              </div>
            </template>
          </el-upload>
          <div v-if="uploadForm.files.length > 0" class="files-list">
            <div v-for="(file, index) in uploadForm.files" :key="index" class="file-item">
              <el-icon><document /></el-icon>
              {{ file.name }} ({{ (file.size / 1024 / 1024).toFixed(2) }} MB)
            </div>
          </div>
        </el-form-item>
        <el-form-item label="描述" prop="describe">
          <el-input v-model="uploadForm.describe" type="textarea" :rows="3" placeholder="请输入文档描述" />
        </el-form-item>
        <el-form-item>
          <template #label>
            <span>上传到</span>
            <el-tooltip content="选择文档存放的文件夹，仅用于组织管理，不影响检索结果。" placement="top">
              <el-icon class="help-icon"><QuestionFilled /></el-icon>
            </el-tooltip>
          </template>
          <el-select v-model="uploadForm.parent_id" placeholder="根目录" clearable style="width: 100%">
            <el-option label="根目录" :value="null" />
            <template v-for="item in getAllFolders(documentTree)" :key="item.id">
              <el-option :label="item.name" :value="item.id" />
            </template>
          </el-select>
        </el-form-item>
        <div class="chunk-settings">
          <div class="chunk-settings-title">
            切块策略
            <el-tooltip content="决定文档如何被分割为小段落用于检索。不同策略适合不同类型的文档。" placement="top">
              <el-icon class="help-icon"><QuestionFilled /></el-icon>
            </el-tooltip>
          </div>
          <el-form-item>
            <template #label>
              <span>策略</span>
              <el-tooltip placement="top">
                <template #content>
                  <div style="max-width:280px">
                    <b>固定长度</b>：按字数均匀切分，适合通用资料<br/>
                    <b>句子边界</b>：在句号等标点处切分，保持语义完整，适合通知公告<br/>
                    <b>Markdown标题</b>：按 # 标题拆分，适合有目录结构的文档
                  </div>
                </template>
                <el-icon class="help-icon"><QuestionFilled /></el-icon>
              </el-tooltip>
            </template>
            <el-segmented v-model="uploadForm.chunk_strategy" :options="chunkStrategyOptions" class="chunk-segmented" />
          </el-form-item>
          <div class="chunk-grid">
            <el-form-item>
              <template #label>
                <span>块大小</span>
                <el-tooltip content="每个切块的最大字符数。较大的块包含更多上下文但检索精度降低，较小的块精度高但可能丢失上下文。建议 300~800。" placement="top">
                  <el-icon class="help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </template>
              <el-input-number v-model="uploadForm.chunk_size" :min="100" :max="4000" :step="100" controls-position="right" style="width: 100%" />
            </el-form-item>
            <el-form-item>
              <template #label>
                <span>重叠</span>
                <el-tooltip content="相邻切块之间重复的字符数。重叠可以避免关键信息被切断，建议设为块大小的 10%~20%。" placement="top">
                  <el-icon class="help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </template>
              <el-input-number v-model="uploadForm.chunk_overlap" :min="0" :max="Math.max(uploadForm.chunk_size - 1, 0)" :step="10" controls-position="right" style="width: 100%" />
            </el-form-item>
          </div>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="uploadDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploadLoading" @click="submitUpload">上传</el-button>
      </template>
    </el-dialog>

    <!-- 创建文件夹对话框 -->
    <el-dialog v-model="folderDialogVisible" title="创建文件夹" width="400px">
      <el-form :model="folderForm" label-width="80px">
        <el-form-item label="文件夹名">
          <el-input v-model="folderForm.name" placeholder="请输入文件夹名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="folderDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCreateFolder">确定</el-button>
      </template>
    </el-dialog>

    <!-- 重命名对话框 -->
    <el-dialog v-model="renameDialogVisible" title="重命名" width="400px">
      <el-form :model="renameForm" label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="renameForm.name" placeholder="请输入新名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="renameDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRename">确定</el-button>
      </template>
    </el-dialog>

    <div class="content-section">
      <el-button @click="goBack" :icon="Back" text class="back-btn">返回知识库</el-button>

      <!-- 头部卡片 -->
      <div class="detail-header">
        <div class="detail-header-left">
          <div class="detail-icon-wrap">
            <el-icon :size="22"><Connection /></el-icon>
          </div>
          <div class="detail-header-text">
            <div class="detail-name-row">
              <h2 class="detail-name">{{ vectorDb.name }}</h2>
              <el-tag :type="visibilityType" effect="plain" size="small">{{ orgDisplayName }}</el-tag>
              <el-tag type="success" effect="plain" size="small">运行中</el-tag>
            </div>
            <p class="detail-desc" v-if="vectorDb.describe">{{ vectorDb.describe }}</p>
          </div>
        </div>
        <div class="detail-header-actions" v-if="canManage">
          <el-button size="small" :icon="Edit" @click="handleEditForm">编辑</el-button>
          <el-button size="small" type="danger" plain :icon="Delete" @click="handleDeleteVectorDb">删除</el-button>
        </div>
      </div>

      <!-- 三卡片概览 -->
      <div class="tile-row-3">
        <!-- 配置信息 -->
        <div class="overview-card">
          <div class="overview-card-header">
            <span class="overview-accent" style="background:#10b981"></span>
            <h3 class="overview-title">配置信息</h3>
          </div>
          <div class="kv-list">
            <div class="kv-row"><span class="kv-label">嵌入模型</span><span class="kv-value">{{ embeddingModelName }}</span></div>
            <div class="kv-row"><span class="kv-label">相似度阈值</span><span class="kv-value">{{ vectorDb.document_similarity }}</span></div>
            <div class="kv-row"><span class="kv-label">归属组织</span><span class="kv-value">{{ orgDisplayName }}</span></div>
          </div>
        </div>

        <!-- 数据概览 -->
        <div class="overview-card">
          <div class="overview-card-header">
            <span class="overview-accent" style="background:#6366f1"></span>
            <h3 class="overview-title">数据概览</h3>
          </div>
          <div class="stat-grid">
            <div class="stat-item"><span class="stat-num">{{ totalDocCount }}</span><span class="stat-label">篇文档</span></div>
            <div class="stat-item"><span class="stat-num">{{ folderCount }}</span><span class="stat-label">个文件夹</span></div>
            <div class="stat-item stat-wide"><span class="stat-num">{{ formatFileSize(totalSize) }}</span><span class="stat-label">总大小</span></div>
          </div>
          <div class="kv-list" style="margin-top:8px">
            <div class="kv-row"><span class="kv-label">创建时间</span><span class="kv-value">{{ vectorDb.created_at }}</span></div>
            <div class="kv-row"><span class="kv-label">最近更新</span><span class="kv-value">{{ vectorDb.updated_at }}</span></div>
          </div>
        </div>

        <!-- 快速操作 -->
        <div class="overview-card">
          <div class="overview-card-header">
            <span class="overview-accent" style="background:#8b5cf6"></span>
            <h3 class="overview-title">快速操作</h3>
          </div>
          <div class="quick-actions">
            <div v-if="canManage" class="qa-item" @click="uploadDialogVisible = true">
              <span class="qa-dot" style="background:#6366f1"></span>
              <div class="qa-text"><span class="qa-label">上传文档</span><span class="qa-desc">添加新的文档资料</span></div>
              <el-icon :size="13" class="qa-arrow"><ArrowRight /></el-icon>
            </div>
            <div v-if="canManage" class="qa-item" @click="handleCreateFolder()">
              <span class="qa-dot" style="background:#10b981"></span>
              <div class="qa-text"><span class="qa-label">新建文件夹</span><span class="qa-desc">组织文档结构</span></div>
              <el-icon :size="13" class="qa-arrow"><ArrowRight /></el-icon>
            </div>
          </div>
        </div>
      </div>

      <!-- 标签页 -->
      <el-tabs v-model="activeTab" class="detail-tabs">
        <!-- 文档管理 -->
        <el-tab-pane label="文档管理" name="docs">
          <div class="tab-content">
            <div class="action-bar">
              <div class="action-buttons" v-if="canManage">
                <el-button type="primary" plain :icon="Upload" @click="uploadDialogVisible = true">上传文档</el-button>
                <el-button type="success" plain :icon="Plus" @click="handleCreateFolder()">新建文件夹</el-button>
              </div>
              <div class="view-toggle">
                <el-radio-group v-model="viewMode" size="small">
                  <el-radio-button label="list">列表视图</el-radio-button>
                  <el-radio-button label="tree">树形视图</el-radio-button>
                </el-radio-group>
              </div>
            </div>

            <!-- 列表视图 -->
            <div v-if="viewMode === 'list'" class="document-list-container">
              <div v-if="getFlatDocuments(documentTree).length === 0" class="empty-documents">
                <el-empty description="暂无文档，请上传文档" />
              </div>
              <div v-else class="document-list">
                <div v-for="doc in getFlatDocuments(documentTree)" :key="doc.id" class="document-item" :class="{ 'selected': selectedDocument === doc.id }" @click="selectedDocument = doc.id">
                  <div class="document-icon"><el-icon class="icon"><Document /></el-icon></div>
                  <div class="document-info">
                    <div class="document-name">{{ doc.name }}</div>
                    <div class="document-meta">
                      <el-tag size="small" effect="plain" class="type-tag">{{ doc.type?.toUpperCase() || 'TXT' }}</el-tag>
                      <el-tag size="small" effect="plain" :type="getDocumentStatusType(doc.status)">{{ getDocumentStatusLabel(doc.status) }}</el-tag>
                      <span class="file-size">{{ formatFileSize(doc.size) }}</span>
                    </div>
                  </div>
                  <div class="document-actions" @click.stop>
                    <el-button v-if="canManage" link type="primary" size="small" :icon="Edit" @click="handleRename(doc)">重命名</el-button>
                    <el-button link type="primary" size="small" @click="handlePreviewDocument(doc.id)" :loading="previewLoading">预览</el-button>
                    <el-button link type="primary" size="small" @click="handleDownloadDocument(doc.id)">下载</el-button>
                    <el-button v-if="canManage && doc.status !== 'archived'" link type="warning" size="small" @click="handleArchiveDocument(doc)">归档</el-button>
                    <el-button v-if="canManage && doc.status === 'archived'" link type="success" size="small" @click="handleRestoreDocument(doc)">恢复</el-button>
                    <el-button v-if="canManage" link type="danger" size="small" :icon="Delete" @click="handleDeleteDocument(doc.id)">删除</el-button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 树形视图 -->
            <div v-else class="document-tree-container">
              <el-tree :data="documentTree" :props="treeProps" default-expand-all :expand-on-click-node="false" node-key="id">
                <template #default="{ node, data }">
                  <div class="tree-node">
                    <el-icon class="node-icon">
                      <FolderOpened v-if="data.is_folder && node.expanded" />
                      <Folder v-else-if="data.is_folder" />
                      <Document v-else />
                    </el-icon>
                    <span class="node-label">{{ data.name }}</span>
                    <span v-if="!data.is_folder" class="node-meta">
                      <el-tag size="small" effect="plain">{{ data.type?.toUpperCase() || 'FILE' }}</el-tag>
                      <el-tag size="small" effect="plain" :type="getDocumentStatusType(data.status)">{{ getDocumentStatusLabel(data.status) }}</el-tag>
                      <span class="file-size">{{ formatFileSize(data.size) }}</span>
                    </span>
                    <span v-else class="node-meta"></span>
                    <div class="node-actions">
                      <el-button v-if="canManage && data.is_folder" link type="primary" size="small" :icon="Plus" @click.stop="handleCreateFolder(data.id)">新建</el-button>
                      <el-button v-if="canManage" link type="primary" size="small" :icon="Edit" @click.stop="handleRename(data)">重命名</el-button>
                      <el-button v-if="!data.is_folder" link type="primary" size="small" @click.stop="handlePreviewDocument(data.id)" :loading="previewLoading">预览</el-button>
                      <el-button v-if="!data.is_folder" link type="primary" size="small" @click.stop="handleDownloadDocument(data.id)">下载</el-button>
                      <el-button v-if="canManage && !data.is_folder && data.status !== 'archived'" link type="warning" size="small" @click.stop="handleArchiveDocument(data)">归档</el-button>
                      <el-button v-if="canManage && !data.is_folder && data.status === 'archived'" link type="success" size="small" @click.stop="handleRestoreDocument(data)">恢复</el-button>
                      <el-button v-if="canManage" link type="danger" size="small" :icon="Delete" @click.stop="handleDeleteDocument(data.id)">删除</el-button>
                    </div>
                  </div>
                </template>
              </el-tree>
            </div>
          </div>
        </el-tab-pane>

        <!-- 检索测试（合并普通 + 调试） -->
        <el-tab-pane label="检索测试" name="search">
          <div class="tab-content">
            <div class="search-toolbar">
              <el-input
                v-model="searchInput"
                :placeholder="searchDebugMode ? '输入查询词，查看向量分 / BM25 分 / 融合分' : '请输入检索内容'"
                clearable
                style="flex:1"
                @keyup.enter="handleSearch"
              >
                <template #append>
                  <el-button :icon="Search" :loading="queryLoading || debugLoading" @click="handleSearch">检索</el-button>
                </template>
              </el-input>
              <div class="search-mode-toggle">
                <el-switch v-model="searchDebugMode" active-text="调试模式" inactive-text="" />
              </div>
            </div>

            <!-- 调试模式参数 -->
            <div v-if="searchDebugMode" class="debug-params">
              <el-tooltip content="混合检索（向量 + BM25）">
                <el-switch v-model="debugUseHybrid" active-text="混合" inactive-text="纯向量" />
              </el-tooltip>
              <el-tooltip content="向量权重 α（BM25 权重 = 1 - α）">
                <div class="alpha-control">
                  <span class="alpha-label">α={{ debugAlpha.toFixed(1) }}</span>
                  <el-slider v-model="debugAlpha" :min="0" :max="1" :step="0.1" style="width:120px" :disabled="!debugUseHybrid" />
                </div>
              </el-tooltip>
            </div>

            <!-- 调试模式结果 -->
            <template v-if="searchDebugMode">
              <div v-if="debugResult" class="debug-meta">
                <span>总耗时 <b>{{ debugResult.total_time_ms?.toFixed(1) }}ms</b></span>
                <span>向量检索 <b>{{ debugResult.vector_search_time_ms?.toFixed(1) }}ms</b></span>
                <span v-if="debugUseHybrid">BM25 <b>{{ debugResult.bm25_search_time_ms?.toFixed(1) }}ms</b></span>
                <span>共 <b>{{ debugResult.results?.length }}</b> 条结果</span>
              </div>
              <div v-if="debugResult?.results?.length" class="debug-results">
                <div v-for="r in debugResult.results" :key="r.rank" class="debug-result-item">
                  <div class="debug-result-header">
                    <span class="debug-rank">#{{ r.rank }}</span>
                    <span class="debug-source">{{ r.source }}</span>
                    <span class="debug-method" :class="'dbg-method-' + r.retrieval_method">{{ getDebugMethodLabel(r.retrieval_method) }}</span>
                    <div class="debug-scores">
                      <span class="score-badge score-vector">向量 {{ (r.vector_score * 100).toFixed(1) }}%</span>
                      <span class="score-badge score-bm25">BM25 {{ (r.bm25_score * 100).toFixed(1) }}%</span>
                      <span class="score-badge score-final">融合 {{ (r.final_score * 100).toFixed(1) }}%</span>
                    </div>
                  </div>
                  <div class="debug-result-content" v-html="highlightContent(r.content, searchInput)"></div>
                  <div v-if="r.highlighted_terms?.length" class="debug-terms">
                    命中关键词：
                    <el-tag v-for="t in r.highlighted_terms" :key="t" size="small" type="warning" style="margin:0 2px">{{ t }}</el-tag>
                  </div>
                </div>
              </div>
              <div v-else-if="debugLoading" class="empty-results"><el-empty description="正在检索..." /></div>
              <div v-else class="empty-results"><el-empty description="输入查询词，点击检索查看详细分数" /></div>
            </template>

            <!-- 普通模式结果 -->
            <template v-else>
              <div v-if="queryResult.length > 0" class="query-results">
                <h4>检索结果（Top {{ queryResult.length }}）</h4>
                <div v-for="(result, index) in queryResult" :key="index" class="result-item">
                  <div class="result-header">
                    <div>
                      <span class="result-doc-name">{{ result.document_name }}</span>
                      <el-tag type="success" size="small">相似度: {{ (result.score * 100).toFixed(2) }}%</el-tag>
                    </div>
                    <el-button type="primary" size="small" @click="handleViewDocument(result.text)">查看全部</el-button>
                  </div>
                  <div class="result-content" v-html="highlightContent(result.text, searchInput)"></div>
                </div>
              </div>
              <div v-else-if="queryLoading" class="empty-results"><el-empty description="正在查询..." /></div>
              <div v-else class="empty-results"><el-empty description="输入关键词，测试知识库检索效果" /></div>
            </template>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<style scoped>
.back-btn { color: #64748b; margin-bottom: 12px; }
.back-btn:hover { color: #4f46e5; }

/* ===== 头部卡片 ===== */
.detail-header {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  background: #fff; border: 1px solid #e6ebf2; border-radius: 10px; padding: 18px 20px; margin-bottom: 14px;
}
.detail-header-left { display: flex; align-items: center; gap: 14px; min-width: 0; flex: 1; }
.detail-icon-wrap {
  width: 44px; height: 44px; flex: 0 0 44px; background: #ecfdf5; color: #059669;
  border-radius: 10px; display: flex; align-items: center; justify-content: center;
}
.detail-header-text { min-width: 0; flex: 1; }
.detail-name-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.detail-name { margin: 0; font-size: 18px; font-weight: 600; color: #1e293b; }
.detail-desc { margin: 4px 0 0; font-size: 13px; color: #64748b; line-height: 1.5; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.detail-header-actions { display: flex; gap: 6px; flex-shrink: 0; }

/* ===== 三卡片网格 ===== */
.tile-row-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 14px; }
.overview-card { background: #fff; border: 1px solid #e6ebf2; border-radius: 10px; padding: 16px 18px; }
.overview-card-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.overview-accent { display: inline-block; width: 3px; height: 14px; border-radius: 2px; flex-shrink: 0; }
.overview-title { margin: 0; font-size: 13.5px; font-weight: 600; color: #1e293b; }

.kv-list { display: flex; flex-direction: column; gap: 0; }
.kv-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; border-bottom: 1px dashed #edf0f5; }
.kv-row:last-child { border-bottom: none; }
.kv-label { font-size: 12.5px; color: #94a3b8; }
.kv-value { font-size: 13px; color: #1e293b; font-weight: 500; }

.stat-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.stat-item { display: flex; flex-direction: column; align-items: center; padding: 10px 0; background: #f8fafc; border-radius: 8px; }
.stat-item.stat-wide { grid-column: 1 / -1; }
.stat-num { font-size: 20px; font-weight: 700; color: #1e293b; line-height: 1; }
.stat-label { font-size: 11.5px; color: #94a3b8; margin-top: 4px; }

.quick-actions { display: flex; flex-direction: column; gap: 6px; }
.qa-item { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border: 1px solid #edf0f5; border-radius: 8px; cursor: pointer; transition: all 0.2s; }
.qa-item:hover { border-color: #c7d2fe; transform: translateX(3px); box-shadow: 0 2px 8px rgba(99,102,241,0.05); }
.qa-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.qa-text { display: flex; flex-direction: column; gap: 1px; flex: 1; min-width: 0; }
.qa-label { font-size: 13px; font-weight: 600; color: #1e293b; }
.qa-desc { font-size: 11.5px; color: #94a3b8; }
.qa-arrow { color: #cbd5e1; flex-shrink: 0; transition: color 0.15s; }
.qa-item:hover .qa-arrow { color: #6366f1; }

/* ===== 标签页 ===== */
.detail-tabs { margin-top: 0; }
:deep(.el-tabs__header) { margin-bottom: 0; }
:deep(.el-tabs__item) { font-size: 14px; padding: 0 20px; }
:deep(.el-tabs__item.is-active) { font-weight: 600; }
:deep(.el-tabs__content) { background: #fff; border: 1px solid #e4e7ed; border-top: none; border-radius: 0 0 10px 10px; }

.tab-content { padding: 18px; }

.action-bar {
  display: flex; justify-content: space-between; align-items: center; gap: 12px;
  margin-bottom: 16px; flex-wrap: wrap;
}
.action-buttons { display: flex; gap: 8px; flex-wrap: wrap; }
.view-toggle { display: flex; align-items: center; }

/* ===== 文档列表 ===== */
.document-tree-container { border: 1px solid #e4e7ed; border-radius: 8px; padding: 1rem; background: #fff; }
.document-list-container { border: 1px solid #e4e7ed; border-radius: 8px; padding: 1rem; background: #fff; min-height: 400px; }
.empty-documents { display: flex; justify-content: center; align-items: center; min-height: 400px; }
.document-list { display: flex; flex-direction: column; gap: 0.5rem; }
.document-item { display: flex; align-items: center; gap: 1rem; padding: 1rem; border: 1px solid #e4e7ed; border-radius: 8px; background: #fff; cursor: pointer; transition: all 0.3s ease; }
.document-item:hover { background: #f5f7fa; border-color: #409eff; box-shadow: 0 2px 8px rgba(64, 158, 255, 0.1); }
.document-item.selected { background: #ecf5ff; border-color: #409eff; box-shadow: 0 2px 12px rgba(64, 158, 255, 0.2); }
.document-icon { display: flex; align-items: center; justify-content: center; width: 48px; height: 48px; background: #f0f2f5; border-radius: 8px; flex-shrink: 0; }
.document-icon .icon { font-size: 24px; color: #409eff; }
.document-info { flex: 1; display: flex; flex-direction: column; gap: 0.5rem; min-width: 0; }
.document-name { font-size: 0.95rem; font-weight: 500; color: #303133; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.document-meta { display: flex; align-items: center; gap: 0.75rem; }
.type-tag { font-size: 0.75rem; padding: 2px 8px; border-radius: 4px; }
.file-size { font-size: 0.85rem; color: #909399; }
.document-actions { display: flex; gap: 0.5rem; opacity: 0; transition: opacity 0.3s ease; flex-shrink: 0; }
.document-item:hover .document-actions { opacity: 1; }

.tree-node { display: flex; align-items: center; gap: 0.5rem; flex: 1; padding: 4px 0; }
.node-icon { font-size: 1.2rem; color: #409eff; }
.node-label { flex: 1; font-size: 0.95rem; color: #303133; }
.node-meta { display: flex; align-items: center; gap: 0.5rem; margin-left: auto; margin-right: 1rem; }
.node-actions { display: flex; gap: 0.25rem; opacity: 0; transition: opacity 0.2s; }
.tree-node:hover .node-actions { opacity: 1; }

/* ===== 检索测试 ===== */
.search-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.search-mode-toggle { flex-shrink: 0; }
.debug-params {
  display: flex; align-items: center; gap: 20px; margin-bottom: 14px;
  padding: 10px 14px; background: #f8fafc; border: 1px solid #e6ebf2; border-radius: 8px;
}
.alpha-control { display: flex; align-items: center; gap: 8px; font-size: 0.85rem; color: #606266; }
.alpha-label { white-space: nowrap; }

.debug-meta { display: flex; gap: 16px; font-size: 0.82rem; color: #909399; margin-bottom: 12px; padding: 6px 12px; background: #f5f7fa; border-radius: 6px; }
.debug-results { display: flex; flex-direction: column; gap: 10px; }
.debug-result-item { border: 1px solid #e4e7ed; border-radius: 8px; padding: 12px; background: white; }
.debug-result-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.debug-rank { font-weight: 700; color: #3a6eff; min-width: 28px; }
.debug-source { color: #5b6b8a; font-size: 0.85rem; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.debug-method { font-size: 0.75rem; padding: 2px 8px; border-radius: 6px; }
.dbg-method-vector { background: #e6f0ff; color: #3a6eff; }
.dbg-method-bm25 { background: #e6ffe6; color: #389e0d; }
.dbg-method-hybrid { background: #fff7e6; color: #d46b08; }
.debug-scores { display: flex; gap: 6px; margin-left: auto; }
.score-badge { font-size: 0.75rem; padding: 2px 8px; border-radius: 10px; }
.score-vector { background: #e6f0ff; color: #3a6eff; }
.score-bm25 { background: #e6ffe6; color: #389e0d; }
.score-final { background: #f9f0ff; color: #722ed1; font-weight: 600; }
.debug-result-content { font-size: 0.88rem; color: #4a5568; line-height: 1.6; display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; margin-bottom: 6px; white-space: pre-wrap; word-break: break-word; }
.debug-result-content :deep(.highlight) { background-color: #ff0; font-weight: bold; padding: 0 2px; color: #000; }
.debug-terms { font-size: 0.8rem; color: #909399; }

.query-results { margin-top: 16px; }
.query-results h4 { margin: 0 0 12px; font-size: 14px; color: #1e293b; font-weight: 600; }
.result-item { border: 1px solid #ebeef5; border-radius: 8px; padding: 14px; margin-bottom: 12px; background: #fafafa; transition: all 0.3s; }
.result-item:hover { box-shadow: 0 2px 12px rgba(0,0,0,0.08); transform: translateY(-1px); }
.result-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px dashed #dcdfe6; }
.result-doc-name { font-weight: 600; margin-right: 10px; color: #1e293b; }
.result-content { line-height: 1.6; color: #606266; max-height: 120px; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; text-align: left; }
.empty-results { margin-top: 40px; text-align: center; }

.highlight { background-color: #ff0; font-weight: bold; padding: 0 2px; }
.result-content :deep(.highlight) { background-color: #ff0; font-weight: bold; padding: 0 2px; color: #000; }
.full-content { max-height: 60vh; overflow-y: auto; padding: 15px; border: 1px solid #ebeef5; border-radius: 4px; background-color: #fafafa; line-height: 1.8; text-align: left; }
.full-content :deep(.highlight) { background-color: #ff0; font-weight: bold; padding: 0 2px; color: #000; }

/* ===== 上传对话框 ===== */
.upload-demo { width: 100%; }
.upload-tip-line { margin-top: 8px; color: #2563eb; }
.upload-tip-line.success { color: #16803c; }
.chunk-settings { border: 1px solid #e6ebf2; border-radius: 8px; padding: 14px 14px 4px; background: #f8fafc; margin-top: 6px; }
.chunk-settings-title { font-size: 0.88rem; font-weight: 600; color: #1f2d3d; margin-bottom: 12px; }
.chunk-segmented { width: 100%; }
.chunk-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.chunk-help { margin: 0 0 12px 80px; font-size: 0.82rem; color: #64748b; line-height: 1.5; }

@media (max-width: 1024px) { .tile-row-3 { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 768px) {
  .tile-row-3 { grid-template-columns: 1fr; }
  .detail-header { flex-direction: column; align-items: flex-start; }
  .detail-header-actions { width: 100%; justify-content: flex-end; }
  .search-toolbar { flex-direction: column; }
}
@media (max-width: 720px) { .chunk-grid { grid-template-columns: 1fr; } .chunk-help { margin-left: 0; } }

/* ===== 帮助图标 ===== */
.help-icon {
  margin-left: 4px;
  font-size: 14px;
  color: #a0aec0;
  cursor: help;
  vertical-align: middle;
}
.help-icon:hover { color: #6366f1; }
</style>
