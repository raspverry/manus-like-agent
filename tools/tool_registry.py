# tools/tool_registry.py
"""
ツールレジストリ：ツールを登録・取得・実行するクラス。
"""
import logging
import json
import importlib
import functools
from typing import Dict, Any, Callable, Optional

logger = logging.getLogger(__name__)

def tool(name: str, description: str, parameters: Dict[str, Any]):
    """
    ツール関数用デコレータ。関数に'tool_spec'属性を追加し、ToolRegistryで自動登録できるようにします。
    
    Args:
        name: ツールの名前
        description: ツールの説明
        parameters: JSONスキーマ形式のパラメータ定義
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        
        # 関数にツール仕様を追加
        wrapper.tool_spec = {
            "name": name,
            "description": description,
            "parameters": parameters
        }
        
        return wrapper
    
    return decorator

class ToolRegistry:
    def __init__(self):
        self.tools = {}
        self.tool_specs = {}
    
    def register_tool(self, name: str, func: Callable, spec: Dict[str, Any]):
        self.tools[name] = func
        self.tool_specs[name] = spec
        logger.info(f"ツール登録: {name}")
    
    def register_tools_from_module(self, module_name: str):
        try:
            mod = importlib.import_module(module_name)
            for attr_name in dir(mod):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(mod, attr_name)
                if callable(attr) and hasattr(attr, "tool_spec"):
                    self.register_tool(attr.tool_spec["name"], attr, attr.tool_spec)
            logger.info(f"モジュール '{module_name}' からツールを登録しました")
        except Exception as e:
            logger.error(f"ツール登録中エラー: {str(e)}")
    
    def get_tool_names(self):
        return list(self.tools.keys())
    
    def get_tool_spec(self, name: str) -> Optional[Dict[str, Any]]:
        return self.tool_specs.get(name)
    
    def execute_tool(self, name: str, params: Dict[str, Any]) -> Any:
        if name not in self.tools:
            raise ValueError(f"ツール '{name}' は登録されていません")
        func = self.tools[name]
        return func(**params)
