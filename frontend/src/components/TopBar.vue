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
      // Load first analyzed file into editor
      const firstFile = result.files.find(f => !f.error)
      if (firstFile) {
        // We need to get the code from the file - for now, show summary
        store.githubResult = result
        store.activeTab = 'github'
      }

      // Fetch import graph in background
      getImportGraph({ repo_url: githubUrl.value.trim(), max_files: 20 })
        .then(graph => { store.importGraph = graph })
        .catch(() => {})
    } else {
      githubError.value = result.error || 'Analysis failed'
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
      <span class="logo-icon">&#x1F9E0;</span>
      <span class="logo-text">Why-Code-Agent</span>
      <span class="logo-tag">程序理解引擎</span>
    </div>

    <div class="actions">
      <!-- GitHub URL input -->
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
          <span v-if="githubLoading" class="animate-pulse">分析中...</span>
          <span v-else>分析仓库</span>
        </button>
        <span v-if="githubError" class="github-error">{{ githubError }}</span>
      </div>

      <div class="demo-group">
        <span class="demo-label">试试：</span>
        <button class="btn btn-secondary btn-sm" @click="emit('demo', 'fibonacci')">Fibonacci</button>
        <button class="btn btn-secondary btn-sm" @click="emit('demo', 'linked_list')">Linked List</button>
        <button class="btn btn-secondary btn-sm" @click="emit('demo', 'filter_sort')">Filter+Sort</button>
      </div>

      <button
        class="btn btn-primary"
        :disabled="(store?.loading ?? false) || !(store?.code ?? '').trim()"
        title="Ctrl+回车"
        @click="emit('analyze')"
      >
        <span v-if="(store?.loading ?? false)" class="animate-pulse">分析中...</span>
        <span v-else>分析</span>
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
  font-size: 24px;
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

.demo-group {
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

.github-group {
  display: flex;
  align-items: center;
  gap: 6px;
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
