<script setup lang="ts">
import { watch, ref } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'

const store = useAnalysisStore()
const visible = ref(false)
const dismissing = ref(false)

watch(() => store.error, (err) => {
  if (err) {
    visible.value = true
    dismissing.value = false
    // Auto-hide after 8 seconds
    setTimeout(() => dismiss(), 8000)
  }
})

function dismiss() {
  dismissing.value = true
  setTimeout(() => {
    visible.value = false
    store.error = ''
  }, 300)
}
</script>

<template>
  <Transition name="toast">
    <div v-if="visible && store.error" :class="['toast', { dismissing }]">
      <div class="toast-icon">!</div>
      <div class="toast-msg">{{ store.error }}</div>
      <button class="toast-close" @click="dismiss">&times;</button>
    </div>
  </Transition>
</template>

<style scoped>
.toast {
  position: fixed;
  top: 16px;
  right: 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  background: #1e1225;
  border: 1px solid rgba(248,113,113,0.4);
  border-radius: 10px;
  padding: 12px 16px;
  z-index: 1000;
  max-width: 420px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5);
  animation: slide-in 0.3s ease-out;
}

.toast.dismissing {
  animation: slide-out 0.3s ease-in forwards;
}

.toast-icon {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: rgba(248,113,113,0.2);
  color: #f87171;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-size: 14px;
}

.toast-msg {
  flex: 1;
  color: #fca5a5;
  font-size: 13px;
  line-height: 1.4;
  word-break: break-word;
}

.toast-close {
  flex-shrink: 0;
  background: none;
  border: none;
  color: #94a3b8;
  font-size: 18px;
  cursor: pointer;
  padding: 0 4px;
  line-height: 1;
}

.toast-close:hover {
  color: #e2e8f0;
}

@keyframes slide-in {
  from { transform: translateX(100%); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}

@keyframes slide-out {
  from { transform: translateX(0); opacity: 1; }
  to { transform: translateX(100%); opacity: 0; }
}
</style>
