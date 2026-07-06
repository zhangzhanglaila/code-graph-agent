<script setup lang="ts">
import { ref } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'
import { analyzeGitHubRepo, getImportGraph } from '../api/analysis'

const store = useAnalysisStore()
const emit = defineEmits<{
  analyze: []
  demo: [name: string]
}>()

const githubUrl = ref('')
const githubLoading = ref(false)
const githubError = ref('')

async function analyzeGithub() {
  if (!githubUrl.value.trim()) return

  githubLoading.value = true
  githubError.value = ''

  try {
    const result = await analyzeGitHubRepo({
      repo_url: githubUrl.value.trim(),
      max_files: 5,
    })

    if (result.success && result.files) {
      const firstFile = result.files.find(f => !f.error)
      if (firstFile) {
        store.githubResult = result
        store.activeTab = 'github'
      }

      getImportGraph({ repo_url: githubUrl.value.trim(), max_files: 20 })
        .then(graph => { store.importGraph = graph })
        .catch(() => {})
    } else {
      githubError.value = result.error || '仓库分析失败'
    }
  } catch (e: any) {
    githubError.value = e.message
  } finally {
    githubLoading.value = false
  }
}
</script>

<template>
  <div class="topbar">
    <div class="logo">
      <span class="logo-icon">Code</span>
      <span class="logo-text">Why-Code-Agent</span>
      <span class="logo-tag">代码理解工作台</span>
    </div>

    <div class="actions">
      <div class="github-group">
        <input
          v-model="githubUrl"
          type="text"
          placeholder="GitHub 仓库 URL"
          class="github-input"
          @keyup.enter="analyzeGithub"
        />
        <button
          class="btn btn-secondary btn-sm"
          :disabled="githubLoading || !githubUrl.trim()"
          @click="analyzeGithub"
        >
          {{ githubLoading ? '分析中...' : '分析仓库' }}
        </button>
        <span v-if="githubError" class="github-error">{{ githubError }}</span>
      </div>

      <div class="demo-group">
        <span class="demo-label">示例</span>
        <button class="btn btn-secondary btn-sm" @click="emit('demo', 'fibonacci')">Fibonacci</button>
        <button class="btn btn-secondary btn-sm" @click="emit('demo', 'linked_list')">Linked List</button>
        <button class="btn btn-secondary btn-sm" @click="emit('demo', 'filter_sort')">Filter+Sort</button>
      </div>

      <button
        class="btn btn-primary"
        :disabled="store.loading || !store.code.trim()"
        title="Ctrl+Enter"
        @click="emit('analyze')"
      >
        {{ store.loading ? '分析中...' : '分析代码' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 20px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 260px;
}

.logo-icon {
  padding: 3px 7px;
  border-radius: 5px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 12px;
  font-weight: 900;
}

.logo-text {
  font-size: 18px;
  font-weight: 700;
  color: var(--primary);
}

.logo-tag {
  font-size: 14px;
  color: var(--text-dim);
  margin-left: 4px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-content: flex-end;
  min-width: 0;
  flex-wrap: wrap;
}

.demo-group,
.github-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.demo-label {
  font-size: 14px;
  color: var(--text-dim);
}

.btn-sm {
  padding: 4px 12px;
  font-size: 14px;
}

.github-input {
  padding: 6px 10px;
  font-size: 14px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-elevated);
  color: var(--text);
  width: min(260px, 28vw);
  min-width: 190px;
}

.github-input:focus {
  outline: none;
  border-color: var(--accent);
}

.github-error {
  font-size: 14px;
  color: var(--error);
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1100px) {
  .topbar {
    align-items: flex-start;
  }

  .actions {
    justify-content: flex-start;
  }

  .github-input {
    width: 260px;
  }
}
</style>
