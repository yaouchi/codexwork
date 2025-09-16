"""
DrTrack 設定管理モジュール

環境変数とシステム設定を一元管理
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """DrTrack 設定クラス"""
    
    # 実行設定
    job_type: str                    # url_collect/doctor_info/outpatient
    
    # GCS設定
    project_id: str
    input_bucket: str                # drtrack_test
    
    # Cloud Run Jobs設定
    task_index: int
    task_count: int
    
    # AI設定
    gemini_key: str
    ai_model: str = "gemini-2.5-flash-lite"
    ai_temperature: float = 0.05
    ai_timeout: int = 120
    
    # 処理設定
    log_level: str = "INFO"
    max_retries: int = 3
    retry_delay: float = 1.0
    
    # 機能別設定
    max_content_length: int = 30000   # HTMLコンテンツ最大長
    request_timeout: int = 30         # HTTPリクエストタイムアウト
    max_concurrent_requests: int = 5  # 最大同時リクエスト数
    
    # 複合タイプ機能設定
    enable_composite_type: bool = False                    # 複合タイプ検出の有効/無効
    composite_type_priority: list = None                   # タイプ優先順位
    
    # 失敗監視設定
    failure_rate_alert_threshold: float = 0.15            # 15%以上で警告
    failure_statistics_log_interval: int = 100            # 100件ごとに統計ログ
    
    @classmethod
    def from_env(cls) -> 'Config':
        """環境変数から設定を作成"""
        
        # 必須環境変数
        job_type = os.getenv("JOB_TYPE")
        if not job_type:
            raise ValueError("JOB_TYPE環境変数が設定されていません")
        
        if job_type not in ["url_collect", "doctor_info", "outpatient", "doctor_info_validation"]:
            raise ValueError(f"無効なJOB_TYPE: {job_type}")
        
        gemini_key = os.getenv("GEMINIKEY")
        if not gemini_key:
            raise ValueError("GEMINIKEY環境変数が設定されていません")
        
        return cls(
            job_type=job_type,
            project_id=os.getenv("PROJECT_ID", "i-rw-sandbox"),
            input_bucket=os.getenv("INPUT_BUCKET", "drtrack_test"),
            task_index=int(os.getenv("CLOUD_RUN_TASK_INDEX", "0")),
            task_count=int(os.getenv("CLOUD_RUN_TASK_COUNT", "1")),
            gemini_key=gemini_key,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            retry_delay=float(os.getenv("RETRY_DELAY", "1.0")),
            max_content_length=int(os.getenv("MAX_CONTENT_LENGTH", "30000")),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "30")),
            max_concurrent_requests=int(os.getenv("MAX_CONCURRENT_REQUESTS", "5")),
            enable_composite_type=os.getenv('ENABLE_COMPOSITE_TYPE', 'false').lower() == 'true',
            composite_type_priority=['s', 'g_txt', 'g_img', 'g_pdf'],
            failure_rate_alert_threshold=float(os.getenv("FAILURE_RATE_ALERT_THRESHOLD", "0.15")),
            failure_statistics_log_interval=int(os.getenv("FAILURE_STATISTICS_LOG_INTERVAL", "100"))
        )
    
    def validate(self) -> None:
        """設定の妥当性チェック"""
        if not self.project_id:
            raise ValueError("PROJECT_ID が設定されていません")
        
        if not self.input_bucket:
            raise ValueError("INPUT_BUCKET が設定されていません")
        
        if self.task_index < 0:
            raise ValueError(f"無効なタスクインデックス: {self.task_index}")
        
        if self.task_count <= 0:
            raise ValueError(f"無効なタスク数: {self.task_count}")
        
        if self.task_index >= self.task_count:
            raise ValueError(f"タスクインデックス({self.task_index})がタスク数({self.task_count})以上です")
    
    def get_input_path(self) -> str:
        """入力ファイルのGCSパスを取得"""
        return f"gs://{self.input_bucket}/{self.job_type}/input/"
    
    def get_output_path(self) -> str:
        """出力ディレクトリのGCSパスを取得"""
        return f"gs://{self.input_bucket}/{self.job_type}/tsv/"
    
    def get_log_path(self) -> str:
        """ログディレクトリのGCSパスを取得"""
        return f"gs://{self.input_bucket}/{self.job_type}/log/"
    
    def get_task_info(self) -> str:
        """タスク情報を文字列で取得"""
        return f"Task {self.task_index+1}/{self.task_count}"


# ローカルテスト用設定
LOCAL_TEST = os.getenv("LOCAL_TEST", "false").lower() == "true"