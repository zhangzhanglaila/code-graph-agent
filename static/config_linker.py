"""Link configuration items to code lines that read them."""

from __future__ import annotations
import os
import re
from typing import Dict, List, Optional

import yaml

from core.graph import CausalGraph
from core.node import CodeNode
from core.edge_types import EdgeType


# Patterns for config access in code
_CONFIG_READERS = [
    # os.environ / os.getenv
    re.compile(r"""os\.environ\.get\(\s*['"](\w+)['"]"""),
    re.compile(r"""os\.environ\[['"](\w+)['"]\]"""),
    re.compile(r"""os\.getenv\(\s*['"](\w+)['"]"""),
    # Nested dict access: config["auth"]["token_ttl"] → auth.token_ttl
    re.compile(r"""(?:config|cfg)\[['"](\w+)['"]\]\[['"](\w+)['"]\]"""),
    # Single dict access: config["key"], config.get("key"), cfg.key
    re.compile(r"""(?:config|cfg)\[['"]([\w.]+)['"]\]"""),
    re.compile(r"""(?:config|cfg)\.get\(\s*['"]([\w.]+)['"]"""),
    re.compile(r"""cfg\.(\w+)"""),
    # YAML/JSON load patterns
    re.compile(r"""['"](\w+)['"]\s*:\s*"""),  # dict literal with key
]


class ConfigLinker:
    """Parse config files and link config items to code lines."""

    def parse_yaml(self, config_path: str) -> Dict[str, str]:
        """Parse YAML config, returning flat dotpath -> value mapping."""
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return self._flatten(data)

    def parse_json(self, config_path: str) -> Dict[str, str]:
        """Parse JSON config."""
        import json
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return self._flatten(data)

    def parse_config(self, config_path: str) -> Dict[str, str]:
        """Auto-detect format and parse."""
        if config_path.endswith((".yml", ".yaml")):
            return self.parse_yaml(config_path)
        elif config_path.endswith(".json"):
            return self.parse_json(config_path)
        return {}

    def build_graph(
        self,
        config_path: str,
        code_files: List[str],
    ) -> CausalGraph:
        """Build causal graph linking config items to code references."""
        graph = CausalGraph()
        config_items = self.parse_config(config_path)

        # Add config nodes
        for key, value in config_items.items():
            nid = CodeNode.config_id(key)
            graph.add_node(CodeNode(
                node_id=nid,
                file_path=config_path,
                line_number=0,
                code_content=f"{key} = {value}",
                node_type="CONFIG",
                semantic_label=f"config: {key}",
            ))

        # Scan code files for config references
        for code_file in code_files:
            self._scan_code_file(code_file, config_items, graph)

        return graph

    def _scan_code_file(
        self,
        file_path: str,
        config_items: Dict[str, str],
        graph: CausalGraph,
    ) -> None:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for i, line in enumerate(lines, 1):
            for pattern in _CONFIG_READERS:
                for match in pattern.finditer(line):
                    # Handle nested bracket pattern (2 groups)
                    if match.lastindex and match.lastindex >= 2:
                        key = f"{match.group(1)}.{match.group(2)}"
                    else:
                        key = match.group(1)
                    # Check if key matches any config item (exact or dotpath prefix)
                    matched_key = self._match_config_key(key, config_items)
                    if matched_key:
                        code_nid = CodeNode.make_id(file_path, i)
                        config_nid = CodeNode.config_id(matched_key)
                        if not graph.has_node(code_nid):
                            graph.add_node(CodeNode(
                                node_id=code_nid,
                                file_path=file_path,
                                line_number=i,
                                code_content=line.strip(),
                            ))
                        graph.add_edge(
                            config_nid,
                            code_nid,
                            EdgeType.CONFIG_INFLUENCE,
                        )

    def _match_config_key(self, key: str, config_items: Dict[str, str]) -> Optional[str]:
        """Match a code reference key to a config item."""
        if key in config_items:
            return key
        # Try common transformations
        lower_key = key.lower()
        for cfg_key in config_items:
            if cfg_key.lower().replace(".", "_") == lower_key:
                return cfg_key
            if cfg_key.lower() == lower_key:
                return cfg_key
        return None

    def _flatten(self, data: dict, prefix: str = "") -> Dict[str, str]:
        """Flatten nested dict to dotpath keys."""
        items: Dict[str, str] = {}
        for k, v in data.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                items.update(self._flatten(v, full_key))
            else:
                items[full_key] = str(v)
        return items
