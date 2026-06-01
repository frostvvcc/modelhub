# ModelHub Backend

AI 模型管理与对话平台 - FastAPI 后端

## 🚀 快速开始

### 使用 UV（推荐）

```bash
# 1. 安装依赖
./uv_install.sh

# 2. 配置环境变量
cp .env.example .env  # 如果存在
# 编辑 .env 文件

# 3. 运行应用
./uv_run.sh
```

### 使用传统方式

```bash
# 1. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# 或 .venv\Scripts\activate  # Windows

# 2. 安装依赖
pip install -r requirements-fastapi.txt

# 3. 运行应用
python main_fastapi.py
```

## 📋 项目特性

- ✅ **FastAPI**: 现代、快速的 Web 框架
- ✅ **异步数据库**: 使用 aiomysql 实现真正的异步 I/O
- ✅ **JWT 认证**: 安全的用户认证系统
- ✅ **向量数据库**: ChromaDB 集成，支持 RAG
- ✅ **LLM 集成**: 支持多种大语言模型
- ✅ **Redis 缓存**: 高性能缓存系统

## 📁 项目结构

```
ModelHub-backend/
├── app/                  # FastAPI 应用代码（统一目录）
│   ├── routers/         # API 路由
│   ├── services/        # 业务逻辑层（异步）
│   ├── mappers/         # 数据访问层（异步）
│   ├── schemas/         # Pydantic 模型
│   ├── models/          # 数据库模型
│   ├── utils/           # 工具函数
│   ├── config.py        # 配置管理
│   └── database*.py     # 数据库配置
├── main_fastapi.py      # FastAPI 应用入口
├── pyproject.toml       # UV 项目配置
└── requirements-fastapi.txt  # 依赖列表
```

## 🔧 环境要求

- Python >= 3.9 (推荐 3.11)
- MySQL 5.7+ 或 8.0+
- Redis 6.0+
- ChromaDB (可选，用于向量数据库)

## ⚙️ 环境变量配置

创建 `.env` 文件：

```env
# 数据库配置
DB_CONNECTION=mysql
DB_HOST=localhost
DB_PORT=3306
DB_DATABASE=modelhub
DB_USERNAME=root
DB_PASSWORD=your_password

# JWT 配置
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# ChromaDB 配置
CHROMA_SERVER_HOST=localhost
CHROMA_SERVER_PORT=8000

# Redis 配置
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# 嵌入模型配置
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_API_KEY=your_api_key
```

## 📚 文档

- [UV 快速开始](QUICK_START_UV.md) - UV 虚拟环境使用指南
- [UV 详细指南](UV_GUIDE.md) - UV 完整文档
- [FastAPI 快速开始](QUICK_START_FASTAPI.md) - FastAPI 使用指南
- [架构文档](ARCHITECTURE_FASTAPI.md) - 系统架构说明
- [异步数据库指南](DATABASE_ASYNC_GUIDE.md) - 异步数据库使用说明

## 🧪 测试

```bash
# 测试 UV 配置
./uv_test.sh

# 运行应用测试
pytest tests/
```

## 📡 API 文档

启动应用后访问：

- **Swagger UI**: http://localhost:5000/docs
- **ReDoc**: http://localhost:5000/redoc
- **OpenAPI JSON**: http://localhost:5000/openapi.json

## 🛠️ 开发

### 安装开发依赖

```bash
# 使用 UV
uv pip install -e ".[dev]"

# 或使用 pip
pip install -r requirements-fastapi.txt
```

### 代码格式化

```bash
# 使用 black
black app_fastapi/

# 使用 ruff
ruff check app_fastapi/
```

## 🎯 主要功能

### 用户管理
- 用户注册/登录
- JWT 认证
- 用户信息管理

### 模型管理
- 模型配置管理
- 模型信息查询
- 公共/私有配置

### 对话功能
- 实时对话
- 历史记录
- 上下文管理

### 向量数据库
- 向量数据库创建/管理
- 文档上传/查询
- RAG 支持

## 📝 更新日志

### v2.0.0 (当前版本)
- ✅ 迁移到 FastAPI
- ✅ 实现异步数据库
- ✅ 完整的异步架构
- ✅ UV 虚拟环境支持

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

[添加许可证信息]

## 🔗 相关链接

- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [UV 文档](https://github.com/astral-sh/uv)
- [SQLAlchemy 文档](https://docs.sqlalchemy.org/)
