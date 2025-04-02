# core/enhanced_memory.py
"""
統合メモリモジュール。

このモジュールは従来のファイルベースメモリとFAISSベクトルデータベースを
組み合わせて、より強力なメモリと検索機能を提供します。
"""
import os
import logging
import json
import time
from typing import Dict, List, Any, Optional

from core.memory import Memory

logger = logging.getLogger(__name__)

class EnhancedMemory(Memory):
    """
    従来のMemoryクラスとFAISSMemoryを組み合わせた拡張メモリクラス。
    
    このクラスは両方のメモリシステムを使用して、ファイルの追跡と
    セマンティック検索の両方の機能を提供します。
    """
    
    def __init__(self, workspace_dir: str):
        """
        拡張メモリを初期化します。
        
        Args:
            workspace_dir: 作業ディレクトリのパス
        """
        # 従来のメモリを初期化
        super().__init__(workspace_dir=workspace_dir)
        
        # ベクトルメモリを初期化
        try:
            # ChromaDBの代わりにFAISSベースのメモリを使用
            from .faiss_memory import FAISSMemory
            self.vector_memory = FAISSMemory(workspace_dir=workspace_dir)
            self._vector_memory_available = True
            logger.info("FAISSベクトルメモリシステムが初期化されました")
        except ImportError as e:
            # FAISSが利用できない場合は警告を表示
            logger.warning(f"ベクトルメモリが利用できません: {str(e)}")
            logger.warning("基本的なメモリのみを使用します")
            self._vector_memory_available = False
    
    def update_from_observation(self, tool_call: Dict[str, Any], result: Any) -> None:
        """
        ツール実行の観察に基づいてメモリを更新します。
        
        Args:
            tool_call: 実行されたツール呼び出し
            result: ツール実行の結果
        """
        # 従来のメモリを更新
        super().update_from_observation(tool_call, result)
        
        # ベクトルメモリが利用可能な場合は更新
        if not self._vector_memory_available:
            return
            
        tool_name = tool_call.get("name", "")
        params = tool_call.get("parameters", {})
        
        # ファイル操作から知識を獲得
        if tool_name == "file_write":
            file_path = params.get("file", "")
            content = params.get("content", "")
            
            if file_path and content and len(content) > 10:
                # メモリに追加
                self.vector_memory.add_document(
                    text=content,
                    source=f"file:{os.path.basename(file_path)}",
                    metadata={
                        "file_path": file_path,
                        "operation": "write"
                    }
                )
        
        # ブラウザや検索結果から知識を獲得
        elif tool_name == "browser_navigate" and isinstance(result, str) and len(result) > 100:
            url = params.get("url", "")
            
            if url:
                self.vector_memory.add_document(
                    text=result,
                    source=f"web:{url}",
                    metadata={
                        "url": url,
                        "operation": "navigate"
                    }
                )
        
        elif tool_name == "info_search_web" and isinstance(result, str) and len(result) > 100:
            query = params.get("query", "")
            
            if query:
                self.vector_memory.add_document(
                    text=result,
                    source=f"search:{query}",
                    metadata={
                        "query": query,
                        "operation": "search"
                    }
                )
    
    def get_relevant_state(self) -> str:
        """
        現在のメモリ状態の関連する要約を取得します。
        
        Returns:
            現在のメモリ状態の文字列記述
        """
        # 従来のメモリ状態を取得
        traditional_state = super().get_relevant_state()
        
        return traditional_state
    
    def get_relevant_knowledge(self, query: str, limit: int = 3) -> str:
        """
        クエリに関連する知識を取得します。
        
        Args:
            query: 検索クエリ
            limit: 返す結果の最大数
            
        Returns:
            関連知識のテキスト
        """
        if not self._vector_memory_available:
            return "ベクトルメモリシステムが利用できないため、関連知識を取得できません。"
            
        return self.vector_memory.get_relevant_context(query, limit)
    
    def add_user_interaction(self, user_message: str, agent_response: str) -> None:
        """
        ユーザーとエージェントの対話をメモリに追加します。
        
        Args:
            user_message: ユーザーのメッセージ
            agent_response: エージェントの応答
        """
        if self._vector_memory_available:
            self.vector_memory.add_conversation(user_message, agent_response)
