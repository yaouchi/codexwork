"""
専門医情報収集プロセッサー

医師情報ページから専門医情報を抽出してTSV形式で出力
"""

import asyncio
import re
from typing import List, Dict, Any, Optional
import pandas as pd

from config import Config, LOCAL_TEST
from common.logger import UnifiedLogger
from common.http_client import UnifiedHttpClient
from common.ai_client import UnifiedAIClient
from common.ai_client_simple import SimpleDoctorInfoAIClient
from common.utils import validate_url, ProcessingResult
from .base_processor import BaseProcessor


class DoctorInfoProcessor(BaseProcessor):
    """専門医情報収集プロセッサー"""
    
    def __init__(self, config: Config, logger: UnifiedLogger):
        super().__init__(config, logger)
        self.http_client = None
        # シンプルAIクライアントを使用
        self.ai_client = SimpleDoctorInfoAIClient(config, logger)
        
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
            
            # バッチサイズ
            batch_size = 20  # 大学病院1000医師対応で少なめ
            
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
                    
                    # バッチ間隔
                    await asyncio.sleep(0.5)
                    
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
        # 同期版の実装（後方互換性）
        progress = self.create_progress_tracker(len(df))
        
        for _, row in df.iterrows():
            item = {
                'fac_id_unif': str(row['fac_id_unif']),
                'url': row['URL'],
                'type': row.get('type', '')  # 複合タイプサポート
            }
            
            try:
                result = self.process_single_item(item, prompt)
                self._record_success(result)
                
            except Exception as e:
                self._record_failure(item, str(e))
            
            progress.update()
    
    def process_single_item(self, item: Dict[str, Any], prompt: str) -> List[Dict[str, Any]]:
        """単一アイテム処理（同期版）"""
        # 非同期コンテキスト内では直接非同期メソッドを呼べないため、
        # 空のリストを返し、実際の処理は process_batch_async で行う
        return []
    
    async def _process_batch_async_custom(self, batch_items: List[Dict[str, Any]], prompt: str):
        """カスタムバッチ非同期処理（doctor_info専用）"""
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
        """単一URL非同期処理"""
        url = item['url']
        fac_id_unif = item['fac_id_unif']
        url_type = item.get('type', '')  # 複合タイプサポート
        
        # URL妥当性チェック
        if not validate_url(url):
            raise ValueError(f"無効なURL: {url}")
        
        # 複合タイプ検出ログ
        if url_type.startswith('sg_'):
            self.logger.log_info(
                f"複合タイプURL処理開始: {fac_id_unif} (type: {url_type})", 
                url=url, 
                fac_id_unif=fac_id_unif,
                url_type=url_type
            )
        else:
            self.logger.log_info(f"医師情報処理開始: {fac_id_unif}", url=url, fac_id_unif=fac_id_unif)
        
        # HTML取得
        html_content = await self.http_client.fetch_html_async(url)
        if not html_content:
            raise Exception("HTML取得に失敗")
        
        # HTML前処理
        processed_content = self.http_client.preprocess_html(html_content)
        if not processed_content.strip():
            raise Exception("HTML前処理後にコンテンツが空")
        
        # 複合タイプ対応の追加コンテキスト
        context = {
            'url': url,
            'fac_id_unif': fac_id_unif,
            'url_type': url_type  # 複合タイプ情報を追加
        }
        
        # プロンプトに複合タイプ情報を追加
        enhanced_prompt = prompt
        if url_type.startswith('sg_'):
            enhanced_prompt = prompt + f"\n\n注意: このページは複合タイプ({url_type})と判定されています。医師情報と外来担当医表の両方が含まれている可能性があります。医師情報の抽出に集中してください。"
        
        # シンプルプロンプトを使用
        records = self.ai_client.process_with_ai(
            processed_content,
            enhanced_prompt,
            context,
            content_type="text"
        )
        
        # HTML照合による架空レコード除去
        validated_records = self._validate_records_against_html(records, processed_content)
        
        # 重複除去処理
        processed_records = self._remove_duplicate_records(validated_records)
        
        # 複合タイプ統計更新
        if url_type.startswith('sg_'):
            self._record_composite_type_processing(url_type, url, len(processed_records))
        
        log_message = f"医師情報処理完了: {len(processed_records)}件"
        if url_type.startswith('sg_'):
            log_message = f"複合タイプ医師情報処理完了: {len(processed_records)}件 (type: {url_type})"
        
        self.logger.log_success(
            log_message,
            url=url,
            fac_id_unif=fac_id_unif,
            record_count=len(processed_records),
            url_type=url_type
        )
        
        return processed_records
    
    def _process_doctor_record(
        self,
        record: Dict[str, Any],
        fac_id_unif: str,
        url: str,
        output_order: int
    ) -> Optional[Dict[str, Any]]:
        """医師レコード後処理"""
        try:
            # 必須フィールドチェック
            name = record.get('name', '').strip()
            department = record.get('department', '').strip()
            
            if not name or not department:
                self.logger.log_warning(f"必須フィールド不足: name={name}, department={department}")
                return None
            
            # 医師名妥当性チェック
            if not self._is_valid_doctor_name(name):
                self.logger.log_warning(f"無効な医師名: {name}")
                return None
            
            # サンプルデータ除外
            if self._is_sample_data(name, department):
                self.logger.log_warning(f"サンプルデータ除外: {name}, {department}")
                return None
            
            # タイムスタンプ設定
            current_time = self.logger.get_jst_now_str()
            
            # フィールドのプレースホルダーチェック
            position = record.get('position', '').strip()
            specialty = record.get('specialty', '').strip()
            licence = record.get('licence', '').strip()
            others = record.get('others', '').strip()
            
            # プレースホルダーが検出された場合は空欄化
            if self._contains_placeholder(position):
                position = ''
                self.logger.log_warning(f"プレースホルダー検出により空欄化: position={record.get('position', '')}")
                
            if self._contains_placeholder(specialty):
                specialty = ''
                self.logger.log_warning(f"プレースホルダー検出により空欄化: specialty={record.get('specialty', '')}")
                
            if self._contains_placeholder(licence):
                licence = ''
                self.logger.log_warning(f"プレースホルダー検出により空欄化: licence={record.get('licence', '')}")
                
            if self._contains_placeholder(others):
                others = ''
                self.logger.log_warning(f"プレースホルダー検出により空欄化: others={record.get('others', '')}")
            
            # 専門医情報レコード作成
            processed_record = {
                'fac_id_unif': fac_id_unif,
                'output_order': f"{fac_id_unif}_{output_order:05d}",
                'department': department,
                'name': name,
                'position': position,
                'specialty': specialty,
                'licence': licence,
                'others': others,
                'output_datetime': current_time,
                'ai_version': self.config.ai_model,
                'url': url
            }
            
            return processed_record
            
        except Exception as e:
            self.logger.log_error(f"レコード処理エラー: {str(e)}", error=e)
            return None
    
    def _is_valid_doctor_name(self, name: str) -> bool:
        """医師名妥当性チェック"""
        if not name or len(name.strip()) < 2:
            return False
        
        # 診療科名パターン（医師名から除外）- より精密なパターンに修正
        department_patterns = [
            # 完全一致の診療科名
            r'^内科$', r'^外科$', r'^小児科$', r'^産婦人科$',
            r'^眼科$', r'^耳鼻咽喉科$', r'^皮膚科$', r'^泌尿器科$',
            r'^整形外科$', r'^脳神経外科$', r'^形成外科$', r'^精神科$',
            r'^放射線科$', r'^麻酔科$', r'^病理診断科$', r'^救急科$',
            # 特定の内科・外科系
            r'^循環器内科$', r'^消化器内科$', r'^呼吸器内科$', r'^神経内科$',
            r'^消化器外科$', r'^呼吸器外科$', r'^心臓血管外科$',
            # 明らかに診療科名のパターン（医師名ではありえない）
            r'^.{3,}内科$', r'^.{3,}外科$', r'^.{4,}科$'
        ]
        
        name_clean = name.strip()
        for pattern in department_patterns:
            if re.match(pattern, name_clean):
                return False
        
        # 偽データパターン
        fake_patterns = [
            r'山田.*太郎', r'佐藤.*花子', r'鈴木.*一郎',
            r'田中.*三郎', r'高橋.*次郎', r'田中.*一郎',
            r'伊藤.*四郎', r'渡辺.*五郎', r'斉藤.*六郎',
            r'〇〇', r'○○', r'^〇+$', r'^○+$'
        ]
        
        for pattern in fake_patterns:
            if re.match(pattern, name_clean):
                return False
        
        return True
    
    def _contains_placeholder(self, text: str) -> bool:
        """プレースホルダーが含まれているかチェック"""
        if not text:
            return False
        
        placeholder_patterns = [
            r'〇〇', r'○○', r'△△',  # 記号パターン
            r'○○大学', r'〇〇大学', r'△△大学',  # 大学パターン
            r'[〇○△]+大学', r'[〇○△]{2,}',  # 複数記号
        ]
        
        for pattern in placeholder_patterns:
            if re.search(pattern, text):
                return True
        
        return False
    
    def _normalize_text(self, text: str) -> str:
        """テキストの正規化（表記揺れ対応）"""
        if not text:
            return ""
        
        import re
        # 全角・半角スペースの統一
        text = re.sub(r'[\s\u3000]+', ' ', text)
        # 句読点の統一
        text = text.replace('，', ',').replace('。', '.')
        # 前後の空白除去
        text = text.strip()
        
        return text
    
    def _validate_field_in_html(self, field_value: str, html_content: str) -> bool:
        """フィールド値がHTMLに含まれているかチェック"""
        if not field_value or not field_value.strip():
            return True  # 空欄は有効
        
        field_normalized = self._normalize_text(field_value)
        html_normalized = self._normalize_text(html_content)
        
        # 直接一致チェック
        if field_normalized in html_normalized:
            return True
        
        # 部分一致チェック（短い文字列の場合は厳格に）
        if len(field_normalized) >= 3:
            # 3文字以上の場合は部分一致も許可
            words = field_normalized.split()
            return all(word in html_normalized for word in words if len(word) >= 2)
        
        return False
    
    def _validate_records_against_html(self, records: List[Dict], html_content: str) -> List[Dict]:
        """HTMLに存在しない情報を含むレコードを除外または修正"""
        if not records:
            return records
        
        valid_records = []
        
        for record in records:
            # 各フィールドのHTML存在チェック
            validation_result = {
                'name': self._validate_field_in_html(record.get('name', ''), html_content),
                'department': self._validate_field_in_html(record.get('department', ''), html_content),
                'position': self._validate_field_in_html(record.get('position', ''), html_content),
                'specialty': self._validate_field_in_html(record.get('specialty', ''), html_content),
                'licence': self._validate_field_in_html(record.get('licence', ''), html_content),
                'others': self._validate_field_in_html(record.get('others', ''), html_content)
            }
            
            # 重要項目（name, department）が無効なら除外
            if not validation_result['name'] or not validation_result['department']:
                self.logger.log_warning(
                    f"HTMLに存在しない重要項目を含むレコードを除外: "
                    f"name={record.get('name')}, department={record.get('department')}"
                )
                continue
            
            # その他項目が無効なら空欄化
            cleaned_record = record.copy()
            for field, is_valid in validation_result.items():
                if not is_valid and field not in ['name', 'department']:
                    original_value = cleaned_record.get(field, '')
                    cleaned_record[field] = ''
                    if original_value:
                        self.logger.log_warning(
                            f"HTMLに存在しない{field}を空欄化: {original_value} "
                            f"(医師: {record.get('name')})"
                        )
            
            valid_records.append(cleaned_record)
        
        # 除外されたレコード数をログ出力
        excluded_count = len(records) - len(valid_records)
        if excluded_count > 0:
            self.logger.log_info(f"HTML照合により{excluded_count}件のレコードを除外しました")
        
        return valid_records
    
    def _create_record_signature(self, record: Dict) -> str:
        """レコードの重複判定用シグネチャを作成"""
        # 連番(output_order)と時間(output_datetime)を除く主要項目でシグネチャ作成
        signature_fields = [
            self._normalize_text(record.get('department', '')),
            self._normalize_text(record.get('name', '')),
            self._normalize_text(record.get('position', '')),
            self._normalize_text(record.get('specialty', '')),
            self._normalize_text(record.get('licence', '')),
            self._normalize_text(record.get('others', ''))
        ]
        
        # タブ区切りでシグネチャ作成
        signature = '\t'.join(signature_fields)
        return signature
    
    def _remove_duplicate_records(self, records: List[Dict]) -> List[Dict]:
        """重複レコードを除去（連番・時間を除いたDISTINCT処理）"""
        if not records:
            return records
        
        seen_signatures = set()
        unique_records = []
        duplicate_count = 0
        
        for record in records:
            signature = self._create_record_signature(record)
            
            if signature not in seen_signatures:
                seen_signatures.add(signature)
                unique_records.append(record)
            else:
                duplicate_count += 1
                self.logger.log_warning(
                    f"重複レコードを除去: {record.get('name')} "
                    f"({record.get('department')}, {record.get('position')})"
                )
        
        # 重複除去の統計をログ出力
        if duplicate_count > 0:
            self.logger.log_info(
                f"重複除去完了: {duplicate_count}件の重複レコードを除去 "
                f"({len(records)}件 → {len(unique_records)}件)"
            )
        
        return unique_records
    
    def _is_sample_data(self, name: str, department: str) -> bool:
        """サンプルデータ判定"""
        sample_names = [
            '山田太郎', '佐藤一郎', '鈴木次郎', '田中三郎',
            'サンプル', 'テスト', '例', 'example'
        ]
        
        sample_departments = [
            '○○科', 'サンプル科', 'テスト科', 'example'
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




# 専門医情報収集実行関数
def run(config: Config, logger: UnifiedLogger):
    """専門医情報収集実行"""
    processor = DoctorInfoProcessor(config, logger)
    
    # 非同期処理を推奨（大学病院1000医師対応）
    import os
    use_async = os.getenv("USE_ASYNC", "true").lower() == "true"
    
    try:
        if use_async:
            asyncio.run(processor.run_async())
        else:
            processor.run_sync()
            
    finally:
        # 複合タイプサマリー出力
        if hasattr(processor, 'composite_type_stats') and processor.composite_type_stats['total_processed'] > 0:
            summary = processor.get_composite_type_summary()
            logger.log_info(
                "複合タイプ処理サマリー",
                summary=summary
            )
        
        processor.cleanup()