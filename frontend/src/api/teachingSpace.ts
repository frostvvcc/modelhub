import api from "../utils/api";

export interface TeachingSpace {
  id: number;
  space_code: string | null;
  name: string;
  description: string | null;
  teacher_id: number;
  teacher_name: string | null;
  school_id: number | null;
  status: string;
  created_at: string;
  updated_at: string;
  major_count?: number;
  resource_count?: number;
  teacher_college_id?: number;
  teacher_college_name?: string;
  member_count?: number;
}

export interface SpaceMajor {
  id: number;
  space_id: number;
  major_id: number;
  major_name: string | null;
  major_code: string | null;
  enrollment_year: number | null;
  created_at: string;
}

export interface SpaceResources {
  vector_dbs: any[];
  bots: any[];
}

export const createTeachingSpace = async (name: string, description?: string): Promise<TeachingSpace> => {
  const formData = new FormData();
  formData.append('name', name);
  if (description) formData.append('description', description);
  const response = await api.post('/teaching-space', formData);
  return response.data.data;
};

export const listTeachingSpaces = async (): Promise<TeachingSpace[]> => {
  const response = await api.get('/teaching-space');
  return response.data.data;
};

export const getTeachingSpace = async (spaceId: number): Promise<TeachingSpace> => {
  const response = await api.get(`/teaching-space/${spaceId}`);
  return response.data.data;
};

export const updateTeachingSpace = async (spaceId: number, data: { name?: string; description?: string; space_status?: string }) => {
  const formData = new FormData();
  if (data.name) formData.append('name', data.name);
  if (data.description !== undefined) formData.append('description', data.description);
  if (data.space_status) formData.append('space_status', data.space_status);
  const response = await api.put(`/teaching-space/${spaceId}`, formData);
  return response.data.data;
};

export const deleteTeachingSpace = async (spaceId: number) => {
  const response = await api.delete(`/teaching-space/${spaceId}`);
  return response.data.data;
};

export const bindMajor = async (spaceId: number, majorId: number, enrollmentYear?: number | null): Promise<SpaceMajor> => {
  const formData = new FormData();
  formData.append('major_id', majorId.toString());
  if (enrollmentYear != null) formData.append('enrollment_year', enrollmentYear.toString());
  const response = await api.post(`/teaching-space/${spaceId}/bindMajor`, formData);
  return response.data.data;
};

export const unbindMajor = async (spaceId: number, majorId: number, enrollmentYear?: number | null) => {
  const params: Record<string, any> = {};
  if (enrollmentYear != null) params.enrollment_year = enrollmentYear;
  const response = await api.delete(`/teaching-space/${spaceId}/unbindMajor/${majorId}`, { params });
  return response.data.data;
};

export const getSpaceMajors = async (spaceId: number): Promise<SpaceMajor[]> => {
  const response = await api.get(`/teaching-space/${spaceId}/majors`);
  return response.data.data;
};

export const getSpaceStudents = async (spaceId: number): Promise<any[]> => {
  const response = await api.get(`/teaching-space/${spaceId}/students`);
  return response.data.data;
};

export const addSpaceStudent = async (spaceId: number, studentId: number) => {
  const formData = new FormData();
  formData.append('student_id', studentId.toString());
  const response = await api.post(`/teaching-space/${spaceId}/students`, formData);
  return response.data.data;
};

export const removeSpaceStudent = async (spaceId: number, studentId: number) => {
  const response = await api.delete(`/teaching-space/${spaceId}/students/${studentId}`);
  return response.data.data;
};

export const publishResource = async (spaceId: number, resourceType: string, resourceId: number) => {
  const formData = new FormData();
  formData.append('resource_type', resourceType);
  formData.append('resource_id', resourceId.toString());
  const response = await api.post(`/teaching-space/${spaceId}/publish`, formData);
  return response.data.data;
};

export const unpublishResource = async (spaceId: number, resourceType: string, resourceId: number) => {
  const formData = new FormData();
  formData.append('resource_type', resourceType);
  formData.append('resource_id', resourceId.toString());
  const response = await api.delete(`/teaching-space/${spaceId}/unpublish`, { data: formData });
  return response.data.data;
};

export const getSpaceResources = async (spaceId: number): Promise<SpaceResources> => {
  const response = await api.get(`/teaching-space/${spaceId}/resources`);
  return response.data.data;
};

export const listAllTeachingSpaces = async (organizationId?: number): Promise<TeachingSpace[]> => {
  const params: Record<string, any> = {};
  if (organizationId) params.organization_id = organizationId;
  const response = await api.get('/teaching-space/admin/all', { params });
  return response.data.data;
};

export const getSpacesByMajor = async (majorId: number): Promise<TeachingSpace[]> => {
  const response = await api.get(`/teaching-space/by-major/${majorId}`);
  return response.data.data;
};
