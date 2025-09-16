"""
基底プロセッサークラス

各機能共通の処理ベース
"""

import asyncio
import pandas as pd
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from config import Config
from common.logger import UnifiedLogger
from common.gcs_client import UnifiedGCSClient
from common.ai_client import UnifiedAIClient
from common.utils import ProgressTracker, get_memory_usage, cleanup_memory


class BaseProcessor(ABC):
    """基底プロセッサークラス"""
    
    def __init__(self, config: Config, logger: UnifiedLogger):
        self.config = config
        self.logger = logger
        
        # クライアント初期化
        self.gcs_client = UnifiedGCSClient(config, logger)
        self.ai_client = UnifiedAIClient(config, logger)
        
        # 処理統計
        self.stats = {
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'records_extracted': 0
        }
        
        # 失敗URL記録
        self.failed_items = {}
        self.all_records = []
    
    async def run_async(self):
        """非同期メイン処理"""
        try:
            # 開始ログ
            self.logger.log_success(f"{self.config.job_type.upper()} 非同期処理開始")
            
            # 入力データ取得
            df = self.gcs_client.fetch_input_csv()
            task_df = self.gcs_client.get_task_data(df)
            
            if task_df.empty:
                self.logger.log_warning("処理対象データがありません")
                return
            
            # プロンプト取得
            prompt = self.gcs_client.fetch_prompt()
            
            # 処理実行
            await self.process_data_async(task_df, prompt)
            
            # 結果保存
            await self.save_results()
            
            # 統計出力
            self.log_final_stats()
            
            self.logger.log_success(f"{self.config.job_type.upper()} 非同期処理完了")
            
        except Exception as e:
            self.logger.log_error(f"{self.config.job_type.upper()} 処理エラー: {str(e)}", error=e)
            raise
        finally:
            # ログアップロード
            self.gcs_client.upload_log()
    
    def run_sync(self):
        """同期メイン処理"""
        try:
            # 開始ログ
            self.logger.log_success(f"{self.config.job_type.upper()} 同期処理開始")
            
            # 入力データ取得
            df = self.gcs_client.fetch_input_csv()
            task_df = self.gcs_client.get_task_data(df)
            
            if task_df.empty:
                self.logger.log_warning("処理対象データがありません")
                return
            
            # プロンプト取得
            prompt = self.gcs_client.fetch_prompt()
            
            # 処理実行
            self.process_data_sync(task_df, prompt)
            
            # 結果保存
            asyncio.run(self.save_results())
            
            # 統計出力
            self.log_final_stats()
            
            self.logger.log_success(f"{self.config.job_type.upper()} 同期処理完了")
            
        except Exception as e:
            self.logger.log_error(f"{self.config.job_type.upper()} 処理エラー: {str(e)}", error=e)
            raise
        finally:
            # ログアップロード
            self.gcs_client.upload_log()
    
    @abstractmethod
    async def process_data_async(self, df: pd.DataFrame, prompt: str):
        """非同期データ処理（各プロセッサーで実装）"""
        pass
    
    @abstractmethod
    def process_data_sync(self, df: pd.DataFrame, prompt: str):
        """同期データ処理（各プロセッサーで実装）"""
        pass
    
    @abstractmethod
    def process_single_item(self, item: Dict[str, Any], prompt: str) -> List[Dict[str, Any]]:
        """単一アイテム処理（各プロセッサーで実装）"""
        pass
    
    async def process_batch_async(self, batch_data: List[Dict[str, Any]], prompt: str):
        """バッチ非同期処理"""
        tasks = []
        semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)
        
        async def process_with_semaphore(item):
            async with semaphore:
                return self.process_single_item(item, prompt)
        
        # タスク作成
        for item in batch_data:
            task = process_with_semaphore(item)
            tasks.append(task)
        
        # 並行処理実行
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 結果処理
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                item = batch_data[i]
                error_msg = str(result)
                self.logger.log_error(f"バッチ処理エラー: {error_msg}", error=result)
                self._record_failure(item, error_msg)
            elif isinstance(result, list):
                self._record_success(result)
            else:
                item = batch_data[i]
                self._record_failure(item, "予期しない結果形式")
    
    def process_batch_sync(self, batch_data: List[Dict[str, Any]], prompt: str):
        """バッチ同期処理"""
        for item in batch_data:
            try:
                result = self.process_single_item(item, prompt)
                self._record_success(result)
                
            except Exception as e:
                error_msg = str(e)
                self.logger.log_error(f"バッチ処理エラー: {error_msg}", error=e)
                self._record_failure(item, error_msg)
    
    def _record_success(self, records: List[Dict[str, Any]]):
        """成功記録"""
        self.stats['total_processed'] += 1
        self.stats['successful'] += 1
        self.stats['records_extracted'] += len(records)
        self.all_records.extend(records)
    
    def _record_failure(self, item: Dict[str, Any], error_msg: str):
        """失敗記録"""
        self.stats['total_processed'] += 1
        self.stats['failed'] += 1
        
        key = item.get('URL') or item.get('url') or str(item.get('fac_id_unif', 'unknown'))
        self.failed_items[key] = error_msg
    
    async def save_results(self):
        """結果保存"""
        try:
            # TSV保存
            if self.all_records:
                output_path = self.gcs_client.upload_tsv(self.all_records)
                self.logger.log_success(
                    f"結果保存完了: {len(self.all_records)}レコード",
                    output_path=output_path,
                    record_count=len(self.all_records)
                )
            else:
                self.logger.log_warning("保存するレコードがありません")
            
            # 失敗情報保存（ログ内に記録）
            if self.failed_items:
                self.logger.log_info(f"失敗アイテム一覧 ({len(self.failed_items)}件):")
                for key, reason in list(self.failed_items.items())[:10]:  # 最初の10件のみ
                    self.logger.log_warning(f"  失敗: {key} - {reason}")
                
                if len(self.failed_items) > 10:
                    self.logger.log_info(f"  ... 他 {len(self.failed_items) - 10} 件")
            
        except Exception as e:
            self.logger.log_error(f"結果保存エラー: {str(e)}", error=e)
            raise
    
    def log_final_stats(self):
        """最終統計ログ"""
        # メモリ使用量取得
        memory_info = get_memory_usage()
        
        # 成功率計算
        success_rate = 0
        if self.stats['total_processed'] > 0:
            success_rate = (self.stats['successful'] / self.stats['total_processed']) * 100
        
        # 統計ログ出力
        self.logger.log_statistics({
            'total_processed': self.stats['total_processed'],
            'successful': self.stats['successful'],
            'failed': self.stats['failed'],
            'success_rate_percent': round(success_rate, 1),
            'records_extracted': self.stats['records_extracted'],
            'failed_items_count': len(self.failed_items),
            'memory_usage_mb': round(memory_info['rss_mb'], 1),
            'memory_percent': round(memory_info['percent'], 1)
        })
        
        # 詳細ログ
        self.logger.log_success(f"処理完了統計:")
        self.logger.log_success(f"  総処理数: {self.stats['total_processed']}")
        self.logger.log_success(f"  成功: {self.stats['successful']}")
        self.logger.log_success(f"  失敗: {self.stats['failed']}")
        self.logger.log_success(f"  成功率: {success_rate:.1f}%")
        self.logger.log_success(f"  抽出レコード数: {self.stats['records_extracted']}")
        self.logger.log_success(f"  メモリ使用量: {memory_info['rss_mb']:.1f}MB")
    
    def cleanup(self):
        """リソースクリーンアップ"""
        try:
            cleanup_memory()
            self.logger.log_info("リソースクリーンアップ完了")
        except Exception as e:
            self.logger.log_warning(f"クリーンアップエラー: {str(e)}", error=e)
    
    def create_progress_tracker(self, total: int) -> ProgressTracker:
        """進捗追跡オブジェクト作成"""
        return ProgressTracker(
            total=total,
            logger=self.logger,
            log_interval=max(1, total // 20)  # 5%刻みでログ
        )
    
    def validate_input_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """入力データ検証"""
        original_count = len(df)
        
        # 必須列チェック
        required_columns = ['fac_id_unif', 'URL']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValueError(f"必須列が不足しています: {missing_columns}")
        
        # NaN値除去
        df = df.dropna(subset=required_columns)
        
        # 重複除去
        df = df.drop_duplicates(subset=required_columns)
        
        # 無効データ除去
        df = df[df['URL'].str.startswith(('http://', 'https://'), na=False)]
        
        cleaned_count = len(df)
        
        self.logger.log_info(
            f"入力データ検証完了: {original_count} -> {cleaned_count}件",
            original_count=original_count,
            cleaned_count=cleaned_count,
            removed_count=original_count - cleaned_count
        )
        
        return df