#!/usr/bin/env python3
"""
処理統計管理システム

AI処理失敗時の統計情報を管理し、GCSに永続化する機能を提供する。
"""

from dataclasses import dataclass, field
from typing import Dict, Any
from datetime import datetime, timezone, timedelta
import json


@dataclass
class ProcessingStatistics:
    """処理統計データ"""
    
    # AI処理統計
    total_processed: int = 0
    ai_success_count: int = 0
    ai_failure_count: int = 0
    ai_success_rate: float = 0.0
    
    # 失敗原因別統計
    failure_breakdown: Dict[str, int] = field(default_factory=dict)
    
    # 複合タイプ統計（成功時のみ）
    composite_type_stats: Dict[str, int] = field(default_factory=dict)
    
    # 時間別統計
    processing_by_hour: Dict[str, int] = field(default_factory=dict)
    
    def calculate_success_rate(self) -> None:
        """成功率を計算"""
        if self.total_processed > 0:
            self.ai_success_rate = self.ai_success_count / self.total_processed
        else:
            self.ai_success_rate = 0.0


class FailureStatistics:
    """失敗統計管理"""
    
    def __init__(self, gcs_client):
        """
        初期化
        
        Args:
            gcs_client: GCSClientインスタンス
        """
        self.gcs_client = gcs_client
        self.stats = ProcessingStatistics()
    
    def update_failure(self, failure_record) -> None:
        """
        失敗統計を更新
        
        Args:
            failure_record: FailureRecordオブジェクト
        """
        self.stats.total_processed += 1
        self.stats.ai_failure_count += 1
        
        # 失敗原因別統計を更新
        reason = failure_record.failure_reason
        if reason in self.stats.failure_breakdown:
            self.stats.failure_breakdown[reason] += 1
        else:
            self.stats.failure_breakdown[reason] = 1
        
        # 時間別統計を更新
        hour_key = failure_record.timestamp.strftime('%Y-%m-%d-%H')
        if hour_key in self.stats.processing_by_hour:
            self.stats.processing_by_hour[hour_key] += 1
        else:
            self.stats.processing_by_hour[hour_key] = 1
        
        # 成功率を再計算
        self.stats.calculate_success_rate()
    
    def update_success(self, url_type: str, processing_time: float = 0.0) -> None:
        """
        成功統計を更新
        
        Args:
            url_type: 分類されたURLタイプ
            processing_time: 処理時間（秒）
        """
        self.stats.total_processed += 1
        self.stats.ai_success_count += 1
        
        # 複合タイプ統計を更新
        if url_type.startswith('sg_'):
            if url_type in self.stats.composite_type_stats:
                self.stats.composite_type_stats[url_type] += 1
            else:
                self.stats.composite_type_stats[url_type] = 1
        
        # 時間別統計を更新（成功）
        current_time = datetime.now(timezone(timedelta(hours=9)))
        hour_key = current_time.strftime('%Y-%m-%d-%H')
        if hour_key in self.stats.processing_by_hour:
            self.stats.processing_by_hour[hour_key] += 1
        else:
            self.stats.processing_by_hour[hour_key] = 1
        
        # 成功率を再計算
        self.stats.calculate_success_rate()
    
    def get_statistics(self) -> ProcessingStatistics:
        """統計データを取得"""
        return self.stats
    
    def persist_statistics(self) -> None:
        """統計をGCSに永続化"""
        try:
            # 統計データをJSON形式で準備
            stats_data = {
                "processing_summary": {
                    "total_processed": self.stats.total_processed,
                    "ai_success_count": self.stats.ai_success_count,
                    "ai_failure_count": self.stats.ai_failure_count,
                    "ai_success_rate": round(self.stats.ai_success_rate * 100, 1)
                },
                "failure_breakdown": self.stats.failure_breakdown,
                "composite_type_stats": self.stats.composite_type_stats,
                "processing_by_hour": self.stats.processing_by_hour,
                "timestamp": datetime.now(timezone(timedelta(hours=9))).isoformat(),
                "alerts": self._generate_alert_status()
            }
            
            # JSONファイルとして保存
            stats_json = json.dumps(stats_data, ensure_ascii=False, indent=2)
            
            # GCSにアップロード（url_collect/statistics/ パスに）
            timestamp = datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d_%H%M%S')
            filename = f"url_collect/statistics/processing_stats_{timestamp}.json"
            
            self.gcs_client.upload_file(filename, stats_json.encode('utf-8'))
            
        except Exception as e:
            # 統計の永続化に失敗してもメイン処理は継続
            print(f"統計永続化エラー: {e}")
    
    def _generate_alert_status(self) -> list:
        """アラート状態を生成"""
        alerts = []
        
        # 失敗率アラート
        threshold = 0.15  # 15%
        current_rate = self.stats.ai_success_rate
        
        alerts.append({
            "type": "high_failure_rate",
            "threshold": threshold * 100,
            "current_rate": round((1 - current_rate) * 100, 1),
            "status": "above_threshold" if (1 - current_rate) > threshold else "below_threshold"
        })
        
        return alerts