import api from "../utils/api";

// 组织架构相关类型定义
export interface Organization {
  id: number;
  name: string;
  code: string;
  type: string;
  parent_id: number | null;
  school_id: number | null;
  level: number;
  path: string | null;
  description: string | null;
  status: string;
  create_at: string;
  update_at: string;
  children?: Organization[];
  members?: OrganizationMember[];
}

export interface OrganizationMember {
  id: number;
  user_id: number;
  organization_id: number;
  role: string;
  status: string;
  join_at: string;
  create_at: string;
  update_at: string;
  user_name?: string;
  user_role?: string;
  student_id?: string;
  employee_id?: string;
}

// 创建组织
export const createOrganization = async (data: {
  name: string;
  code: string;
  org_type: string;
  parent_id?: number;
  description?: string;
  school_id?: number;
}) => {
  const formData = new FormData();
  formData.append('name', data.name);
  formData.append('code', data.code);
  formData.append('org_type', data.org_type);
  if (data.parent_id) formData.append('parent_id', data.parent_id.toString());
  if (data.description) formData.append('description', data.description);
  if (data.school_id) formData.append('school_id', data.school_id.toString());
  
  const response = await api.post('/organization/create', formData);
  return response.data.data;
};

// 获取组织详情
export const getOrganization = async (
  organizationId: number,
  includeChildren: boolean = false,
  includeMembers: boolean = false
) => {
  const response = await api.get(`/organization/${organizationId}`, {
    params: { include_children: includeChildren, include_members: includeMembers }
  });
  return response.data.data;
};

// 更新组织
export const updateOrganization = async (
  organizationId: number,
  data: {
    name?: string;
    description?: string;
    status?: string;
  }
) => {
  const formData = new FormData();
  if (data.name) formData.append('name', data.name);
  if (data.description) formData.append('description', data.description);
  if (data.status) formData.append('status', data.status);
  
  const response = await api.put(`/organization/${organizationId}`, formData);
  return response.data.data;
};

// 删除组织
export const deleteOrganization = async (organizationId: number) => {
  const response = await api.delete(`/organization/${organizationId}`);
  return response.data.data;
};

// 获取子组织列表
export const getChildren = async (organizationId: number) => {
  const response = await api.get(`/organization/${organizationId}/children`);
  return response.data.data;
};

// 获取组织树
export const getOrganizationTree = async (
  organizationId: number,
  includeInactive: boolean = false
) => {
  const response = await api.get(`/organization/${organizationId}/tree`, {
    params: { include_inactive: includeInactive }
  });
  return response.data.data;
};

// 获取组织路径
export const getOrganizationPath = async (organizationId: number) => {
  const response = await api.get(`/organization/${organizationId}/path`);
  return response.data.data;
};

// 添加组织成员
export const addMember = async (
  organizationId: number,
  userId: number,
  role: string = 'member'
) => {
  const formData = new FormData();
  formData.append('user_id', userId.toString());
  formData.append('role', role);
  
  const response = await api.post(`/organization/${organizationId}/member`, formData);
  return response.data.data;
};

// 移除组织成员
export const removeMember = async (organizationId: number, userId: number) => {
  const response = await api.delete(`/organization/${organizationId}/member/${userId}`);
  return response.data.data;
};

// 获取组织成员列表
export const getMembers = async (
  organizationId: number,
  includeInactive: boolean = false
) => {
  const response = await api.get(`/organization/${organizationId}/members`, {
    params: { include_inactive: includeInactive }
  });
  return response.data.data;
};

// 获取用户所属的所有组织
export const getUserOrganizations = async (userId: number) => {
  const response = await api.get(`/organization/user/${userId}/organizations`);
  return response.data.data;
};

// 获取学校下的学院/部门列表（公开接口，注册用）
export const getDepartments = async (schoolId: number) => {
  const response = await api.get(`/organization/${schoolId}/departments`);
  return response.data.data;
};

// 获取学院下的专业列表（公开接口，注册用）
export const getMajors = async (collegeId: number) => {
  const response = await api.get(`/organization/${collegeId}/majors`);
  return response.data.data;
};

// 获取专业下的年级分布
export interface GradeDistribution {
  enrollment_year: number;
  student_count: number;
}

export const getGradeDistribution = async (majorId: number): Promise<GradeDistribution[]> => {
  const response = await api.get(`/organization/${majorId}/grade-distribution`);
  return response.data.data;
};

