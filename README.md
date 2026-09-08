# ModelHub - 大学综合检索对话平台

## 项目简介

ModelHub 是一个专为大学场景设计的**综合检索对话平台**，支持层级化组织架构管理、基于角色的权限控制（RBAC）、多租户数据隔离、向量数据库管理和智能对话等功能。平台采用前后端分离架构，为大学提供完整的知识管理和智能问答解决方案。

### 核心特性

- **层级化组织架构**：支持学校 -> 学院 -> 系 -> 班级的无限层级扩展
- **层级化权限管理**：基于 RBAC 的权限系统，支持权限继承
- **多租户数据隔离**：按学校进行数据隔离，确保数据安全
- **RAG 检索增强生成**：向量检索 + BM25 混合检索 + RRF 融合排序
- **组织级知识库管理**：按组织层级管理知识库，支持权限控制
- **Bot Builder**：三步创建智能体，绑定知识库和模型

## 技术栈

### 后端
- **框架**: FastAPI 0.115.12
- **服务器**: Uvicorn（ASGI）
- **数据库**: MySQL（SQLAlchemy 2.0 异步 ORM）
- **向量数据库**: ChromaDB
- **缓存**: Redis（连接池优化）
- **认证**: JWT（python-jose）
- **数据验证**: Pydantic 2.11.5
- **AI**: LlamaIndex + OpenAI 兼容接口
- **文档处理**: python-docx / PyPDF2 / PaddleOCR（可选）

### 前端
- **框架**: Vue 3.5.13 + TypeScript
- **构建工具**: Vite 6.3.5
- **UI**: Element Plus 2.10.1
- **状态管理**: Pinia 3.0.3
- **路由**: Vue Router 4.5.1
- **Markdown**: Marked + Highlight.js

## 项目结构

```
modelhub/
├── backend/                       # 后端（FastAPI）
│   ├── main_fastapi.py            # 应用入口
│   ├── app/
│   │   ├── __init__.py            # FastAPI 应用工厂
│   │   ├── config.py              # Pydantic Settings 配置
│   │   ├── database_async.py      # 异步数据库引擎
│   │   ├── mappers/               # 数据访问层（8 个 Mapper）
│   │   ├── models/                # SQLAlchemy 模型（13 个表）
│   │   ├── routers/               # API 路由（8 个模块）
│   │   ├── schemas/               # Pydantic 请求/响应模型
│   │   ├── services/              # 业务逻辑层
│   │   │   └── rag/               # RAG 模块（分块/解析/检索）
│   │   ├── middleware/            # 错误处理中间件
│   │   └── utils/                 # 工具类
│   ├── alembic/                   # 数据库迁移
│   ├── tests/                     # 测试（unit + integration）
│   ├── scripts/                   # 初始化与管理脚本
│   ├── pyproject.toml             # 项目元数据与依赖
│   ├── Dockerfile
│   └── .env.example               # 环境变量模板
│
├── frontend/                      # 前端（Vue 3 + TypeScript）
│   ├── src/
│   │   ├── api/                   # API 接口（9 个模块）
│   │   ├── components/            # 公共组件
│   │   ├── layouts/               # 布局组件
│   │   ├── router/                # 路由配置（19 个路由）
│   │   ├── stores/                # Pinia 状态管理
│   │   ├── types/                 # TypeScript 类型定义
│   │   ├── utils/                 # 工具函数
│   │   └── views/                 # 页面视图（21 个页面）
│   ├── package.json
│   ├── vite.config.ts
│   └── Dockerfile
│
├── scripts/                       # 启动/部署脚本
├── docker-compose.yml             # Docker Compose 编排
├── DATABASE.md                    # 数据库设计文档
└── LICENSE
```

## 快速开始

### Docker Compose 一键启动

```bash
# 1. 配置环境变量
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入数据库密码和 API Key

# 2. 启动所有服务
docker compose up -d

# 3. 初始化数据库
docker compose exec backend python scripts/create_tables.py
docker compose exec backend python scripts/init_sample_data.py
```

访问：
- 前端：http://localhost:8080
- 后端 API 文档：http://localhost:5000/docs

### 本地开发

**后端：**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-fastapi.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env

# 创建数据库表
python scripts/create_tables.py

# 启动
uvicorn main_fastapi:app --host 0.0.0.0 --port 5000 --reload
```

**前端：**
```bash
cd frontend
npm install
npm run dev
```

### 依赖服务

| 服务 | 用途 | 默认端口 |
|------|------|---------|
| MySQL 8.0 | 主数据库 | 3306 |
| ChromaDB | 向量数据库 | 8000 |
| Redis（可选） | 缓存 | 6379 |

## 环境变量

在 `backend/.env` 中配置：

```env
# 数据库
DB_CONNECTION=mysql
DB_HOST=localhost
DB_PORT=3306
DB_DATABASE=modelhub
DB_USERNAME=root
DB_PASSWORD=your_password

# JWT
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# 嵌入模型
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_API_KEY=your_api_key

# ChromaDB
CHROMA_SERVER_HOST=localhost
CHROMA_SERVER_PORT=8000

# Redis（可选）
REDIS_HOST=localhost
REDIS_PORT=6379

# CORS
CORS_ORIGINS=*
```

## 核心架构

### 后端分层架构

```
Router（路由层）→ Service（业务逻辑层）→ Mapper（数据访问层）→ Model（ORM 模型）
```

- **Router**：处理 HTTP 请求，参数校验，权限检查
- **Service**：业务逻辑，全链路 async/await
- **Mapper**：数据库 CRUD，AsyncSession
- **Schema**：Pydantic 请求/响应模型

### 数据库设计（18 张表）

| 模块 | 表 | 说明 |
|------|---|------|
| 用户认证 | user, role, permission, role_permission, user_role | 5 层 RBAC 权限模型 |
| 组织架构 | organization, organization_member | 自引用树 + 成员管理 |
| AI 模型 | provider_config, model_info, model_config | 模型供应链管理 |
| 知识库 | vector_db, document | 向量库 + 文档层级管理 |
| 对话 | conversation, message | 对话历史 + 组织上下文 |
| 智能体 | bot | Bot Builder 配置 |
| 教学空间 | teaching_space, teaching_space_major, teaching_space_resource | 教学资源管理 |

### RAG 检索流程

```
用户提问 → 文档检索（向量 + BM25 混合）→ RRF 融合排序 → Cross-Encoder 重排 → MMR 去重
        → CRAG 质量评估（不足则改写查询补充检索，限次）→ 上下文注入 → LLM 流式生成 → 引用标注
```

- 3 种分块策略：定长 / 句子边界 / Markdown 标题层级
- 混合检索：向量相似度 + BM25 关键词匹配
- RRF 融合排序，自动引用编号
- CRAG 自纠错：生成前基于检索分数评估质量，不足时改写查询补充检索（`RAG_CRAG_*` 配置），全程只生成一次、真流式
- 运行时监控：`GET /metrics` 暴露 Prometheus 指标（各阶段延迟、top1 相关度、grounding 比率、CRAG 触发率等）

## 测试

```bash
cd backend

# 单元测试
python -m pytest tests/unit/ -v

# 集成测试
INTEGRATION_TESTS=1 python -m pytest tests/integration/ -v

# 全部测试
INTEGRATION_TESTS=1 python -m pytest -v
```

## API 概览

| 模块 | 路径前缀 | 主要接口 |
|------|---------|---------|
| 用户 | `/user` | 注册、登录、用户信息、头像 |
| 组织 | `/organization` | 组织 CRUD、成员管理、组织树 |
| 权限 | `/permission` | 角色/权限 CRUD、权限检查 |
| 模型 | `/model` | 模型信息、模型配置 CRUD |
| 供应商 | `/provider` | 供应商配置管理 |
| 知识库 | `/vector` | 知识库 CRUD、文档上传/检索 |
| 对话 | `/chat` | 发送消息、对话历史、重新回答 |
| 智能体 | `/bot` | Bot CRUD、Bot 对话 |

完整 API 文档启动后访问：http://localhost:5000/docs

## License

MIT License
