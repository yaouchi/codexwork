"""
DrTrack GCS操作クライアント

入力読み込み、出力保存、ログアップロード機能
"""

import pandas as pd
import csv
from io import StringIO
from typing import List, Dict, Any, Optional
from google.cloud import storage

from config import Config
from .logger import UnifiedLogger


class UnifiedGCSClient:
    """DrTrack GCS操作クライアント"""
    
    def __init__(self, config: Config, logger: UnifiedLogger):
        self.config = config
        self.logger = logger
        self.storage_client = storage.Client(project=config.project_id)
    
    def fetch_input_csv(self) -> pd.DataFrame:
        """入力CSVファイルを取得"""
        try:
            bucket_name = self.config.input_bucket
            file_path = f"{self.config.job_type}/input/input.csv"
            
            self.logger.log_info(f"入力CSV読み込み開始: gs://{bucket_name}/{file_path}")
            
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(file_path)
            
            if not blob.exists():
                raise FileNotFoundError(f"入力ファイルが見つかりません: gs://{bucket_name}/{file_path}")
            
            # CSV内容を取得
            csv_content = blob.download_as_text(encoding='utf-8')
            df = pd.read_csv(StringIO(csv_content))
            
            # 列名の正規化（URLとurlの両方に対応）
            df = self._normalize_columns(df)
            
            # 必須列の確認
            required_columns = ['fac_id_unif', 'URL']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                raise ValueError(f"必須列が不足しています: {missing_columns}")
            
            self.logger.log_success(
                f"入力CSV読み込み完了: {len(df)}行",
                row_count=len(df),
                columns=list(df.columns)
            )
            
            return df
            
        except Exception as e:
            self.logger.log_error(f"入力CSV読み込みエラー: {str(e)}", error=e)
            raise
    
    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """列名を正規化（URLとurlの統一）"""
        # url列をURL列に統一
        if 'url' in df.columns and 'URL' not in df.columns:
            df = df.rename(columns={'url': 'URL'})
            self.logger.log_info("列名を正規化: url -> URL")
        
        return df
    
    def fetch_prompt(self) -> str:
        """プロンプトファイルを取得"""
        try:
            bucket_name = self.config.input_bucket
            file_path = f"{self.config.job_type}/input/prompt.txt"
            
            self.logger.log_info(f"プロンプト読み込み開始: gs://{bucket_name}/{file_path}")
            
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(file_path)
            
            if not blob.exists():
                raise FileNotFoundError(f"プロンプトファイルが見つかりません: gs://{bucket_name}/{file_path}")
            
            content = blob.download_as_text(encoding='utf-8')
            
            self.logger.log_success(
                f"プロンプト読み込み完了: {len(content)}文字",
                content_length=len(content)
            )
            
            return content
            
        except Exception as e:
            self.logger.log_error(f"プロンプト読み込みエラー: {str(e)}", error=e)
            raise
    
    def upload_tsv(self, records: List[Dict[str, Any]], filename: Optional[str] = None) -> str:
        """TSVファイルをアップロード（pandas.to_csv完全回避版）"""
        try:
            if not records:
                self.logger.log_warning("アップロードするレコードがありません")
                return ""
            
            # ファイル名生成
            if not filename:
                timestamp = self.logger.get_jst_now_str()
                filename = f"{self.config.job_type}_result_task_{self.config.task_index}_{timestamp}.tsv"
            
            # データフレーム作成（重複除去のためだけに使用）
            df = pd.DataFrame(records)
            
            # 重複除去
            original_count = len(df)
            if self.config.job_type == "url_collect":
                df = df.sort_values('update_datetime', ascending=False)
                df = df.drop_duplicates(subset=['fac_id_unif', 'url'], keep='first')
                self.logger.log_info(f"URL収集: 重複除去前={original_count}, 重複除去後={len(df)}")
            else:
                df = df.drop_duplicates()
                if len(df) < original_count:
                    self.logger.log_info(f"重複除去: {original_count} -> {len(df)}行")
            
            # 徹底的なフィールドクリーニング関数
            def ultra_clean_field(value):
                """完全安全なフィールドクリーニング"""
                if pd.isna(value) or value is None:
                    return ""
                
                # 文字列化
                str_value = str(value)
                
                # 危険文字を完全除去
                danger_chars = ['\t', '\n', '\r', '\x00', '\x0b', '\x0c']
                for char in danger_chars:
                    str_value = str_value.replace(char, ' ')
                
                # 引用符を安全な文字に
                str_value = str_value.replace('"', "'").replace('`', "'")
                
                # バックスラッシュをスラッシュに
                str_value = str_value.replace('\\', '/')
                
                # 連続空白を単一に
                import re
                str_value = re.sub(r'\s+', ' ', str_value).strip()
                
                # 長すぎる場合は切り詰め
                if len(str_value) > 500:
                    str_value = str_value[:497] + "..."
                
                return str_value
            
            # 手動TSV生成（pandas.to_csv()を一切使わない）
            tsv_lines = []
            
            # ヘッダー行の生成
            if len(df) > 0:
                columns = list(df.columns)
                clean_columns = [ultra_clean_field(col) for col in columns]
                header_line = '\t'.join(clean_columns)
                tsv_lines.append(header_line)
                
                # データ行の生成
                for idx, (_, row) in enumerate(df.iterrows()):
                    try:
                        clean_values = []
                        for col in columns:
                            raw_value = row[col] if col in row else ""
                            clean_value = ultra_clean_field(raw_value)
                            clean_values.append(clean_value)
                        
                        data_line = '\t'.join(clean_values)
                        tsv_lines.append(data_line)
                        
                    except Exception as row_error:
                        self.logger.log_warning(f"行{idx}のクリーニングでエラー: {row_error}")
                        # エラー行は基本情報のみ
                        error_values = [
                            ultra_clean_field(row.get('fac_id_unif', '')),
                            'ERROR',
                            f'行処理エラー_{idx}'
                        ]
                        # 残りの列を空で埋める
                        while len(error_values) < len(columns):
                            error_values.append('')
                        
                        error_line = '\t'.join(error_values[:len(columns)])
                        tsv_lines.append(error_line)
            
            # TSVコンテンツ生成
            tsv_content = '\n'.join(tsv_lines) + '\n'
            
            # GCSアップロード
            bucket_name = self.config.input_bucket
            file_path = f"{self.config.job_type}/tsv/{filename}"
            
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(file_path)
            
            self.logger.log_info(f"TSVアップロード開始: gs://{bucket_name}/{file_path}")
            
            blob.upload_from_string(
                tsv_content, 
                content_type='text/tab-separated-values'
            )
            
            gcs_path = f"gs://{bucket_name}/{file_path}"
            
            self.logger.log_success(
                f"手動TSVアップロード完了: {len(df)}行",
                file_path=gcs_path,
                record_count=len(df)
            )
            
            return gcs_path
            
        except Exception as e:
            self.logger.log_error(f"TSVアップロードエラー: {str(e)}")
            
            # 最終緊急手段：最低限のCSV形式
            try:
                self.logger.log_warning("最終緊急手段: 簡易CSV生成")
                emergency_content = "fac_id_unif,validation_status,error_message\n"
                for i, record in enumerate(records[:5]):  # 最初の5件だけ
                    fac_id = str(record.get('fac_id_unif', f'unknown_{i}')).replace(',', '_')
                    status = str(record.get('validation_status', 'ERROR')).replace(',', '_')
                    emergency_content += f"{fac_id},{status},TSV_generation_failed\n"
                
                emergency_filename = f"EMERGENCY_{filename}".replace('.tsv', '.csv')
                file_path = f"{self.config.job_type}/tsv/{emergency_filename}"
                
                bucket = self.storage_client.bucket(self.config.input_bucket)
                blob = bucket.blob(file_path)
                blob.upload_from_string(emergency_content, content_type='text/csv')
                
                emergency_path = f"gs://{self.config.input_bucket}/{file_path}"
                self.logger.log_warning(f"緊急CSV保存完了: {emergency_path}")
                return emergency_path
                
            except Exception as emergency_error:
                self.logger.log_error(f"緊急保存も失敗: {emergency_error}")
                raise e
    
    def upload_log(self) -> str:
        """ログファイルをアップロード"""
        try:
            # ログファイル名生成
            log_filename = self.logger.get_log_filename()
            
            # ログ内容をテキスト形式で取得
            log_content = self.logger.export_logs_as_text()
            
            if not log_content:
                self.logger.log_warning("アップロードするログがありません")
                return ""
            
            # GCSにアップロード
            bucket_name = self.config.input_bucket
            file_path = f"{self.config.job_type}/log/{log_filename}"
            
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(file_path)
            
            blob.upload_from_string(
                log_content, 
                content_type='text/plain'
            )
            
            gcs_path = f"gs://{bucket_name}/{file_path}"
            
            # 最終ログとしてPythonロガーに出力
            import logging
            logging.getLogger().info(f"ログアップロード完了: {gcs_path}")
            
            return gcs_path
            
        except Exception as e:
            # ログアップロード失敗は致命的ではないので警告レベル
            import logging
            logging.getLogger().warning(f"ログアップロードエラー: {str(e)}")
            return ""
    
    def get_task_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """タスクの担当分データを取得"""
        total_rows = len(df)
        
        if total_rows == 0:
            return df
        
        # タスク分割
        if self.config.task_count == 1:
            start_idx = 0
            end_idx = total_rows
        else:
            chunk_size = total_rows // self.config.task_count
            remainder = total_rows % self.config.task_count
            
            start_idx = self.config.task_index * chunk_size + min(self.config.task_index, remainder)
            end_idx = start_idx + chunk_size + (1 if self.config.task_index < remainder else 0)
        
        self.logger.log_info(
            f"タスク分割: {start_idx}～{end_idx-1} (全{total_rows}件中)",
            start_index=start_idx,
            end_index=end_idx,
            total_rows=total_rows,
            chunk_size=end_idx - start_idx
        )
        
        return df.iloc[start_idx:end_idx]