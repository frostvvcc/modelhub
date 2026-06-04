<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElNotification } from 'element-plus'
import { getUserInfo, uploadAvatar } from '../api/user'
import { getModelInfos } from '../api/model'
import { ModelConfig, ModelInfo } from '../types/model_config';
import { document } from '../types/document'
import { useRouter } from 'vue-router';
import { useUserStore } from '../stores/user';
// 定义类型
interface UserInfo {
  id: number
  name: string
  email: string
  type: string
  avatar: string
  describe: string | null
  create_at: string
  update_at: string
}
interface VectorDb {
  id: number
  name: string
  describe: string
  embedding_id: number
  document_similarity: number
  created_at: string
  updated_at: string
  model_configs: ModelConfig[]
  documents: document[]
}
// 响应式数据
const userInfo = ref<UserInfo | null>(null)
const userStore = useUserStore()
const modelConfigs = ref<ModelConfig[]>([])
const vectorDBs = ref<VectorDb[]>([])
const modelInfos = ref<ModelInfo[]>([])
const activeTab = ref('connections')

// 计算属性
const baseModelMap = computed(() => {
  const map = new Map<number, string>()
  modelInfos.value.forEach(model => {
    map.set(model.id, model.model_name)
  })
  return map
})
// 修改计算属性定义
const modelConfigs_base = computed(() => (base_model_id: number) => {
  return modelConfigs.value.filter(config => 
    config.base_model_id === base_model_id
  );
});
// 获取知识库名称
const getVectorDBName = (id: number | null) => {
  if (id === null) return '无'
  const vdb = vectorDBs.value.find(db => db.id === id)
  return vdb ? vdb.name : '未知'
}

// 获取知识库提示
const getVectorDBTips = (id: number | null) => {
  if (id === null) return '未关联知识库'
  const vdb = vectorDBs.value.find(db => db.id === id)
  return vdb ? '点击查看知识库详情' : '未知知识库'
}

const router = useRouter();
const toVectorDB = (id: number | null) => { 
  if (id === null) return
  router.push(`/database/${id}`);
}
const handleViewConfig = (config: ModelConfig) => { 
  router.push({
    name: 'configDetail',
    params: { id: config.id },
    state: { 
      config: JSON.parse(JSON.stringify(config)) 
    } // Pass the config data via state
  });
}
const navigateToDetail = (id: number) => {
  router.push(`/database/${id}`);
};

// 格式化日期
const formatDate = (dateStr: string) => {
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}
const avatarInput = ref<HTMLInputElement | null>(null);

// 处理头像上传
const handleAvatarUpload = async (event: Event) => {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;

  try {
    // 假设有一个上传头像的 API 函数 uploadAvatar
    const formData = new FormData();
    formData.append('file', file);

    const response = await uploadAvatar(formData); // 替换为你的 API 调用

    // 更新用户头像地址
    userInfo.value!.avatar = response.avatarUrl;

    ElNotification({
      title: '成功',
      message: '头像上传成功',
      type: 'success'
    });
  } catch (error) {
    console.error('头像上传失败：', error)
    if (userInfo.value) {
      userInfo.value.avatar = userStore.user?.avatar ?? userInfo.value.avatar;
    }
    ElNotification({
      title: '错误',
      message: '头像上传失败，请重试',
      type: 'error'
    });
  }
};
// 更换头像按钮点击
const changeAvatar = () => {
  if (avatarInput.value) {
    avatarInput.value.click();
  }
};
onMounted(async () => {
  try {
    // 获取用户信息
    const res = await getUserInfo()
    console.log(res)
    userInfo.value = res.user_info
    modelConfigs.value = res.model_configs
    vectorDBs.value = res.vector_dbs
    
    // 只获取配置中使用的基础模型信息
    const baseModelIds = new Set<number>()
    res.model_configs.forEach((config: ModelConfig) => {
      if (config.base_model_id) {
        baseModelIds.add(config.base_model_id)
      }
    })

    if (baseModelIds.size > 0) {
      // 获取模型信息 - 只获取配置中使用的模型
      const modelRes = await getModelInfos()
      modelInfos.value = modelRes.filter((model: ModelInfo) => baseModelIds.has(model.id))
    } else {
      modelInfos.value = []
    }
    
    console.log('数据加载完成')
    
  } catch (error: unknown) {
    ElNotification({
      title: '错误',
      message: error.message || '获取数据失败',
      type: 'error',
      duration: 5000
    })
  }
})
// 新增方法：格式化文件大小
const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
};

;
</script>

<template>
  <div class="page-container">
    <div class="content-section">
      <!-- 用户信息区域 -->
      <div class="user-info-section">
        <div class="user-card">
          <div class="avatar-container">
            <!-- <div class="avatar-placeholder">
              <span>{{ userInfo?.name?.charAt(0) || 'U' }}</span>
            </div> -->
            <img :src="userInfo?.avatar" class="avatar-placeholder" :alt="userInfo?.name?.charAt(0) || 'U'"></img>
            <!-- 添加文件上传控件 -->
             <button class="change-avatar-btn" @click="changeAvatar">更换头像</button>
              <input type="file" accept="image/*" @change="handleAvatarUpload" hidden ref="avatarInput" />
          </div>
          <div class="user-details">
            <h2>{{ userInfo?.name || '未命名用户' }}</h2>
            <p class="email">{{ userInfo?.email || '未设置邮箱' }}</p>
            <div class="user-meta">
              <span class="badge">{{ {admin:'管理员',teacher:'教师',student:'学生'}[userInfo?.role] || userInfo?.role || '未设置角色' }}</span>
              <span class="join-date">加入时间: {{ userInfo?.create_at ? formatDate(userInfo.create_at) : '未知' }}</span>
            </div>
            <p class="description">{{ userInfo?.describe?userInfo?.describe:'该用户暂无描述信息' }}</p>
          </div>
        </div>
      </div>
      
      <!-- 标签页区域 -->
      <div class="tabs-container">
        <div class="tabs">
          <button 
            :class="['tab', { 'active': activeTab === 'models' }]"
            @click="activeTab = 'models'"
          >
            <el-icon><cpu /></el-icon> 模型配置
            <span class="count-badge">{{ modelConfigs.length }}</span>
          </button>
          <button 
            :class="['tab', { 'active': activeTab === 'vector' }]"
            @click="activeTab = 'vector'"
          >
            <el-icon><data-analysis /></el-icon> 知识库
            <span class="count-badge">{{ vectorDBs.length }}</span>
          </button>
          <button 
            :class="['tab', { 'active': activeTab === 'connections' }]"
            @click="activeTab = 'connections'"
          >
            <el-icon><Connection /></el-icon> 配置关系图
          </button>
        </div>
        
        <!-- 模型配置区域 -->
        <div class="tab-content" v-if="activeTab === 'models'">
          <div class="models-grid">
            <div 
              v-for="config in modelConfigs" 
              :key="config.id"
              class="model-card"
              :class="{ 'private': config.is_private }"
            >
              <div class="model-header">
                <h3>{{ config.name }}</h3>
                <span class="privacy-tag" v-if="config.is_private">私有</span>
                <span class="privacy-tag public" v-else>公开</span>
              </div>
              <div class="model-desc"> 
                <p>{{ config.describe || '暂无描述' }}</p>
              </div>
              
              <div class="model-meta">
                <div class="meta-item">
                  <span class="label">基础模型:</span>
                  <span class="value">
                    {{ baseModelMap.get(config.base_model_id) || '未知模型' }}
                  </span>
                </div>
                <div class="meta-item">
                  <span class="label">温度:</span>
                  <span class="value">{{ config.temperature }}</span>
                </div>
                <div class="meta-item">
                  <span class="label">Top P:</span>
                  <span class="value">{{ config.top_p }}</span>
                </div>
              </div>
              
              <div class="model-footer">
                <span class="update-date">更新: {{ formatDate(config.updated_at) }}</span>
                <button class="action-button" @click="handleViewConfig(config)" >查看详情</button>
              </div>
            </div>
          </div>
        </div>
        
        <!-- 知识库区域 -->
        <div class="tab-content" v-if="activeTab === 'vector'">
          <div class="vector-db-container">
            <div 
              v-for="db in vectorDBs" 
              :key="db.id"
              class="vector-card"
            >
              <div class="vector-header">
                <el-icon><database /></el-icon>
                <h3>{{ db.name }}</h3>
              </div>
              <div class="vector-body">
                <div class="vector-desc"> 
                  <p>{{ db.describe || '暂无描述' }}</p>
                </div>
                <div class="db-meta">
                  <span>创建: {{ formatDate(db.created_at) }}</span>
                  <span>更新: {{ formatDate(db.updated_at) }}</span>
                </div>
              </div>
              <div class="vector-footer">
                <span class="used-by">
                  <el-icon><connection /></el-icon>
                  知识库
                </span>
                <button class="action-button" @click="navigateToDetail(db.id)">管理</button>
              </div>
            </div>
          </div>
        </div>
        
        <!-- 关系图区域 -->
        <div class="tab-content" v-if="activeTab === 'connections'">
          <div class="connections-header">
            <h3>配置关系图</h3>
            <div class="legend">
              <div class="legend-item">
                <span class="legend-color user"></span>
                <span>用户</span>
              </div>
              <div class="legend-item">
                <span class="legend-color model"></span>
                <span>模型配置</span>
              </div>
              <div class="legend-item">
                <span class="legend-color vector"></span>
                <span>知识库</span>
              </div>
              <div class="legend-item">
                <span class="legend-color document"></span>
                <span>文档</span>
              </div>
              <div class="legend-item">
                <span class="legend-color base-model"></span>
                <span>基础模型</span>
              </div>
            </div>
          </div>
          <div class="connections-container">
            <div class="grid-layout">

              
              <!-- 基础模型节点 -->
              <div class="grid-row model-row">
                <div v-for="model in baseModelMap"
                :key="`config_${model[1]}`"
                class="grid-cell">
                    <div 
                      class="node base-model-node"
                      :title="`基础模型: ${model[1] || '未知模型'}`"
                    >
                      <el-icon><cpu /></el-icon>
                      <div class="node-label">
                        {{ model[1] }}
                      </div>
                    </div>
                    <!-- 连接线 - 模型配置到基础模型 -->
                    <div class="connection-line model-to-base"></div>
                    <div class="grid-row model-row">
                      <div 
                        v-for="config in modelConfigs_base(model[0])"
                        :key="`config_${config.id}`"
                        class="grid-cell"
                      >
                        <div 
                          class="node model-node" 
                          :class="{ 'private': config.is_private }"
                          :title="`配置: ${config.name}\n描述: ${config.describe || '无描述'}`"
                        >
                          <el-icon><setting /></el-icon>
                          <div class="node-label">{{ config.name }}</div>
                          <div 
                            :class="[
                              'privacy-tag', 
                              { 'public': !config.is_private }  // 动态添加 public 类
                            ]">{{ config.is_private ? '私有' : '公开' }}</div>
                        </div>
                      </div>
                    </div>
                  
                </div>
              </div>
              
        
              <!-- 知识库行 -->
              <div class="grid-row vector-row">
                <div 
                  v-for="db in vectorDBs" 
                  :key="`db_${db.id}`"
                  class="grid-cell"
                >
                  <div 
                    class="node vector-node"
                    :title="`知识库: ${db.name}\n描述: ${db.describe || '无描述'}`"
                  >
                    <el-icon><data-analysis /></el-icon>
                    <div class="node-label">{{ db.name }}</div>
                  </div>
                  
                  <!-- 连接线 - 知识库到文档 -->
                  <div class="connection-line vector-to-doc"></div>
                  <!-- 文档节点 -->
                  <div class="documents-container">
                    <div 
                      v-for="doc in db.documents" 
                      :key="`doc_${doc.id}`"
                      class="node document-node"
                      :title="`文档: ${doc.original_name}\n类型: ${doc.type}\n大小: ${formatFileSize(doc.size)}`"
                    >
                      <el-icon><document /></el-icon>
                      <div class="node-label">{{ doc.original_name }}</div>
                    </div>
                  </div>
                </div>
              </div>
              
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.content-section {
  margin: 0 auto;
}
.page-title {
  text-align: center;
  color: #2c3e50;
  margin-bottom: 30px;
  font-weight: 600;
  position: relative;
  padding-bottom: 15px;
}

.page-title::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 100px;
  height: 4px;
  background: linear-gradient(90deg, #3498db, #9b59b6);
  border-radius: 2px;
}

.user-info-section {
  background: #fff;
  border: 1px solid #eef0f4;
  border-radius: 12px;
  padding: 20px 24px;
  margin-bottom: 20px;
}

.user-card {
  display: flex;
  align-items: flex-start;
  gap: 20px;
}

.avatar-container {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.avatar-placeholder {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  color: white;
  font-weight: bold;
  object-fit: cover;
}

.change-avatar-btn {
  padding: 4px 10px;
  background-color: transparent;
  color: #64748b;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.78rem;
  transition: all 0.15s ease;
}

.change-avatar-btn:hover {
  background-color: #f1f5f9;
  border-color: #c7d2fe;
  color: #4f46e5;
}

.user-details {
  flex: 1;
}

.user-details h2 {
  margin: 0;
  font-size: 1.3rem;
  color: #1e293b;
  font-weight: 600;
}

.email {
  color: #94a3b8;
  margin: 2px 0 10px;
  font-size: 0.88rem;
}

.user-meta {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 10px;
}

.badge {
  background: #f1f5f9;
  color: #64748b;
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 0.78rem;
  font-weight: 500;
  border: 1px solid #e2e8f0;
}

.join-date {
  color: #94a3b8;
  font-size: 0.82rem;
}

.description {
  color: #475569;
  line-height: 1.6;
  font-size: 0.88rem;
  background: #f8fafc;
  padding: 10px 14px;
  border-radius: 8px;
  border-left: 3px solid #c7d2fe;
}

.tabs-container {
  background: white;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid #eef0f4;
}

.tabs {
  display: flex;
  background: #fafbfd;
  border-bottom: 1px solid #eef0f4;
}

.tab {
  flex: 1;
  padding: 12px 16px;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.88rem;
  font-weight: 500;
  color: #94a3b8;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  transition: all 0.15s ease;
  position: relative;
}

.tab:hover {
  background: #f5f3ff;
  color: #4f46e5;
}

.tab.active {
  background: white;
  color: #4f46e5;
  border-bottom: 2px solid #4f46e5;
}

.tab.active .count-badge {
  background: #4f46e5;
  color: white;
}

.count-badge {
  background: #f1f5f9;
  color: #64748b;
  border-radius: 10px;
  padding: 1px 8px;
  font-size: 0.78rem;
}

.tab-content {
  padding: 16px;
}

/* 模型配置区域 */
.models-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 25px;
}

.model-card {
  border: 1px solid #eaeaea;
  border-radius: 10px;
  padding: 20px;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
  background: white;
  position: relative;
  overflow: hidden;
}

.model-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.08);
  border-color: #3498db;
}

.model-card.private {
  border-left: 4px solid #e74c3c;
}

.model-card:not(.private) {
  border-left: 4px solid #2ecc71;
}

.model-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
  padding-bottom: 15px;
  border-bottom: 1px dashed #eee;
}

.model-header h3 {
  margin: 0;
  font-size: 20px;
  color: #2c3e50;
}

.privacy-tag {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 12px;
  font-weight: 500;
}

.privacy-tag.public {
  background: rgba(46, 204, 113);
  color: #ffffff;
}

.privacy-tag:not(.public) {
  background: rgba(231, 76, 60);
  color: #ffffff;
}
.vector-desc {
  display: -webkit-box;
  -webkit-line-clamp: 5;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
  min-height: 172px;
}

.vector-desc > p { 
  color: #7f8c8d;
  line-height: 1.6;
}
.model-desc {
  display: -webkit-box;
  -webkit-line-clamp: 5;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
  min-height: 172px;
}

.model-desc > p { 
  color: #7f8c8d;
  line-height: 1.6;
}

.model-meta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 20px;
}

.meta-item {
  display: flex;
  flex-direction: column;
}

.label {
  font-size: 13px;
  color: #95a5a6;
  margin-bottom: 3px;
}

.value {
  font-weight: 500;
  color: #2c3e50;
}

.vector-link {
  font-weight: 500;
  color: #3498db;
  cursor: pointer;
  text-decoration: underline;
  text-decoration-color: rgba(52, 152, 219, 0.3);
  transition: all 0.2s;
}

.vector-link:hover {
  color: #2980b9;
  text-decoration-color: #3498db;
}

.model-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px solid #f1f1f1;
  padding-top: 15px;
  margin-top: 10px;
}

.update-date {
  font-size: 13px;
  color: #95a5a6;
}

.action-button {
  background: #f8f9fa;
  border: 1px solid #eaeaea;
  padding: 8px 16px;
  border-radius: 6px;
  color: #3498db;
  cursor: pointer;
  font-weight: 500;
  transition: all 0.2s;
}

.action-button:hover {
  background: #3498db;
  color: white;
  border-color: #3498db;
}

/* 知识库区域 */
.vector-db-container {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 25px;
}

.vector-card {
  border: 1px solid #eaeaea;
  border-radius: 10px;
  overflow: hidden;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
  background: white;
}

.vector-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.08);
}

.vector-header {
  background: linear-gradient(135deg, #3498db, #9b59b6);
  padding: 18px 20px;
  display: flex;
  align-items: center;
  gap: 12px;
  color: white;
}

.vector-header i {
  font-size: 24px;
}

.vector-header h3 {
  margin: 0;
  font-size: 20px;
}

.vector-body {
  padding: 20px;
}

.db-desc {
  color: #7f8c8d;
  line-height: 1.6;
  min-height: 100px;
}

.db-meta {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: #95a5a6;
  margin-top: 15px;
  padding-top: 15px;
  border-top: 1px dashed #eee;
}

.vector-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px 20px;
  background: #f8f9fa;
  border-top: 1px solid #eee;
}

.used-by {
  font-size: 14px;
  color: #7f8c8d;
  display: flex;
  align-items: center;
  gap: 6px;
}

/* 添加样式优化 */
.connections-container {
  width: 100%;
  height: 600px;
  background: white;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
}

/* 确保图表容器有高度 */
#relation-graph {
  min-height: 600px;
}
@keyframes flow {
  0% {
    stroke-dashoffset: 10;
  }
  100% {
    stroke-dashoffset: 0;
  }
}

/* 关系图区域新样式 */
.connections-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding: 0 10px;
}

.connections-header h3 {
  margin: 0;
  font-size: 20px;
  color: #2c3e50;
}

.legend {
  display: flex;
  gap: 15px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 14px;
}

.legend-color {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 50%;
}

.legend-color.user { background-color: #5470c6; }
.legend-color.model { background-color: #91cc75; }
.legend-color.vector { background-color: #fac858; }
.legend-color.document { background-color: #3ba272; }
.legend-color.base-model { background-color: #73c0de; }

.connections-container {
  /* position: relative; 添加相对定位 */
  width: 100%;
  height: 600px;
  background: white;
  border-radius: 8px;
  overflow: auto;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
  padding: 20px;
}

.grid-layout {
  /* position: relative; 添加相对定位 */
  display: flex;
  flex-direction: column;
  height: 100%;
  position: relative;
  min-width: 800px;
}

.grid-row {
  display: flex;
  justify-content: space-around;
  width: 100%;
  position: relative;
  flex: 1;
}

.grid-cell {
  position: relative;
  /* flex: 1; */
  display: flex;
  justify-content: center;
  align-items: center;
  flex-direction: column;
}
.model-row {
  /* min-height: 200px; */
}

.vector-row {
  /* min-height: 200px; */
}

.node {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 15px;
  border-radius: 8px;
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
  transition: all 0.3s ease;
  cursor: pointer;
  z-index: 10;
  text-align: center;
  max-width: 200px;
  min-width: 150px;
}

.node:hover {
  transform: translateY(-5px);
  box-shadow: 0 8px 16px rgba(0, 0, 0, 0.15);
}
.model-node {
  background: linear-gradient(135deg, #91cc75, #73a95c);
  color: white;
}

.model-node.private {
  background: linear-gradient(135deg, #ee6666, #c95151);
}

.vector-node {
  background: linear-gradient(135deg, #fac858, #e0b347);
  color: white;
}

.document-node {
  background: linear-gradient(135deg, #3ba272, #2d855b);
  color: white;
  width: 130px;
  margin: 5px auto;
}

.base-model-node {
  background: linear-gradient(135deg, #73c0de, #5aa7c7);
  color: white;
  width: 130px;
  margin-top: 20px;
}

.node-label {
  font-size: 14px;
  font-weight: 500;
  margin-top: 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  width: 100%;
}

.privacy-tag {
  position: absolute;
  top: -8px;
  right: -8px;
  background: white;
  color: #333;
  font-size: 12px;
  padding: 3px 8px;
  border-radius: 12px;
  font-weight: bold;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

/* 连接线样式 */
.connection-line {
  /* position: absolute; */
  background: #9a9a9a;
  z-index: 1;
}

.connection-line::after {
  content: '';
  /* position: absolute; */
  width: 8px;
  height: 8px;
  border-right: 2px solid #9a9a9a;
  border-bottom: 2px solid #9a9a9a;
  transform: rotate(45deg);
}

.model-to-base {
  /* top: 100%; */
  left: 50%;
  width: 2px;
  height: 40px;
  transform: translateX(-50%);
}

.model-to-base::after {
  bottom: -4px;
  left: -3px;
}

.vector-to-doc {
  /* top: 100%; */
  left: 50%;
  width: 2px;
  height: 40px;
  transform: translateX(-50%);
}

.vector-to-doc::after {
  bottom: -4px;
  left: -3px;
}

.documents-container {
  position: absolute;
  top: 100%;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  /* padding-top: 50px; */
  width: 100%;
  flex-direction: row;
}

.base-model-container {
  position: absolute;
  top: 100%;
  width: 100%;
  padding-top: 50px;
}

/* 新增样式 */
.connections-lines {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 5;
}

.connection-line.model-to-vector {
  position: absolute;
  height: 2px;
  background: #9a9a9a;
  transform-origin: left center;
  z-index: 1;
}

.connection-line.model-to-vector::after {
  content: '';
  position: absolute;
  right: -5px;
  top: -4px;
  width: 8px;
  height: 8px;
  border-right: 2px solid #9a9a9a;
  border-bottom: 2px solid #9a9a9a;
  transform: rotate(-45deg);
}
</style>
