<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'

const store = useAnalysisStore()
const editorContainer = ref<HTMLElement>()
let editor: any = null
let monaco: any = null
let lineHighlight: any = null
let disposed = false

function isAlive() {
  if (disposed || !editor || !monaco) return false
  try { return !!editor.getModel() } catch { return false }
}

onMounted(async () => {
  disposed = false
  monaco = await import('monaco-editor')

  editor = monaco.editor.create(editorContainer.value!, {
    value: store.code,
    language: 'python',
    theme: 'vs',
    fontSize: 14,
    fontFamily: "'Consolas', 'Monaco', monospace",
    lineNumbers: 'on',
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    automaticLayout: true,
    padding: { top: 12, bottom: 12 },
    renderLineHighlight: 'all',
    bracketPairColorization: { enabled: true },
    tabSize: 4,
    glyphMargin: true,
  })

  editor.onDidChangeModelContent(() => {
    store.setCode(editor.getValue())
  })
})

onUnmounted(() => {
  disposed = true
  lineHighlight = null
  if (editor) {
    try { editor.dispose() } catch {}
    editor = null
  }
  monaco = null
})

watch(() => store.code, (newCode) => {
  if (!isAlive()) return
  if (editor.getValue() !== newCode) {
    editor.setValue(newCode)
  }
})

watch(() => store.highlightedLine, (line) => {
  if (!isAlive()) return
  try {
    lineHighlight = editor.deltaDecorations(lineHighlight || [], line > 0 ? [{
      range: new monaco.Range(line, 1, line, 1),
      options: {
        isWholeLine: true,
        className: 'debugger-line',
        glyphMarginClassName: 'debugger-glyph',
      },
    }] : [])
  } catch { /* editor DOM detached */ }
})
</script>

<template>
  <div class="editor-wrapper">
    <div class="editor-header">
      <span class="editor-title">代码输入</span>
      <select v-model="store.language" class="lang-select">
        <option value="python">Python</option>
        <option value="javascript">JavaScript</option>
      </select>
    </div>
    <div ref="editorContainer" class="editor-container"></div>
  </div>
</template>

<style scoped>
.editor-wrapper {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.editor-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-dim);
}

.lang-select {
  background: var(--bg-dark);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 14px;
  outline: none;
}

.lang-select:focus {
  border-color: var(--primary);
}

.editor-container {
  flex: 1;
  min-height: 0;
}
</style>

<style>
.debugger-line {
  background: rgba(239, 68, 68, 0.18) !important;
  border-left: 3px solid #ef4444 !important;
}
.debugger-glyph {
  background: #ef4444 !important;
  width: 4px !important;
  border-radius: 2px;
  margin-left: 4px;
}
</style>
