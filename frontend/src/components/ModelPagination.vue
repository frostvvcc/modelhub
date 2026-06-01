<script setup lang="ts">
defineProps<{
  currentPage: number;
  pageSize: number;
  total: number;
}>();

const emit = defineEmits(['page-change', 'size-change']);

const handlePageChange = (newPage: number) => {
  emit('page-change', newPage);
};

const handleSizeChange = (newSize: number) => {
  emit('size-change', newSize);
};
</script>

<template>
  <div class="pagination-container">
    <ElPagination
      :size="'large'"
      :current-page="currentPage"
      :page-size="pageSize"
      :total="total"
      :page-sizes="[10, 16, 20, 50, 100]"
      layout="total, sizes, prev, pager, next, jumper"
      background
      @current-change="handlePageChange"
      @size-change="handleSizeChange"
    />
  </div>
</template>

<style scoped>
.pagination-container {
  margin-top: 4rem;
  display: flex;
  justify-content: center;
}
</style>