import { ElMessageBox } from 'element-plus';

export const confirmAction = (message: string, title = '确认操作') => {
  return ElMessageBox.confirm(message, title, {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning'
  });
};