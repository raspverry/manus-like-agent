# config.py
"""
Manusのようなエージェントシステムの設定ファイル。
"""
import os
from typing import Dict, Any

BASE_CONFIG: Dict[str, Any] = {
    "system": {
        "name": "Manus-Like Agent",
        "version": "0.2.0",
        "default_language": "ja",
        "log_level": "INFO",
        "workspace_dir": os.path.abspath("workspace"),
        "prompt_dir": os.path.abspath("prompts"),
    },
    "llm": {
        "provider": "azure",
        "model": "gpt-4o",  # Azureデプロイメント名の例
        "temperature": 0.2,
        "max_tokens": 2000,
        "context_window": 8000,
        "planning_model": "gpt-4o",
    },
    "agent_loop": {
        "max_iterations": 40,
        "max_time_seconds": 1800,
        "auto_summarize_threshold": 30,
    },
    "tools": {
        "message": {"enabled": True},
        "file": {"enabled": True, "allowed_dirs": ["/home/ubuntu"]},
        "shell": {"enabled": True, "timeout_seconds": 90, "max_output_chars": 15000},
        "browser": {
            "enabled": True,
            "timeout_seconds": 60,
            "user_agent": "Manus-Agent/0.2.0",
            "headless": True  # Playwrightをヘッドレスで使う
        },
        "info": {"enabled": True, "search_max_results": 5},
        "deploy": {"enabled": True, "allowed_ports": [3000, 5000, 8000, 8080]},
    },
    "memory": {
        "todo_file": "todo.md",
        "notes_file": "notes.md",
        "max_files_to_track": 200,
        "use_vector_memory": True,
    },
    "vector_memory": {
        "enabled": True,
        "embedding_model": "all-MiniLM-L6-v2",
        "collection_name": "agent_memory",
        "results_limit": 3,
    },
    "docker": {
        "enabled": True,
        "image_name": "manus-sandbox:latest",
        "memory_limit": "512m",
        "cpu_limit": 0.5,
    },
    "security": {
        "sandbox_enabled": True,
        "allow_sudo": True,
        "allow_network": True,
        "blocked_domains": [],
        "blocked_commands": [
            "rm -rf /",
            "shutdown",
            "reboot",
            "passwd",
        ],
    },
}

def override_from_env(config: Dict[str, Any]) -> Dict[str, Any]:
    # LLM関連
    if os.getenv("LLM_PROVIDER"):
        config["llm"]["provider"] = os.getenv("LLM_PROVIDER")
    
    if os.getenv("LLM_MODEL"):
        config["llm"]["model"] = os.getenv("LLM_MODEL")
    
    if os.getenv("LLM_TEMPERATURE"):
        config["llm"]["temperature"] = float(os.getenv("LLM_TEMPERATURE"))
    
    if os.getenv("LOG_LEVEL"):
        config["system"]["log_level"] = os.getenv("LOG_LEVEL")
    
    if os.getenv("WORKSPACE_DIR"):
        config["system"]["workspace_dir"] = os.path.abspath(os.getenv("WORKSPACE_DIR"))
    
    if os.getenv("USE_VECTOR_MEMORY") == "False":
        config["memory"]["use_vector_memory"] = False
        config["vector_memory"]["enabled"] = False
    
    if os.getenv("USE_DOCKER") == "False":
        config["docker"]["enabled"] = False
        config["security"]["sandbox_enabled"] = False
    
    if os.getenv("ALLOW_SUDO") == "False":
        config["security"]["allow_sudo"] = False
    
    if os.getenv("ALLOW_NETWORK") == "False":
        config["security"]["allow_network"] = False
    
    return config

CONFIG = override_from_env(BASE_CONFIG)
