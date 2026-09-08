# 测试指南

## 运行方式

### 单元测试（无需外部服务）

```bash
cd ModelHub-backend
pytest tests/unit/
```

### 集成测试（使用内存 SQLite，无需 MySQL/Redis）

```bash
cd ModelHub-backend
INTEGRATION_TESTS=1 pytest tests/integration/
```

> **必须加 `INTEGRATION_TESTS=1`**，否则根级 `conftest.py` 会把 `aiosqlite` 替换成 MagicMock，导致所有集成测试失败。

### 全量运行

```bash
INTEGRATION_TESTS=1 pytest tests/
```

---

## 测试分层

| 层级 | 目录 | 数量 | 外部依赖 |
|------|------|------|---------|
| 单元测试 | `tests/unit/` | 97 | 无（全部 mock） |
| 集成测试 | `tests/integration/` | 60 | 无（内存 SQLite） |

---

## 单元测试新增用例（2026-09）

### CRAG 编排器 `test_graph_orchestrator.py`（8）
- `test_good_retrieval_skips_correction` — 检索质量高时直通生成，不触发纠错
- `test_low_score_triggers_single_correction_and_single_synthesis` — 低分触发查询改写+补充检索，且**生成只执行一次**（防回答重复生成回归）
- `test_correction_bounded_when_still_insufficient` — 纠错次数受 `RAG_CRAG_MAX_RETRIES` 限制，用尽后仍生成兜底回答
- `test_duplicate_chunks_deduped_on_corrective_round` — 补充检索与首轮来源合并去重、编号连续
- `test_crag_disabled_bypasses_grading` — `RAG_CRAG_ENABLED=false` 时完全旁路
- `TestHeuristicGrade`（3）— 启发式评分：空结果 / 低分 / 高分

### Prometheus 指标 `test_prometheus_metrics.py`（4）
- 计数器/直方图更新、低置信度计数、CRAG 触发与 grounding 比率、RAGMonitor 联动

### 文档解析 `test_document_parser.py` 新增（1）
- `test_table_preserved_as_markdown_in_position` — Word 表格按正文位置输出 Markdown 结构

---

## 集成测试用例清单

### 组织服务 `test_organization_service.py`（4）
- `test_create_organization` — 创建子组织，验证层级自动推导
- `test_get_organization_by_id` — 按 ID 查询组织
- `test_get_organization_tree` — 获取组织树（含子节点）
- `test_update_organization` — 更新组织名称和描述

### 组织 API `test_organization_api.py`（2）
- `test_create_organization_api` — POST `/organization/create`，含 JWT 认证
- `test_get_organization_tree_api` — GET `/organization/{id}/tree`，含 JWT 认证

### 权限服务 `test_permission_service.py`（4）
- `test_create_role` — 创建角色
- `test_assign_permission_to_role` — 为角色分配权限
- `test_check_permission` — 检查用户权限
- `test_get_user_permissions` — 获取用户权限列表

### 供应商服务 `test_provider_service.py`（10）
- `test_create_provider` — 创建供应商配置
- `test_create_provider_invalid_type` — 无效类型抛 `ValidationError`
- `test_get_provider` — 按 ID 查询供应商
- `test_get_provider_not_found` — 不存在时抛 `NotFoundError`
- `test_get_provider_by_code` — 按 code 查询
- `test_get_all_providers` — 获取全部供应商
- `test_get_all_providers_filtered_by_active` — 过滤活跃供应商
- `test_get_default_provider` — 获取默认供应商
- `test_update_provider` — 更新供应商
- `test_delete_provider` — 删除供应商

### 模型服务 `test_model_service.py`（11）
- `test_get_all_model_info_empty` — 空库时返回空列表
- `test_get_all_model_info` — 获取全部模型信息
- `test_get_model_info_by_id` — 按 ID 查询模型
- `test_get_model_info_not_found` — 不存在时抛 `NotFoundError`
- `test_create_model_config` — 创建用户模型配置
- `test_get_model_config_by_id` — 按 ID 查询配置
- `test_get_model_config_not_found` — 不存在时抛 `NotFoundError`
- `test_update_model_config` — 更新模型配置
- `test_delete_model_config` — 删除模型配置
- `test_get_public_config_empty` — 无公开配置时返回空
- `test_get_user_config` — 获取用户自己的配置

### 用户服务 `test_user_service.py`（14）
- `test_register_basic` — 基本注册
- `test_register_with_school` — 注册时关联学校
- `test_register_duplicate_email` — 重复邮箱抛 `ConflictError`
- `test_register_invalid_school` — 不存在的学校 ID 抛 `ValidationError`
- `test_login_success` — 登录成功，返回 token
- `test_login_wrong_password` — 密码错误抛 `UnauthorizedError`
- `test_login_nonexistent_user` — 用户不存在抛 `NotFoundError`
- `test_get_user_by_email` — 按邮箱查询用户
- `test_get_user_by_email_not_found` — 不存在时抛 `NotFoundError`
- `test_get_enterprise_users` — 获取企业用户（type=2）
- `test_update_avatar` — 更新头像 URL
- `test_update_avatar_not_found` — 用户不存在时抛 `NotFoundError`
- `test_get_user_school` — 获取用户所属学校
- `test_get_user_school_no_school` — 无学校时返回 None

### Bot 服务 `test_bot_service.py`（15）
- `test_check_forbidden_topics_hit` — 禁止话题命中
- `test_check_forbidden_topics_no_hit` — 未命中
- `test_check_forbidden_topics_empty_list` — 空禁止列表
- `test_check_forbidden_topics_none_list` — None 禁止列表
- `test_create_bot_private` — 创建私有 Bot
- `test_create_bot_public_by_teacher` — 教师创建公开 Bot
- `test_create_bot_public_by_student_raises` — 学生创建公开 Bot 抛 `ForbiddenError`
- `test_get_bot` — 获取 Bot 详情
- `test_get_bot_not_found` — 不存在时抛 `NotFoundError`
- `test_get_bot_private_by_other_user` — 他人私有 Bot 抛 `ForbiddenError`
- `test_list_bots` — 列出用户可见的 Bot
- `test_update_bot` — 更新 Bot
- `test_update_bot_permission_denied` — 非所有者更新抛 `ForbiddenError`
- `test_delete_bot` — 删除 Bot
- `test_delete_bot_permission_denied` — 非所有者删除抛 `ForbiddenError`

---

## 新增功能测试规范

1. 先跑测试确认基线全绿（`INTEGRATION_TESTS=1 pytest tests/integration/`）
2. 在对应的 `test_xxx_service.py` 中新增测试用例
3. 更新本文件（TEST.md）的用例清单
4. 确认全部测试通过
