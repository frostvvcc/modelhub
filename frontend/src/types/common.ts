import type { FormItemRule } from 'element-plus'

/** Element Plus 表单验证器参数类型 */
export type FormValidator = (
  rule: FormItemRule,
  value: string,
  callback: (error?: Error) => void,
) => void

/** 树形节点通用接口 */
export interface TreeNode {
  id: number | string
  label?: string
  name?: string
  children?: TreeNode[]
  [key: string]: unknown
}

/** 文档树节点 */
export interface DocumentTreeNode {
  id: number
  name: string
  type: 'folder' | 'file'
  document_id?: number
  status?: string
  file_size?: number
  children?: DocumentTreeNode[]
}

/** 通用分页参数 */
export interface PaginationParams {
  page: number
  pageSize: number
  total: number
}

/** API 错误响应 */
export interface ApiError {
  message: string
  code?: string | number
  detail?: string
}

/** 组织信息 */
export interface OrganizationNode {
  id: number
  name: string
  type: string
  parent_id?: number | null
  path?: string
  children?: OrganizationNode[]
  member_count?: number
}

/** 学生信息 */
export interface StudentInfo {
  id: number
  name: string
  student_id?: string
  email?: string
  enrollment_year?: number
}

/** 权限角色 */
export interface RoleInfo {
  id: number
  name: string
  code: string
  scope?: string
  description?: string
}

/** 权限信息 */
export interface PermissionInfo {
  id: number
  code: string
  name: string
  resource?: string
  action?: string
}
