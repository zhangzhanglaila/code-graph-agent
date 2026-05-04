<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'

const store = useAnalysisStore()
const graphContainer = ref<HTMLElement>()

const EDGE_COLORS: Record<string, string> = {
  DATA_DEPENDENCY: '#2196F3',
  CALL_RELATION: '#4CAF50',
  CONFIG_INFLUENCE: '#FF9800',
  RUNTIME_TRACE: '#E91E63',
  THROWS: '#F44336',
  CONTROL_FLOW: '#9C27B0',
}

const NODE_COLORS: Record<string, string> = {
  CODE: '#90CAF9',
  CONFIG: '#FFE082',
  ERROR: '#EF9A9A',
  ENTRY: '#A5D6A7',
}

onMounted(() => {
  if (store.analyzeResult) renderGraph()
})

watch(() => store.analyzeResult, () => {
  if (store.analyzeResult) renderGraph()
})

async function renderGraph() {
  if (!graphContainer.value || !store.analyzeResult) return

  const cytoscape = (await import('cytoscape')).default
  const dagre = (await import('cytoscape-dagre')).default
  cytoscape.use(dagre)
  const data = store.analyzeResult

  const elements: any[] = []

  data.nodes.forEach((n: any) => {
    elements.push({
      data: {
        id: n.node_id,
        label: `${n.file_path.split('/').pop()}:${n.line_number}`,
        type: n.node_type,
        code: n.code_content,
        semantic: n.semantic_label,
      },
    })
  })

  data.edges.forEach((e: any) => {
    elements.push({
      data: {
        source: e.source,
        target: e.target,
        edgeType: e.type,
      },
    })
  })

  cytoscape({
    container: graphContainer.value,
    elements,
    style: [
      {
        selector: 'node',
        style: {
          'background-color': (ele: any) => NODE_COLORS[ele.data('type')] || '#90CAF9',
          'border-color': (ele: any) => NODE_COLORS[ele.data('type')] || '#90CAF9',
          'border-width': 2,
          'label': 'data(label)',
          'font-size': '10px',
          'color': '#e2e8f0',
          'text-outline-color': '#0f172a',
          'text-outline-width': 2,
          'width': 30,
          'height': 30,
          'text-valign': 'bottom',
          'text-margin-y': 5,
        } as any,
      },
      {
        selector: 'node[type="ERROR"]',
        style: {
          'background-color': '#EF9A9A',
          'border-color': '#C62828',
          'border-width': 3,
          'width': 40,
          'height': 40,
        } as any,
      },
      {
        selector: 'edge',
        style: {
          'width': 1.5,
          'line-color': (ele: any) => EDGE_COLORS[ele.data('edgeType')] || '#999',
          'target-arrow-color': (ele: any) => EDGE_COLORS[ele.data('edgeType')] || '#999',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'arrow-scale': 0.8,
        } as any,
      },
      {
        selector: 'edge[edgeType="CONFIG_INFLUENCE"], edge[edgeType="THROWS"]',
        style: {
          'line-style': 'dashed',
        } as any,
      },
    ],
    layout: {
      name: 'dagre',
      rankDir: 'BT',
      spacingFactor: 1.2,
    } as any,
    userZoomingEnabled: true,
    userPanningEnabled: true,
  })
}
</script>

<template>
  <div class="graph-panel animate-slide-up">
    <!-- Legend -->
    <div class="legend">
      <span v-for="(color, type) in EDGE_COLORS" :key="type" class="legend-item">
        <span class="legend-line" :style="{ background: color, borderStyle: (type === 'CONFIG_INFLUENCE' || type === 'THROWS') ? 'dashed' : 'solid' }"></span>
        {{ type.replace('_', ' ') }}
      </span>
    </div>

    <!-- Graph -->
    <div ref="graphContainer" class="graph-container"></div>

    <!-- Stats -->
    <div v-if="store.analyzeResult" class="stats">
      Nodes: {{ store.analyzeResult.stats.nodes }} |
      Edges: {{ store.analyzeResult.stats.edges }}
      <span v-for="(count, etype) in store.analyzeResult.stats.edge_types" :key="etype">
        | {{ etype }}: {{ count }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.graph-panel { display: flex; flex-direction: column; height: 100%; }

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 8px 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 8px;
}

.legend-item { display: flex; align-items: center; gap: 4px; font-size: 10px; color: var(--text-dim); }

.legend-line {
  width: 16px;
  height: 2px;
  border-top: 2px solid;
}

.graph-container {
  flex: 1;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  min-height: 400px;
}

.stats {
  font-size: 11px;
  color: var(--text-muted);
  padding: 6px 0;
  text-align: center;
}
</style>
