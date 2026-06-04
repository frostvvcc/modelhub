import api from "../utils/api";

// 权限管理相关类型定义
export interface Role {
  id: number;
  name: string;
  code: string;
  description: string | null;
  level: string;
  is_system: boolean;
  school_id: number | null;
  create_at: string;
  update_at: string;
  permissions?: Permission[];
}

export interface Permission {
  id: number;
  name: string;
  code: string;
  description: string | null;
  resource: string;
  action: string;
  create_at: string;
  update_at: string;
}

export interface UserRole {
  id: number;
  user_id: number;
  role_id: number;
  organization_id: number | null;
  scope: string | null;
  is_active: boolean;
  create_at: string;
  update_at: string;
}

// 检查用户权限
export const checkPermission = async (
  permissionCode: string,
  organizationId?: number
) => {
  // 验证权限代码不为空
  if (!permissionCode || permissionCode.trim() === '') {
    console.warn('权限检查：permissionCode 为空，返回 false');
    return false;
  }
  
  try {
    const formData = new FormData();
    formData.append('permission_code', permissionCode);
    if (organizationId) {
      formData.append('organization_id', organizationId.toString());
    }
    
    // FormData 会自动设置正确的 Content-Type
    const response = await api.post('/permission/check', formData);
    return response.data.data?.has_permission || false;
  } catch (error: unknown) {
    // 如果是 422 错误，可能是参数验证失败
    if (error.response?.status === 422) {
      console.warn('权限检查失败：参数验证错误', error.response?.data);
      return false;
    }
    console.error('权限检查失败:', error);
    return false;
  }
};

// 获取用户所有权限
export const getUserPermissions = async (
  userId: number,
  organizationId?: number
) => {
  const response = await api.get(`/permission/user/${userId}/permissions`, {
    params: organizationId ? { organization_id: organizationId } : {}
  });
  return response.data.data;
};

// 获取用户所有角色
export const getUserRoles = async (
  userId: number,
  organizationId?: number
) => {
  const response = await api.get(`/permission/user/${userId}/roles`, {
    params: organizationId ? { organization_id: organizationId } : {}
  });
  return response.data.data;
};

// 创建角色
export const createRole = async (data: {
  name: string;
  code: string;
  description?: string;
  level?: string;
  is_system?: boolean;
  school_id?: number;
}) => {
  const formData = new FormData();
  formData.append('name', data.name);
  formData.append('code', data.code);
  if (data.description) formData.append('description', data.description);
  formData.append('level', data.level || 'class');
  formData.append('is_system', (data.is_system || false).toString());
  if (data.school_id) formData.append('school_id', data.school_id.toString());
  
  const response = await api.post('/permission/role', formData);
  return response.data.data;
};

// 获取角色列表
export const getRoles = async (schoolId?: number, includeSystem: boolean = true) => {
  const response = await api.get('/permission/roles', {
    params: {
      school_id: schoolId,
      include_system: includeSystem
    }
  });
  return response.data.data;
};

// 获取所有权限
export const getAllPermissions = async () => {
  const response = await api.get('/permission/permissions');
  return response.data.data;
};

// 获取角色的所有权限
export const getRolePermissions = async (roleId: number) => {
  const response = await api.get(`/permission/role/${roleId}/permissions`);
  return response.data.data;
};

// 为角色分配权限
export const assignPermissionToRole = async (roleId: number, permissionId: number) => {
  const formData = new FormData();
  formData.append('permission_id', permissionId.toString());
  
  const response = await api.post(`/permission/role/${roleId}/permission`, formData);
  return response.data.data;
};

// 为用户分配角色
export const assignRoleToUser = async (
  userId: number,
  roleId: number,
  organizationId?: number,
  scope?: string
) => {
  const formData = new FormData();
  formData.append('role_id', roleId.toString());
  if (organizationId) formData.append('organization_id', organizationId.toString());
  if (scope) formData.append('scope', scope);
  
  const response = await api.post(`/permission/user/${userId}/role`, formData);
  return response.data.data;
};

// 更新角色
export const updateRole = async (
  roleId: number,
  data: {
    name?: string;
    description?: string;
    level?: string;
  }
) => {
  const formData = new FormData();
  if (data.name) formData.append('name', data.name);
  if (data.description) formData.append('description', data.description);
  if (data.level) formData.append('level', data.level);
  
  const response = await api.put(`/permission/role/${roleId}`, formData);
  return response.data.data;
};

// 删除角色
export const deleteRole = async (roleId: number) => {
  const response = await api.delete(`/permission/role/${roleId}`);
  return response.data.data;
};

// 移除角色权限
export const removePermissionFromRole = async (roleId: number, permissionId: number) => {
  const response = await api.delete(`/permission/role/${roleId}/permission/${permissionId}`);
  return response.data.data;
};

// 检查组织访问权限
export const checkOrganizationAccess = async (
  organizationId: number,
  permissionCode: string
) => {
  const formData = new FormData();
  formData.append('permission_code', permissionCode);
  
  const response = await api.post(`/permission/organization/${organizationId}/access`, formData);
  return response.data.data.has_access;
};

