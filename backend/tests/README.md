# 测试文档

## 测试结构

```
tests/
├── __init__.py
├── conftest.py          # 测试配置和fixtures
├── unit/                # 单元测试
│   ├── test_organization_service.py
│   └── test_permission_service.py
└── integration/         # 集成测试
    └── test_organization_api.py
```

## 运行测试

### 安装测试依赖

```bash
pip install pytest pytest-asyncio httpx aiosqlite
```

### 运行所有测试

```bash
pytest
```

### 运行单元测试

```bash
pytest tests/unit/
```

### 运行集成测试

```bash
pytest tests/integration/
```

### 运行特定测试文件

```bash
pytest tests/unit/test_organization_service.py
```

### 生成测试覆盖率报告

```bash
pytest --cov=app --cov-report=html
```

## 测试说明

- **单元测试**: 测试服务层和Mapper层的业务逻辑
- **集成测试**: 测试API端点的完整流程
- **测试数据库**: 使用内存SQLite数据库，每个测试独立运行
- **Fixtures**: 提供测试用户、组织、角色等测试数据

