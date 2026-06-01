# ModelHub 数据库字段说明与表关系文档

## 概述

- **ORM 框架**: SQLAlchemy（支持异步）
- **数据库类型**: MySQL / SQLite
- **模型目录**: `ModelHub-backend/app/models/`
- **共计**: 18 张表

---

## 一、用户与认证模块

### 1. user（用户表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| name | String(255) | 用户名 | 不可为空 |
| avatar | String(255) | 头像 | 头像 URL 地址 |
| password | String(255) | 密码 | 加密存储，不可为空 |
| email | String(255) | 邮箱 | 可为空 |
| describe | String(255) | 个人描述 | 用户简介 |
| type | Integer | 用户类型 | 旧字段，已弃用 |
| role | String(20) | 角色 | 默认 "student"，可选值: admin/school_admin/teacher/student |
| school_id | Integer | 所属学校 ID | 外键 → organization.id |
| student_id | String(50) | 学号 | 学生专用 |
| employee_id | String(50) | 工号 | 教职工专用 |
| phone | String(20) | 手机号 | 联系电话 |
| status | String(20) | 账号状态 | 默认 "active"，可选值: active/inactive/suspended |
| create_at | DateTime | 创建时间 | 服务端自动生成 |
| update_at | DateTime | 更新时间 | 修改时自动更新 |

---

### 2. role（角色表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| name | String(100) | 角色名称 | 不可为空 |
| code | String(100) | 角色代码 | 唯一，不可为空，如 "school_admin" |
| description | String(500) | 描述 | 角色说明 |
| level | String(50) | 作用层级 | 默认 "class"，可选值: system/school/college/department/class |
| is_system | Boolean | 是否系统角色 | 默认 False，系统内置角色不可删除 |
| school_id | Integer | 所属学校 ID | 外键 → organization.id，系统角色为空 |
| create_at | DateTime | 创建时间 | 服务端自动生成 |
| update_at | DateTime | 更新时间 | 修改时自动更新 |

---

### 3. permission（权限表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| name | String(100) | 权限名称 | 不可为空 |
| code | String(100) | 权限代码 | 唯一，不可为空，如 "knowledge:read" |
| description | String(500) | 描述 | 权限说明 |
| resource | String(50) | 资源类型 | 不可为空，可选值: knowledge/chat/config/user/organization |
| action | String(50) | 操作类型 | 不可为空，可选值: read/write/delete/manage |
| create_at | DateTime | 创建时间 | 服务端自动生成 |
| update_at | DateTime | 更新时间 | 修改时自动更新 |

---

### 4. role_permission（角色-权限关联表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| role_id | Integer | 角色 ID | 外键 → role.id，不可为空 |
| permission_id | Integer | 权限 ID | 外键 → permission.id，不可为空 |
| create_at | DateTime | 创建时间 | 服务端自动生成 |

> **约束**: (role_id, permission_id) 联合唯一

---

### 5. user_role（用户-角色关联表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| user_id | Integer | 用户 ID | 外键 → user.id，不可为空 |
| role_id | Integer | 角色 ID | 外键 → role.id，不可为空 |
| organization_id | Integer | 组织 ID | 外键 → organization.id，角色生效的组织范围 |
| scope | String(50) | 作用域 | 可选值: system/school/college/department/class |
| is_active | Boolean | 是否生效 | 默认 True |
| create_at | DateTime | 创建时间 | 服务端自动生成 |
| update_at | DateTime | 更新时间 | 修改时自动更新 |

---

## 二、组织架构模块

### 6. organization（组织表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| name | String(255) | 组织名称 | 不可为空 |
| code | String(100) | 组织代码 | 唯一，不可为空 |
| type | String(50) | 组织类型 | 不可为空，可选值: school/college/department/class/research_group/laboratory/administrative |
| parent_id | Integer | 上级组织 ID | 外键 → organization.id（自引用），根节点为空 |
| school_id | Integer | 所属学校 ID | 外键 → organization.id（自引用），冗余字段便于查询 |
| level | Integer | 层级深度 | 默认 1，1=学校 2=学院 3=专业/系 4=班级 |
| path | String(500) | 路径 | 如 "1/2/5"，用于快速查询子树 |
| description | String(500) | 描述 | 组织说明 |
| status | String(20) | 状态 | 默认 "active"，可选值: active/inactive/suspended |
| create_at | DateTime | 创建时间 | 服务端自动生成 |
| update_at | DateTime | 更新时间 | 修改时自动更新 |

---

### 7. organization_member（组织成员表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| user_id | Integer | 用户 ID | 外键 → user.id，不可为空 |
| organization_id | Integer | 组织 ID | 外键 → organization.id，不可为空 |
| role | String(50) | 成员角色 | 默认 "member"，可选值: admin/teacher/student/guest/member |
| status | String(20) | 成员状态 | 默认 "active"，可选值: active/inactive |
| join_at | DateTime | 加入时间 | 服务端自动生成 |
| create_at | DateTime | 创建时间 | 服务端自动生成 |
| update_at | DateTime | 更新时间 | 修改时自动更新 |

---

## 三、AI 模型与供应商模块

### 8. provider_config（模型供应商配置表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| name | String(100) | 供应商名称 | 不可为空，如 "OpenAI"、"阿里云通义" |
| code | String(50) | 供应商代码 | 唯一，不可为空，如 "openai"、"aliyun" |
| provider_type | String(50) | 供应商类型 | 不可为空，可选值: openai/aliyun/anthropic/local/custom |
| base_url | String(500) | API 基础地址 | 不可为空 |
| api_key | String(500) | API Key | 认证密钥 |
| api_secret | String(500) | API Secret | 部分供应商需要 |
| config_json | Text | 扩展配置 | JSON 格式额外配置 |
| description | Text | 描述 | 供应商说明 |
| is_active | Boolean | 是否启用 | 默认 True |
| is_default | Boolean | 是否默认 | 默认 False |
| priority | Integer | 优先级 | 默认 0，数值越大优先级越高 |
| rate_limit | Integer | 请求频率限制 | 每分钟最大请求数 |
| max_tokens | Integer | 最大 Token 数 | 供应商级别限制 |
| supported_model_types | String(100) | 支持的模型类型 | 逗号分隔，如 "chatllm,embedding" |
| create_at | DateTime | 创建时间 | 服务端自动生成 |
| update_at | DateTime | 更新时间 | 修改时自动更新 |

---

### 9. model_info（模型信息表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| model_name | String(255) | 模型名称 | 唯一，不可为空，如 "gpt-4"、"qwen-turbo" |
| type | Enum | 模型类型 | 不可为空，可选值: chatllm / embedding |
| provider_id | Integer | 供应商 ID | 外键 → provider_config.id，不可为空 |
| base_url | String(500) | API 地址 | 旧字段，优先使用供应商配置 |
| api_key | String(500) | API Key | 旧字段，优先使用供应商配置 |
| model_endpoint | String(255) | 模型端点 | 如 "/v1/chat/completions" |
| describe | Text | 描述 | 模型说明 |
| version | String(50) | 版本 | 模型版本号 |
| max_tokens | Integer | 最大 Token | 单次请求最大 Token |
| context_window | Integer | 上下文窗口 | 最大上下文长度 |
| is_active | Boolean | 是否启用 | 默认 True |
| is_default | Boolean | 是否默认 | 默认 False |
| priority | Integer | 优先级 | 默认 0 |
| create_at | DateTime | 创建时间 | 服务端自动生成 |
| update_at | DateTime | 更新时间 | 修改时自动更新 |

---

### 10. model_config（数字助理配置表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| user_id | Integer | 创建者 ID | 外键 → user.id，不可为空 |
| share_id | String(255) | 分享 ID | 唯一，用于分享链接 |
| base_model_id | Integer | 基础模型 ID | 外键 → model_info.id，不可为空 |
| name | String(255) | 配置名称 | 不可为空 |
| temperature | Numeric(10,2) | 温度参数 | 默认 0.70，控制输出随机性 |
| top_p | Numeric(10,2) | Top-P 参数 | 默认 0.70，核采样阈值 |
| prompt | Text | 系统提示词 | 模型人设/角色设定 |
| prompt_variables | Text | 提示词变量 | JSON 格式，动态变量定义 |
| knowledge_context_template | Text | 知识库上下文模板 | 检索结果注入模板 |
| citation_template | String(100) | 引用模板 | 默认 "[来源{index}]" |
| refusal_strategy | Text | 拒答策略 | 无法回答时的处理方式 |
| max_context_chars | Integer | 最大上下文字符数 | 默认 6000 |
| answer_with_citations | Boolean | 是否带引用回答 | 默认 True |
| describe | String(255) | 描述 | 配置说明 |
| organization_id | Integer | 所属组织 ID | 外键 → organization.id |
| school_id | Integer | 所属学校 ID | 外键 → organization.id，冗余字段 |
| scope | String(20) | 可见范围 | 默认 "private"，可选值: public/organization/private |
| is_private | Boolean | 是否私有 | 默认 False |
| create_at | DateTime | 创建时间 | 服务端自动生成 |
| update_at | DateTime | 更新时间 | 修改时自动更新 |

---

## 四、知识库模块

### 11. vector_db（向量知识库表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| user_id | Integer | 创建者 ID | 外键 → user.id，不可为空 |
| embedding_id | Integer | 向量模型 ID | 外键 → model_info.id，不可为空 |
| name | String(255) | 知识库名称 | 唯一，不可为空 |
| document_similarity | Numeric(5,2) | 相似度阈值 | 默认 0.70，检索匹配最低相似度 |
| describe | String(255) | 描述 | 知识库说明 |
| organization_id | Integer | 所属组织 ID | 外键 → organization.id |
| school_id | Integer | 所属学校 ID | 外键 → organization.id，冗余字段 |
| scope | String(20) | 可见范围 | 默认 "private"，可选值: public/teacher/private |
| access_level | String(20) | 访问层级 | 可选值: school/college/department/class |
| create_at | DateTime | 创建时间 | 服务端自动生成 |
| update_at | DateTime | 更新时间 | 修改时自动更新 |

---

### 12. document（文档表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| user_id | Integer | 上传者 ID | 外键 → user.id，不可为空 |
| vector_db_id | Integer | 所属知识库 ID | 外键 → vector_db.id，不可为空 |
| name | String(255) | 文档名称 | 不可为空 |
| original_name | String(255) | 原始文件名 | 上传时的文件名 |
| type | String(64) | 文件类型 | 如 "pdf"、"txt"、"docx" |
| size | Integer | 文件大小 | 默认 0，单位字节 |
| save_path | Text | 存储路径 | 服务器本地存储路径 |
| describe | String(255) | 描述 | 文档说明 |
| status | String(20) | 处理状态 | 默认 "success"，可选值: processing/success/failed/archived |
| error_message | Text | 错误信息 | 处理失败时的错误详情 |
| archived_at | DateTime | 归档时间 | 文档被归档的时间 |
| parent_id | Integer | 父级 ID | 外键 → document.id（自引用），文件夹层级 |
| is_folder | Boolean | 是否为文件夹 | 默认 False |
| folder_path | String(500) | 文件夹路径 | 层级路径如 "1/2/5" |
| upload_at | DateTime | 上传时间 | 服务端自动生成 |

---

## 五、对话模块

### 13. conversation（会话表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| user_id | Integer | 用户 ID | 外键 → user.id，不可为空 |
| name | String(255) | 会话名称 | 对话标题 |
| model_config_id | Integer | 数字助理配置 ID | 外键 → model_config.id，不可为空 |
| chat_history | Integer | 历史消息数 | 默认 20，发送给模型的历史条数 |
| organization_id | Integer | 所属组织 ID | 外键 → organization.id |
| school_id | Integer | 所属学校 ID | 外键 → organization.id，冗余字段 |
| create_at | DateTime | 创建时间 | 服务端自动生成 |
| update_at | DateTime | 更新时间 | 修改时自动更新 |

---

### 14. message（消息表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| conversation_id | Integer | 会话 ID | 外键 → conversation.id，不可为空 |
| role | String(10) | 角色 | 不可为空，如 "user"、"assistant"、"system" |
| content | Text | 消息内容 | 消息正文 |
| create_at | DateTime | 创建时间 | 服务端自动生成 |

---

## 六、Bot（数字人）模块

### 15. bot（Bot 表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| name | String(100) | Bot 名称 | 不可为空 |
| description | Text | 描述 | Bot 说明 |
| avatar | String(255) | 头像 | 头像 URL |
| system_prompt | Text | 系统提示词 | Bot 的人设/角色设定 |
| greeting | String(500) | 开场白 | 对话开始时的欢迎语 |
| forbidden_topics | JSON | 禁止话题 | JSON 数组，Bot 不回答的话题 |
| model_config_id | Integer | 数字助理配置 ID | 外键 → model_config.id |
| vector_db_ids | JSON | 关联知识库 ID 列表 | JSON 数组，Bot 绑定的知识库 |
| visibility | String(20) | 可见范围 | 默认 "private"，可选值: public/organization/private |
| user_id | Integer | 创建者 ID | 外键 → user.id，不可为空 |
| org_id | Integer | 所属组织 ID | 外键 → organization.id |
| school_id | Integer | 所属学校 ID | 外键 → organization.id，冗余字段 |
| created_at | DateTime | 创建时间 | 服务端自动生成 |
| updated_at | DateTime | 更新时间 | 修改时自动更新 |

---

## 七、教学空间模块

### 16. teaching_space（教学空间表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| name | String(255) | 空间名称 | 不可为空 |
| description | Text | 描述 | 空间说明 |
| teacher_id | Integer | 教师 ID | 外键 → user.id，不可为空，空间创建者 |
| school_id | Integer | 所属学校 ID | 外键 → organization.id |
| status | String(20) | 状态 | 默认 "active"，可选值: active/archived |
| created_at | DateTime | 创建时间 | 服务端自动生成 |
| updated_at | DateTime | 更新时间 | 修改时自动更新 |

---

### 17. teaching_space_major（教学空间-专业绑定表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| space_id | Integer | 教学空间 ID | 外键 → teaching_space.id（级联删除），不可为空 |
| major_id | Integer | 专业 ID | 外键 → organization.id，不可为空 |
| created_at | DateTime | 创建时间 | 服务端自动生成 |

> **约束**: (space_id, major_id) 联合唯一

---

### 18. teaching_space_resource（教学空间-资源关联表）

| 字段 | 类型 | 中文含义 | 说明 |
|------|------|----------|------|
| id | Integer | 主键 | 自增主键 |
| space_id | Integer | 教学空间 ID | 外键 → teaching_space.id（级联删除），不可为空 |
| resource_type | String(20) | 资源类型 | 不可为空，可选值: vector_db / bot |
| resource_id | Integer | 资源 ID | 不可为空，指向 vector_db.id 或 bot.id |
| created_at | DateTime | 创建时间 | 服务端自动生成 |

> **约束**: (space_id, resource_type, resource_id) 联合唯一

---

## 八、表关系总览

### ER 关系图（文字版）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           组织架构层                                      │
│                                                                         │
│  organization ←──(自引用 parent_id)──→ organization                      │
│       │                                                                 │
│       ├── organization_member ──→ user                                  │
│       ├── role.school_id                                                │
│       ├── user.school_id                                                │
│       └── (多表的 organization_id / school_id 冗余外键)                   │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                           权限层 (RBAC)                                   │
│                                                                         │
│  user ──→ user_role ──→ role ──→ role_permission ──→ permission          │
│                │                                                        │
│                └── organization (作用域)                                  │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                           AI 模型层                                       │
│                                                                         │
│  provider_config ──→ model_info ──→ model_config ──→ conversation       │
│                                         │                │              │
│                                         │                └── message    │
│                                         └── bot                         │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                           知识库层                                        │
│                                                                         │
│  vector_db ──→ document ←──(自引用 parent_id 文件夹)                      │
│      │                                                                  │
│      └── model_info (embedding_id)                                      │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                           教学空间层                                      │
│                                                                         │
│  teaching_space ──→ teaching_space_major ──→ organization (专业)          │
│        │                                                                │
│        └── teaching_space_resource ──→ vector_db / bot (多态关联)         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### 详细外键关系列表

| 源表 | 源字段 | 目标表 | 目标字段 | 关系类型 | 说明 |
|------|--------|--------|----------|----------|------|
| user | school_id | organization | id | 多对一 | 用户所属学校 |
| organization | parent_id | organization | id | 自引用多对一 | 上级组织 |
| organization | school_id | organization | id | 自引用多对一 | 所属学校（冗余） |
| organization_member | user_id | user | id | 多对一 | 成员用户 |
| organization_member | organization_id | organization | id | 多对一 | 所属组织 |
| role | school_id | organization | id | 多对一 | 角色所属学校 |
| role_permission | role_id | role | id | 多对一 | 所属角色 |
| role_permission | permission_id | permission | id | 多对一 | 关联权限 |
| user_role | user_id | user | id | 多对一 | 所属用户 |
| user_role | role_id | role | id | 多对一 | 关联角色 |
| user_role | organization_id | organization | id | 多对一 | 角色作用组织 |
| model_info | provider_id | provider_config | id | 多对一 | 所属供应商 |
| model_config | user_id | user | id | 多对一 | 创建者 |
| model_config | base_model_id | model_info | id | 多对一 | 基础模型 |
| model_config | organization_id | organization | id | 多对一 | 所属组织 |
| model_config | school_id | organization | id | 多对一 | 所属学校（冗余） |
| vector_db | user_id | user | id | 多对一 | 创建者 |
| vector_db | embedding_id | model_info | id | 多对一 | 向量化模型 |
| vector_db | organization_id | organization | id | 多对一 | 所属组织 |
| vector_db | school_id | organization | id | 多对一 | 所属学校（冗余） |
| document | user_id | user | id | 多对一 | 上传者 |
| document | vector_db_id | vector_db | id | 多对一 | 所属知识库 |
| document | parent_id | document | id | 自引用多对一 | 父级文件夹 |
| conversation | user_id | user | id | 多对一 | 所属用户 |
| conversation | model_config_id | model_config | id | 多对一 | 使用的数字助理配置 |
| conversation | organization_id | organization | id | 多对一 | 所属组织 |
| conversation | school_id | organization | id | 多对一 | 所属学校（冗余） |
| message | conversation_id | conversation | id | 多对一 | 所属会话 |
| bot | model_config_id | model_config | id | 多对一 | 使用的模型配置 |
| bot | user_id | user | id | 多对一 | 创建者 |
| bot | org_id | organization | id | 多对一 | 所属组织 |
| bot | school_id | organization | id | 多对一 | 所属学校（冗余） |
| teaching_space | teacher_id | user | id | 多对一 | 教师（创建者） |
| teaching_space | school_id | organization | id | 多对一 | 所属学校 |
| teaching_space_major | space_id | teaching_space | id | 多对一（级联删除） | 所属教学空间 |
| teaching_space_major | major_id | organization | id | 多对一 | 绑定的专业 |
| teaching_space_resource | space_id | teaching_space | id | 多对一（级联删除） | 所属教学空间 |
| teaching_space_resource | resource_id | vector_db / bot | id | 多态关联 | 资源（根据 resource_type 决定） |

---

## 九、设计特点

1. **多租户架构**: 通过 `organization_id` + `school_id` 冗余字段实现组织隔离，`school_id` 冗余存储便于快速过滤学校维度数据
2. **RBAC 权限体系**: user → user_role → role → role_permission → permission 五层结构，支持按组织粒度授权
3. **自引用层级**: organization（组织树）和 document（文件夹树）均使用 parent_id 自引用 + path 路径字段实现层级结构
4. **多态关联**: teaching_space_resource 通过 resource_type + resource_id 组合实现对不同类型资源的关联
5. **可见范围控制**: 多个表使用 scope/visibility 字段控制数据可见性（public/organization/private）
6. **教育领域定制**: 组织层级（学校→学院→专业→班级）、教学空间、学号/工号等字段面向高校场景
