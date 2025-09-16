"""
共通ユーティリティ関数

URL妥当性チェック、メモリ管理等の共通機能
"""

import re
import gc
import psutil
import urllib.parse
from typing import List, Dict, Any, Optional, Tuple


def validate_url(url: str) -> bool:
    """URL妥当性チェック"""
    if not url or not isinstance(url, str):
        return False
    
    # 基本的なURL形式チェック
    if not url.startswith(('http://', 'https://')):
        return False
    
    try:
        parsed = urllib.parse.urlparse(url)
        return bool(parsed.netloc and parsed.scheme)
    except:
        return False


def calculate_chunk_range(total_items: int, task_index: int, task_count: int) -> Tuple[int, int]:
    """タスク分割の範囲を計算"""
    if total_items == 0 or task_count <= 0:
        return 0, 0
    
    if task_count == 1:
        return 0, total_items
    
    # より均等な分割
    chunk_size = total_items // task_count
    remainder = total_items % task_count
    
    start_idx = task_index * chunk_size + min(task_index, remainder)
    end_idx = start_idx + chunk_size + (1 if task_index < remainder else 0)
    
    return start_idx, min(end_idx, total_items)


def generate_instance_id() -> str:
    """インスタンスID生成"""
    import hashlib
    import os
    import datetime
    
    data = f"{os.getpid()}-{datetime.datetime.now().isoformat()}"
    return hashlib.md5(data.encode()).hexdigest()[:8]


def get_memory_usage() -> Dict[str, float]:
    """メモリ使用量取得"""
    try:
        process = psutil.Process()
        memory_info = process.memory_info()
        
        return {
            'rss_mb': memory_info.rss / 1024 / 1024,  # Resident Set Size
            'vms_mb': memory_info.vms / 1024 / 1024,  # Virtual Memory Size
            'percent': process.memory_percent()
        }
    except:
        return {'rss_mb': 0, 'vms_mb': 0, 'percent': 0}


def cleanup_memory():
    """メモリクリーンアップ"""
    gc.collect()


def format_duration(seconds: float) -> str:
    """処理時間のフォーマット"""
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        return f"{seconds/60:.1f}分"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}時間{minutes}分"


def truncate_content(content: str, max_length: int) -> str:
    """コンテンツの切り詰め"""
    if not content or len(content) <= max_length:
        return content
    
    return content[:max_length]


def clean_html_content(html_content: str) -> str:
    """HTML内容のクリーンアップ"""
    if not html_content:
        return ""
    
    # 基本的なHTMLタグ除去
    
    # スクリプト・スタイル除去
    html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    
    # HTMLタグ除去
    html_content = re.sub(r'<[^>]+>', '', html_content)
    
    # 連続する空白・改行を整理
    html_content = re.sub(r'\s+', ' ', html_content)
    
    return html_content.strip()


def extract_domain(url: str) -> Optional[str]:
    """URLからドメイン抽出"""
    try:
        parsed = urllib.parse.urlparse(url)
        return parsed.netloc.lower()
    except:
        return None


def is_valid_japanese_text(text: str, min_length: int = 1) -> bool:
    """日本語テキストの妥当性チェック"""
    if not text or len(text) < min_length:
        return False
    
    # ひらがな、カタカナ、漢字が含まれているかチェック
    return bool(re.search(r'[ぁ-んァ-ヶ一-龯]', text))


def normalize_whitespace(text: str) -> str:
    """空白文字の正規化"""
    if not text:
        return ""
    
    # 全角スペースも半角スペースに統一
    text = text.replace('　', ' ')
    
    # 連続する空白を単一スペースに
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def validate_facility_id(fac_id_unif: str) -> bool:
    """施設IDの妥当性チェック"""
    if not fac_id_unif:
        return False
    
    # サンプルデータ除外
    if fac_id_unif in ['123456789', 'sample', 'test']:
        return False
    
    # 基本的な形式チェック（数字のみ、適切な桁数）
    if re.match(r'^\d{6,12}$', fac_id_unif):
        return True
    
    return False


def detect_encoding(content: bytes) -> str:
    """エンコーディング検出"""
    try:
        import chardet
        result = chardet.detect(content)
        return result.get('encoding', 'utf-8')
    except:
        # chardetがない場合は一般的なエンコーディングを試行
        for encoding in ['utf-8', 'shift_jis', 'euc-jp', 'cp932']:
            try:
                content.decode(encoding)
                return encoding
            except:
                continue
        return 'utf-8'


class ProgressTracker:
    """進捗追跡クラス"""
    
    def __init__(self, total: int, logger=None, log_interval: int = 10):
        self.total = total
        self.current = 0
        self.logger = logger
        self.log_interval = log_interval
        self.last_logged = 0
    
    def update(self, increment: int = 1):
        """進捗更新"""
        self.current += increment
        
        # 定期ログ出力
        if self.logger and (self.current - self.last_logged) >= self.log_interval:
            percentage = (self.current / self.total * 100) if self.total > 0 else 0
            self.logger.log_progress(
                self.current,
                self.total,
                "item",
                percentage=percentage
            )
            self.last_logged = self.current
    
    def is_complete(self) -> bool:
        """完了判定"""
        return self.current >= self.total
    
    def get_percentage(self) -> float:
        """進捗率取得"""
        return (self.current / self.total * 100) if self.total > 0 else 0


class ProcessingResult:
    """処理結果クラス"""
    
    def __init__(
        self,
        success: bool,
        records: List[Dict[str, Any]],
        error_message: Optional[str] = None,
        url: Optional[str] = None,
        fac_id_unif: Optional[str] = None
    ):
        self.success = success
        self.records = records or []
        self.error_message = error_message
        self.url = url
        self.fac_id_unif = fac_id_unif
    
    def __bool__(self):
        return self.success
    
    def __len__(self):
        return len(self.records)