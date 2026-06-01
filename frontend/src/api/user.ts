import api from "../utils/api";
export const getConfigurators = async () => {
    const response = await api.get('/user/enterprise')
    return response.data.data
}

export const getUserInfo = async () => {
    const response = await api.get('/user/info')
    return response.data.data
}
export const uploadAvatar = async (formData: FormData) => {
  const res = await api.put('/user/avatar', formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  });
  return res.data.data;
};

export const updateProfile = async (data: {
  name?: string;
  describe?: string;
  phone?: string;
  student_id?: string;
  employee_id?: string;
}) => {
  const res = await api.put('/user/profile', data);
  return res.data.data;
};

export const changePassword = async (oldPassword: string, newPassword: string) => {
  const res = await api.put('/user/password', {
    old_password: oldPassword,
    new_password: newPassword,
  });
  return res.data.data;
};