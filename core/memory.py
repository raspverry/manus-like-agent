# core/memory.py
"""
エージェントのメモリ機能。ファイル操作の記録やタスク進捗を追跡。
"""
import logging
import os
from typing import Dict, Any

logger = logging.getLogger(__name__)

class Memory:
    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir
        self.file_registry = {}
        self.task_progress = {}
        self.variables = {}
    
    def update_from_observation(self, tool_call: Dict[str, Any], result: Any):
        # ファイル書き込みツールやtodoへの書き込み等を追跡
        name = tool_call.get("name", "")
        params = tool_call.get("parameters", {})
        
        if name == "file_write":
            file_path = params.get("file", "")
            if file_path:
                self.file_registry[file_path] = "written"
        
        if name == "file_str_replace":
            file_path = params.get("file", "")
            if file_path:
                self.file_registry[file_path] = "str_replaced"
    
    def get_file_info(self, file_path: str):
        return self.file_registry.get(file_path, None)
