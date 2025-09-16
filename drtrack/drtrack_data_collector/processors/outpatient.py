"""
外来担当医表収集プロセッサー

HTML・画像・PDFのマルチモーダル処理で外来担当医表を抽出
"""

import asyncio
import re
from typing import List, Dict, Any, Optional, Union
import pandas as pd

from config import Config, LOCAL_TEST
from common.logger import UnifiedLogger
from common.http_client import UnifiedHttpClient
from common.ai_client_outpatient_simple import SimpleOutpatientAIClient
from common.utils import validate_url, ProcessingResult
from .base_processor import BaseProcessor


class OutpatientProcessor(BaseProcessor):
    """外来担当医表収集プロセッサー"""
    
    def __init__(self, config: Config, logger: UnifiedLogger):
        super().__init__(config, logger)
        self.http_client = None
        # シンプルAIクライアントを使用
        self.ai_client = SimpleOutpatientAIClient(config, logger)
        
        # マルチモーダル処理統計
        self.modal_stats = {
            'html_success': 0,
            'image_success': 0,
            'pdf_success': 0,
            'html_attempts': 0,
            'image_attempts': 0,
            'pdf_attempts': 0
        }
        
        # 複合タイプ統計
        self.composite_type_stats = {
            'total_processed': 0,
            'composite_detected': 0,
            'types': {
                'sg_txt': 0,
                'sg_img': 0,
                'sg_pdf': 0
            },
            'success_count': 0,
            'total_records_extracted': 0
        }
    
    async def process_data_async(self, df: pd.DataFrame, prompt: str):
        """非同期データ処理"""
        async with UnifiedHttpClient(self.config, self.logger) as http_client:
            self.http_client = http_client
            
            # バッチサイズ（マルチモーダル処理のため少なめ）
            batch_size = 30
            
            # バッチ処理
            for i in range(0, len(df), batch_size):
                batch_df = df.iloc[i:i + batch_size]
                batch_items = []
                
                for _, row in batch_df.iterrows():
                    batch_items.append({
                        'fac_id_unif': str(row['fac_id_unif']),
                        'url': row['URL'],
                        'type': row.get('type', '')  # 複合タイプサポート
                    })
                
                try:
                    await self._process_batch_async_custom(batch_items, prompt)
                    
                    # 進捗ログ
                    processed = min(i + batch_size, len(df))
                    self.logger.log_progress(processed, len(df), "URL")
                    
                    # バッチ間隔（マルチモーダル処理は負荷が高い）
                    await asyncio.sleep(1.0)
                    
                except Exception as e:
                    self.logger.log_error(f"バッチ処理エラー: batch {i//batch_size + 1}", error=e)
                    
                    # 個別処理にフォールバック
                    for item in batch_items:
                        try:
                            result = await self._process_single_url_async(item, prompt)
                            self._record_success(result)
                        except Exception as item_error:
                            self._record_failure(item, str(item_error))
    
    def process_data_sync(self, df: pd.DataFrame, prompt: str):
        """同期データ処理"""
        # マルチモーダル処理は非同期推奨のため、同期実行
        asyncio.run(self.process_data_async(df, prompt))
    
    def process_single_item(self, item: Dict[str, Any], prompt: str) -> List[Dict[str, Any]]:
        """単一アイテム処理（同期版）"""
        # 非同期コンテキスト内では直接非同期メソッドを呼べないため、
        # 空のリストを返し、実際の処理は BaseProcessor の方法で処理
        return []
    
    async def _process_batch_async_custom(self, batch_items: List[Dict[str, Any]], prompt: str):
        """カスタムバッチ非同期処理（outpatient専用）"""
        tasks = []
        semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)
        
        async def process_with_semaphore(item):
            async with semaphore:
                return await self._process_single_url_async(item, prompt)
        
        # タスク作成
        for item in batch_items:
            task = process_with_semaphore(item)
            tasks.append(task)
        
        # 並行処理実行
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 結果処理
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                item = batch_items[i]
                error_msg = str(result)
                self.logger.log_error(f"バッチ処理エラー: {error_msg}", error=result)
                self._record_failure(item, error_msg)
            elif isinstance(result, list):
                self._record_success(result)
            else:
                item = batch_items[i]
                self._record_failure(item, "予期しない結果形式")
    
    async def _process_single_url_async(self, item: Dict[str, Any], prompt: str) -> List[Dict[str, Any]]:
        """単一URL非同期マルチモーダル処理"""
        url = item['url']
        fac_id_unif = item['fac_id_unif']
        url_type = item.get('type', '')  # 複合タイプサポート
        
        # URL妥当性チェック
        if not validate_url(url):
            raise ValueError(f"無効なURL: {url}")
        
        # 複合タイプ検出ログ
        if url_type.startswith('sg_'):
            self.logger.log_info(
                f"複合タイプマルチモーダル処理開始: {fac_id_unif} (type: {url_type})",
                url=url,
                fac_id_unif=fac_id_unif,
                url_type=url_type
            )
        else:
            self.logger.log_info(f"マルチモーダル処理開始: {fac_id_unif}", url=url, fac_id_unif=fac_id_unif)
        
        # 複合タイプ対応のプロセッサ選択
        if url_type.startswith('sg_'):
            # 複合タイプの場合は、type末尾の処理方式を優先
            if url_type == 'sg_txt':
                processors = [self._process_as_html, self._process_as_image, self._process_as_pdf]
            elif url_type == 'sg_img':
                processors = [self._process_as_image, self._process_as_html, self._process_as_pdf]
            elif url_type == 'sg_pdf':
                processors = [self._process_as_pdf, self._process_as_html, self._process_as_image]
            else:
                processors = [self._process_as_html, self._process_as_image, self._process_as_pdf]
        else:
            # 通常のマルチモーダル処理順序: HTML → 画像 → PDF
            processors = [self._process_as_html, self._process_as_image, self._process_as_pdf]
        
        # プロンプト強化（複合タイプ対応）
        enhanced_prompt = prompt
        if url_type.startswith('sg_'):
            enhanced_prompt = prompt + f"\n\n注意: このページは複合タイプ({url_type})と判定されています。医師情報と外来担当医表の両方が含まれている可能性があります。外来担当医表の抽出に集中してください。"
        
        for processor in processors:
            try:
                result = await processor(url, fac_id_unif, enhanced_prompt, url_type)
                if result:
                    # 複合タイプ統計更新
                    if url_type.startswith('sg_'):
                        self._record_composite_type_processing(url_type, url, len(result))
                    
                    log_message = f"マルチモーダル処理成功: {processor.__name__}"
                    if url_type.startswith('sg_'):
                        log_message = f"複合タイプマルチモーダル処理成功: {processor.__name__} (type: {url_type})"
                    
                    self.logger.log_success(
                        log_message,
                        url=url,
                        fac_id_unif=fac_id_unif,
                        records=len(result),
                        url_type=url_type
                    )
                    return result
                    
            except Exception as e:
                self.logger.log_warning(
                    f"処理失敗 {processor.__name__}: {str(e)}",
                    url=url,
                    processor=processor.__name__
                )
                continue
        
        # すべての処理に失敗
        raise Exception("すべてのマルチモーダル処理に失敗")
    
    async def _process_as_html(self, url: str, fac_id_unif: str, prompt: str, url_type: str = '') -> List[Dict[str, Any]]:
        """HTML処理"""
        self.modal_stats['html_attempts'] += 1
        
        # HTML取得
        html_content = await self.http_client.fetch_html_async(url)
        if not html_content:
            raise Exception("HTML取得失敗")
        
        # 外来担当医表関連キーワードチェック
        if not self._contains_outpatient_keywords(html_content):
            raise Exception("外来担当医表キーワードなし")
        
        # HTML前処理
        processed_content = self.http_client.preprocess_html(html_content)
        if not processed_content.strip():
            raise Exception("HTML前処理後にコンテンツが空")
        
        # AI処理
        context = {
            'url': url,
            'fac_id_unif': fac_id_unif,
            'content_type': 'html',
            'url_type': url_type  # 複合タイプ情報追加
        }
        
        records = self.ai_client.process_with_ai(
            processed_content,
            prompt,
            context,
            content_type="text"
        )
        
        if records:
            self.modal_stats['html_success'] += 1
            processed_records = []
            for record in records:
                processed_record = self._process_outpatient_record(record, fac_id_unif, url)
                if processed_record:
                    processed_records.append(processed_record)
            
            return processed_records
        
        raise Exception("HTML AI処理で結果なし")
    
    async def _process_as_image(self, url: str, fac_id_unif: str, prompt: str, url_type: str = '') -> List[Dict[str, Any]]:
        """画像処理"""
        self.modal_stats['image_attempts'] += 1
        
        # 画像取得
        image_data = await self.http_client.fetch_image_async(url)
        if not image_data:
            raise Exception("画像取得失敗")
        
        # 画像前処理
        processed_image = self.http_client.process_image_for_ai(image_data)
        if not processed_image:
            raise Exception("画像前処理失敗")
        
        # AI処理
        context = {
            'url': url,
            'fac_id_unif': fac_id_unif,
            'content_type': 'image',
            'url_type': url_type  # 複合タイプ情報追加
        }
        
        records = self.ai_client.process_with_ai(
            processed_image,
            prompt,
            context,
            content_type="image"
        )
        
        if records:
            self.modal_stats['image_success'] += 1
            processed_records = []
            for record in records:
                processed_record = self._process_outpatient_record(record, fac_id_unif, url)
                if processed_record:
                    processed_records.append(processed_record)
            
            return processed_records
        
        raise Exception("画像AI処理で結果なし")
    
    async def _process_as_pdf(self, url: str, fac_id_unif: str, prompt: str, url_type: str = '') -> List[Dict[str, Any]]:
        """PDF処理"""
        self.modal_stats['pdf_attempts'] += 1
        
        # PDF取得
        pdf_data = await self.http_client.fetch_pdf_async(url)
        if not pdf_data:
            raise Exception("PDF取得失敗")
        
        # PDF→画像変換
        page_images = self.http_client.convert_pdf_to_images(pdf_data)
        if not page_images:
            raise Exception("PDF変換失敗")
        
        # 各ページを処理
        all_records = []
        for i, image_data in enumerate(page_images):
            try:
                # ページ前処理
                processed_image = self.http_client.process_image_for_ai(image_data)
                if not processed_image:
                    continue
                
                # AI処理
                context = {
                    'url': url,
                    'fac_id_unif': fac_id_unif,
                    'content_type': 'pdf',
                    'page_number': i + 1,
                    'url_type': url_type  # 複合タイプ情報追加
                }
                
                records = self.ai_client.process_with_ai(
                    processed_image,
                    prompt,
                    context,
                    content_type="pdf"
                )
                
                if records:
                    for record in records:
                        processed_record = self._process_outpatient_record(record, fac_id_unif, url)
                        if processed_record:
                            all_records.append(processed_record)
                
            except Exception as e:
                self.logger.log_warning(f"PDFページ {i+1} 処理エラー: {str(e)}")
                continue
        
        if all_records:
            self.modal_stats['pdf_success'] += 1
            return all_records
        
        raise Exception("PDF AI処理で結果なし")
    
    def _contains_outpatient_keywords(self, content: str) -> bool:
        """外来担当医表キーワード含有チェック"""
        keywords = [
            '外来', '担当医', '担当表', '診療表', 'スケジュール',
            '外来担当', '診療担当', '外来スケジュール', '診療スケジュール',
            'outpatient', 'schedule', 'timetable', '診療科', '曜日'
        ]
        
        content_lower = content.lower()
        
        # 最低2つのキーワードが含まれることを要求
        keyword_count = sum(1 for keyword in keywords if keyword.lower() in content_lower)
        
        return keyword_count >= 2
    
    def _process_outpatient_record(
        self,
        record: Dict[str, Any],
        fac_id_unif: str,
        url: str
    ) -> Optional[Dict[str, Any]]:
        """外来担当医表レコード後処理"""
        try:
            # 必須フィールドチェック（診療科のみ）
            department = record.get('department', '').strip()
            doctors_name = record.get('doctors_name', '').strip()
            
            if not department:
                return None
            
            # 医師名は既にSimpleOutpatientAIClientで検証済みのためスキップ
            
            # サンプルデータ除外
            if self._is_sample_data(doctors_name, department):
                return None
            
            # 時間情報の正規化
            charge_date, specialty = self._normalize_time_info(
                record.get('charge_date', ''),
                record.get('specialty', '')
            )
            
            # タイムスタンプ設定
            current_time = self.logger.get_jst_now_str()
            
            # 外来担当医表レコード作成
            processed_record = {
                'fac_id_unif': fac_id_unif,
                'fac_nm': record.get('fac_nm', '').strip(),
                'department': department,
                'day_of_week': record.get('day_of_week', '').strip(),
                'first_followup_visit': record.get('first_followup_visit', '').strip(),
                'doctors_name': doctors_name,
                'position': record.get('position', '').strip(),
                'charge_week': record.get('charge_week', '').strip(),
                'charge_date': charge_date,
                'specialty': specialty,
                'update_date': record.get('update_date', '').strip(),
                'url_single_table': url,
                'output_datetime': current_time,
                'ai_version': self.config.ai_model
            }
            
            return processed_record
            
        except Exception as e:
            self.logger.log_error(f"外来担当医表レコード処理エラー: {str(e)}", error=e)
            return None
    
    # _is_valid_doctor_name メソッドは削除
    # SimpleOutpatientAIClient内で検証するため重複を排除
    
    def _is_sample_data(self, name: str, department: str) -> bool:
        """サンプルデータ判定"""
        sample_names = [
            '山田太郎', '佐藤一郎', '鈴木次郎', '田中三郎',
            'サンプル', 'テスト', '例', 'example'
        ]
        
        sample_departments = [
            '○○科', 'サンプル科', 'テスト科', 'example'
        ]
        
        sample_facilities = [
            '○○病院', 'サンプル病院', 'テスト病院'
        ]
        
        name_lower = name.lower()
        department_lower = department.lower()
        
        for sample in sample_names:
            if sample.lower() in name_lower:
                return True
        
        for sample in sample_departments:
            if sample.lower() in department_lower:
                return True
        
        return False
    
    def _normalize_time_info(self, charge_date: str, specialty: str) -> tuple[str, str]:
        """時間情報の正規化"""
        # specialtyに時間情報が誤って入っている場合の修正
        time_patterns = [
            r'\d{1,2}:\d{2}[〜～-]\d{1,2}:\d{2}',  # 8:30〜11:30
            r'午前', r'午後',  # 午前、午後
            r'\d{1,2}時[〜～-]\d{1,2}時',  # 8時〜11時
            r'\d{1,2}:\d{2}まで',  # 10:00まで
        ]
        
        # specialtyに時間情報が含まれている場合
        if specialty:
            for pattern in time_patterns:
                if re.search(pattern, specialty):
                    # specialtyの時間情報をcharge_dateに移動
                    if not charge_date or charge_date.strip() in ['-', '']:
                        charge_date = specialty
                        specialty = ''
                        break
        
        return charge_date.strip(), specialty.strip()
    
    def _record_composite_type_processing(self, url_type: str, url: str, record_count: int):
        """複合タイプ処理統計を記録"""
        self.composite_type_stats['total_processed'] += 1
        
        if url_type.startswith('sg_'):
            self.composite_type_stats['composite_detected'] += 1
            
            if url_type in self.composite_type_stats['types']:
                self.composite_type_stats['types'][url_type] += 1
            
            if record_count > 0:
                self.composite_type_stats['success_count'] += 1
                self.composite_type_stats['total_records_extracted'] += record_count
                
            self.logger.log_info(
                f"複合タイプ処理統計更新: {url_type} ({record_count}件抽出)",
                url_type=url_type,
                record_count=record_count,
                composite_stats=self.composite_type_stats
            )
    
    def get_composite_type_summary(self) -> Dict[str, Any]:
        """複合タイプ処理サマリーを取得"""
        total = self.composite_type_stats['total_processed']
        composite = self.composite_type_stats['composite_detected']
        
        summary = {
            'total_processed': total,
            'composite_detected': composite,
            'composite_rate': f"{(composite/total*100):.1f}%" if total > 0 else "0.0%",
            'success_rate': f"{(self.composite_type_stats['success_count']/composite*100):.1f}%" if composite > 0 else "0.0%",
            'avg_records_per_composite': f"{(self.composite_type_stats['total_records_extracted']/composite):.1f}" if composite > 0 else "0.0",
            'type_breakdown': self.composite_type_stats['types']
        }
        
        return summary
    
    def log_final_stats(self):
        """マルチモーダル統計を含む最終ログ"""
        # 基本統計
        super().log_final_stats()
        
        # マルチモーダル統計
        self.logger.log_statistics({
            'html_attempts': self.modal_stats['html_attempts'],
            'html_success': self.modal_stats['html_success'],
            'image_attempts': self.modal_stats['image_attempts'],
            'image_success': self.modal_stats['image_success'],
            'pdf_attempts': self.modal_stats['pdf_attempts'],
            'pdf_success': self.modal_stats['pdf_success']
        })
        
        # 成功率計算
        html_rate = (self.modal_stats['html_success'] / self.modal_stats['html_attempts'] * 100) if self.modal_stats['html_attempts'] > 0 else 0
        image_rate = (self.modal_stats['image_success'] / self.modal_stats['image_attempts'] * 100) if self.modal_stats['image_attempts'] > 0 else 0
        pdf_rate = (self.modal_stats['pdf_success'] / self.modal_stats['pdf_attempts'] * 100) if self.modal_stats['pdf_attempts'] > 0 else 0
        
        self.logger.log_success("マルチモーダル処理統計:")
        self.logger.log_success(f"  HTML処理: {self.modal_stats['html_success']}/{self.modal_stats['html_attempts']} ({html_rate:.1f}%)")
        self.logger.log_success(f"  画像処理: {self.modal_stats['image_success']}/{self.modal_stats['image_attempts']} ({image_rate:.1f}%)")
        self.logger.log_success(f"  PDF処理: {self.modal_stats['pdf_success']}/{self.modal_stats['pdf_attempts']} ({pdf_rate:.1f}%)")
        
        # 複合タイプ統計
        if self.composite_type_stats['total_processed'] > 0:
            summary = self.get_composite_type_summary()
            self.logger.log_info(
                "複合タイプ処理サマリー",
                summary=summary
            )



# 外来担当医表収集実行関数
def run(config: Config, logger: UnifiedLogger):
    """外来担当医表収集実行"""
    processor = OutpatientProcessor(config, logger)
    
    # マルチモーダル処理は非同期必須
    try:
        asyncio.run(processor.run_async())
    finally:
        processor.cleanup()