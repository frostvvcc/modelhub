# 性能优化指南

## 后端性能优化

### 1. 缓存策略

#### 权限检查缓存
- **位置**: `app/services/permission_service.py`
- **缓存时间**: 5分钟
- **缓存键**: `permission:check_permission:{hash}`
- **说明**: 权限检查结果会被缓存，减少数据库查询

#### 组织树缓存
- **位置**: `app/services/organization_service.py`
- **缓存时间**: 10分钟
- **缓存键**: `org_tree:get_organization_tree:{hash}`
- **说明**: 组织树结构会被缓存，减少递归查询

#### 清除缓存
当组织或权限发生变化时，需要清除相关缓存：
```python
from app.utils.cache import clear_cache

# 清除组织相关缓存
clear_cache("org_tree:*")

# 清除权限相关缓存
clear_cache("permission:*")
```

### 2. 数据库查询优化

#### 索引优化
已为以下字段添加索引：
- `organization.parent_id`
- `organization.school_id`
- `organization.path`
- `user.school_id`
- `vector_db.organization_id`
- `vector_db.school_id`
- `conversation.organization_id`

#### 查询优化建议
1. **使用selectinload预加载关联数据**
   ```python
   stmt = select(Organization).options(selectinload(Organization.children))
   ```

2. **批量查询替代循环查询**
   ```python
   # 不好
   for org_id in org_ids:
       org = await get_organization(org_id)
   
   # 好
   orgs = await get_organizations(org_ids)
   ```

3. **使用分页查询**
   ```python
   stmt = select(User).limit(20).offset(0)
   ```

### 3. Redis连接池优化

已使用连接池管理Redis连接，避免频繁创建连接：
- **位置**: `app/utils/optimized_redis.py`
- **配置**: 连接池大小、超时时间等

### 4. 异步操作优化

- 所有数据库操作使用异步SQLAlchemy
- 使用`asyncio.gather`并发执行独立操作
- 避免在异步函数中使用同步阻塞操作

## 前端性能优化

### 1. 组件懒加载

使用Vue Router的懒加载：
```typescript
const OrganizationView = () => import('@/views/OrganizationView.vue')
```

### 2. 数据缓存

在Pinia Store中缓存常用数据：
- 用户信息
- 组织列表
- 权限列表

### 3. 防抖和节流

对频繁触发的操作使用防抖：
```typescript
import { debounce } from 'lodash-es'

const debouncedSearch = debounce(searchFunction, 300)
```

### 4. 虚拟滚动

对于长列表，使用虚拟滚动：
- Element Plus的`el-table`支持虚拟滚动
- 或使用`vue-virtual-scroller`

### 5. 图片优化

- 使用WebP格式
- 实现懒加载
- 压缩图片大小

### 6. 代码分割

使用Vite的代码分割：
```typescript
// vite.config.ts
export default {
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'element-plus': ['element-plus'],
          'vue-vendor': ['vue', 'vue-router', 'pinia']
        }
      }
    }
  }
}
```

## 监控和性能分析

### 1. 日志记录

- 记录慢查询（>1秒）
- 记录缓存命中率
- 记录API响应时间

### 2. 性能指标

监控以下指标：
- API响应时间
- 数据库查询时间
- 缓存命中率
- 前端页面加载时间

### 3. 性能测试

使用以下工具进行性能测试：
- **后端**: `locust`、`pytest-benchmark`
- **前端**: Chrome DevTools Performance、Lighthouse

## 优化建议

1. **定期清理缓存**: 设置缓存过期时间，避免内存泄漏
2. **数据库连接池**: 合理配置连接池大小
3. **CDN加速**: 静态资源使用CDN
4. **Gzip压缩**: 启用HTTP压缩
5. **HTTP/2**: 使用HTTP/2协议提升性能

