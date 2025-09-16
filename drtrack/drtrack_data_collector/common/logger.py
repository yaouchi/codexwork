"""
DrTrack ログシステム

構造化JSON形式でのログ出力とGCSアップロード機能
"""

import json
import logging
import datetime
import pytz
from typing import List, Dict, Any, Optional


class UnifiedLogger:
    """DrTrack ログシステム"""
    
    def __init__(self, system_name: str, task_index: int, task_count: int):
        self.system_name = system_name
        self.task_index = task_index
        self.task_count = task_count
        self.jst = pytz.timezone('Asia/Tokyo')
        self.log_messages = []
        
        # Pythonロガーの設定
        self.python_logger = logging.getLogger(system_name)
        self.python_logger.setLevel(logging.INFO)
        
        # コンソールハンドラー
        if not self.python_logger.handlers:
            console_handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            console_handler.setFormatter(formatter)
            self.python_logger.addHandler(console_handler)
    
    def get_jst_now_str(self, format_str: str = "%Y%m%d_%H%M%S") -> str:
        """JST時刻の文字列を取得"""
        return datetime.datetime.now(self.jst).strftime(format_str)
    
    def get_jst_now_iso(self) -> str:
        """JST時刻のISO形式文字列を取得（TSV出力用）"""
        now = datetime.datetime.now(self.jst)
        return now.strftime("%Y-%m-%dT%H:%M:%S+09:00")
    
    def _create_log_entry(self, message: str, level: str, **context) -> Dict[str, Any]:
        """ログエントリーを作成"""
        timestamp = self.get_jst_now_str("%Y-%m-%d %H:%M:%S")
        
        entry = {
            "timestamp": timestamp,
            "system": self.system_name,
            "task_index": self.task_index,
            "task_count": self.task_count,
            "level": level,
            "message": message
        }
        
        # コンテキスト情報があれば追加
        if context:
            entry.update(context)
        
        return entry
    
    def log(self, message: str, level: str = "INFO", **context):
        """基本ログ出力"""
        entry = self._create_log_entry(message, level, **context)
        
        # 構造化ログとして保存
        self.log_messages.append(entry)
        
        # コンソールにも出力
        log_level = getattr(logging, level.upper(), logging.INFO)
        self.python_logger.log(log_level, message)
    
    def log_success(self, message: str, **context):
        """成功ログ"""
        self.log(message, "SUCCESS", **context)
    
    def log_info(self, message: str, **context):
        """情報ログ"""
        self.log(message, "INFO", **context)
    
    def log_warning(self, message: str, **context):
        """警告ログ"""
        self.log(message, "WARNING", **context)
    
    def log_error(self, message: str, error: Optional[Exception] = None, **context):
        """エラーログ"""
        if error:
            context.update({
                "error_type": type(error).__name__,
                "error_message": str(error)
            })
        self.log(message, "ERROR", **context)
    
    def log_ai_failure(self, url: str, failure_reason: str, 
                      error_details: str, context: Dict[str, Any]):
        """AI処理失敗の詳細ログ（新規追加）"""
        enhanced_context = {
            **context,
            'failure_reason': failure_reason,
            'error_details': error_details
        }
        self.log_error(f"AI処理失敗: {url} - {failure_reason}", **enhanced_context)
    
    def log_progress(self, current: int, total: int, item_type: str = "item", **context):
        """進捗ログ"""
        percentage = (current / total * 100) if total > 0 else 0
        message = f"進捗: {current}/{total} {item_type} ({percentage:.1f}%)"
        
        context.update({
            "current": current,
            "total": total,
            "percentage": percentage,
            "item_type": item_type
        })
        
        self.log(message, "PROGRESS", **context)
    
    def log_statistics(self, stats: Dict[str, Any]):
        """統計ログ"""
        message = "処理統計: " + ", ".join([f"{k}={v}" for k, v in stats.items()])
        self.log(message, "STATISTICS", **stats)
    
    def export_logs_as_json(self) -> str:
        """ログをJSON形式で出力"""
        return "\n".join([json.dumps(entry, ensure_ascii=False) for entry in self.log_messages])
    
    def export_logs_as_text(self) -> str:
        """ログをテキスト形式で出力"""
        lines = []
        for entry in self.log_messages:
            timestamp = entry.get("timestamp", "")
            level = entry.get("level", "")
            message = entry.get("message", "")
            task_info = f"Task {entry.get('task_index', 0)+1}/{entry.get('task_count', 1)}"
            
            line = f"{timestamp} - {task_info} - {level} - {message}"
            
            # context情報があればそれも追加（AI応答の詳細など）
            important_context_keys = [
                'response_full', 'response_preview', 'response_raw', 
                'doctor_name', 'contains_tab', 'contains_newline',
                'starts_with_status', 'line_count', 'response_length'
            ]
            
            context_parts = []
            for key in important_context_keys:
                if key in entry:
                    value = entry[key]
                    if key == 'response_full' and value:
                        # AI応答の全文を追加
                        context_parts.append(f"AI応答全文: {value}")
                    elif key == 'response_preview' and value:
                        context_parts.append(f"応答抜粋: {value}")
                    elif key == 'response_raw' and value:
                        context_parts.append(f"応答内容: {value}")
                    elif key == 'doctor_name' and value:
                        context_parts.append(f"医師名: {value}")
                    elif key in ['contains_tab', 'contains_newline'] and value is not None:
                        context_parts.append(f"{key}: {value}")
                    elif key in ['starts_with_status', 'line_count', 'response_length'] and value is not None:
                        context_parts.append(f"{key}: {value}")
            
            if context_parts:
                line += f" | {' | '.join(context_parts)}"
            
            lines.append(line)
        
        return "\n".join(lines)
    
    def get_log_filename(self, format_type: str = "log") -> str:
        """ログファイル名を生成"""
        timestamp = self.get_jst_now_str()
        return f"{self.system_name}_task_{self.task_index}_{timestamp}.{format_type}"