#!/usr/bin/env python3
"""
AI処理失敗記録システム

フォールバック処理廃止機能の一部として、AI処理失敗時の
透明性の高い記録システムを提供する。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, Optional
import re


@dataclass
class FailureRecord:
    """AI処理失敗記録"""
    url: str
    fac_id_unif: str
    failure_reason: str
    error_details: str
    timestamp: datetime


class FailureReasonClassifier:
    """失敗原因分類器"""
    
    FAILURE_TYPES = {
        'CONNECTION_ERROR': ['connection', 'network', 'dns', 'unreachable'],
        'TIMEOUT_ERROR': ['timeout', 'deadline', 'timed out'],
        'API_RATE_LIMIT': ['429', 'rate_limit', 'quota', 'too many requests'],
        'API_ERROR': ['400', '401', '403', '404', '500', '502', '503'],
        'EMPTY_RESPONSE': ['empty', 'null', 'no_records', 'no data'],
        'PARSING_ERROR': ['json', 'parse', 'format', 'decode', 'invalid'],
        'UNKNOWN_ERROR': []
    }
    
    @classmethod
    def classify(cls, error: Exception) -> str:
        """エラーを分類して失敗原因を返す"""
        error_str = str(error).lower()
        
        for error_type, keywords in cls.FAILURE_TYPES.items():
            if error_type == 'UNKNOWN_ERROR':
                continue
                
            for keyword in keywords:
                if keyword in error_str:
                    return error_type
                    
        return 'UNKNOWN_ERROR'


class AIFailureRecorder:
    """AI処理失敗記録器"""
    
    def __init__(self, logger):
        """
        初期化
        
        Args:
            logger: UnifiedLoggerインスタンス
        """
        self.logger = logger
    
    def record_failure(self, url: str, fac_id_unif: str, 
                      failure_reason: str, error_details: str) -> FailureRecord:
        """
        失敗を記録して構造化データを返す
        
        Args:
            url: 失敗したURL
            fac_id_unif: 施設統一ID
            failure_reason: 失敗原因（分類済み）
            error_details: エラー詳細情報
            
        Returns:
            FailureRecord: 構造化された失敗記録
        """
        failure_record = FailureRecord(
            url=url,
            fac_id_unif=fac_id_unif,
            failure_reason=failure_reason,
            error_details=error_details,
            timestamp=datetime.now()
        )
        
        # ログに記録
        context = {
            'fac_id_unif': fac_id_unif,
            'failure_reason': failure_reason
        }
        
        self.logger.log_error(f"AI処理失敗記録: {url}", error_details=error_details, **context)
        
        return failure_record


class AlertManager:
    """アラート管理器"""
    
    def __init__(self, logger, config):
        """
        初期化
        
        Args:
            logger: UnifiedLoggerインスタンス
            config: 設定オブジェクト
        """
        self.logger = logger
        self.threshold = getattr(config, 'failure_rate_alert_threshold', 0.15)
    
    def check_and_alert(self, stats) -> None:
        """
        統計を確認してアラートを発火
        
        Args:
            stats: ProcessingStatisticsオブジェクト
        """
        if stats.total_processed == 0:
            return
            
        current_failure_rate = stats.ai_failure_count / stats.total_processed
        
        if current_failure_rate > self.threshold:
            alert_message = (f"AI失敗率が警戒しきい値を超過: "
                           f"{current_failure_rate:.1%} > {self.threshold:.1%}")
            
            self.logger.log_error(f"[ALERT:HIGH_AI_FAILURE_RATE] {alert_message}")