"""
URL収集プロセッサー

医療施設ウェブサイトから専門医・外来担当医ページのURL収集
"""

import asyncio
import re
import time
from typing import List, Dict, Any, Set, Optional
from urllib.parse import urljoin, urlparse, parse_qs
import pandas as pd

from config import Config, LOCAL_TEST
from common.logger import UnifiedLogger
from common.http_client import UnifiedHttpClient
from common.ai_client_url_simple import SimpleURLCollectAIClient
from common.utils import validate_url, extract_domain
from .base_processor import BaseProcessor
from .failure_recorder import AIFailureRecorder, FailureReasonClassifier, AlertManager
from .statistics_manager import FailureStatistics


class UrlCollectorProcessor(BaseProcessor):
    """URL収集プロセッサー"""
    
    def __init__(self, config: Config, logger: UnifiedLogger):
        super().__init__(config, logger)
        self.http_client = None
        # シンプルAIクライアントを使用
        self.ai_client = SimpleURLCollectAIClient(config, logger)
        
        # 失敗記録システムの初期化
        self.failure_recorder = AIFailureRecorder(logger)
        self.failure_statistics = FailureStatistics(self.gcs_client)
        
        # URL収集設定
        self.max_pages_per_facility = 800
        self.max_depth = 4
        self.request_interval = 0.15
        
        # 医師ページキーワード
        self.doctor_keywords = [
            '医師', 'ドクター', '先生', '専門医', '主任', '部長', '科長',
            'doctor', 'physician', 'md', 'prof', 'professor',
            '医師紹介', 'スタッフ紹介', '医師一覧', 'スタッフ一覧'
        ]
        
        # 外来担当医表キーワード
        self.schedule_keywords = [
            '外来', '担当医', '担当表', '診療表', 'スケジュール',
            '外来担当', '診療担当', '外来スケジュール', '診療スケジュール',
            'outpatient', 'schedule', 'timetable'
        ]
        
        # 除外キーワード
        self.exclude_keywords = [
            'sitemap', 'privacy', 'contact', 'access', 'map', 'faq',
            'tel:', 'mailto:', 'javascript:', '#',
            'プライバシー', '個人情報', 'お問い合わせ', 'アクセス',
            'よくある質問', 'ご質問'
        ]
        
        # 複合タイプ統計
        self.composite_type_stats = {
            'total_processed': 0,
            'composite_detected': 0,
            'types': {
                'sg_txt': 0,
                'sg_img': 0,
                'sg_pdf': 0
            },
            'urls': []  # 複合タイプのURL記録用
        }
    
    async def process_data_async(self, df: pd.DataFrame, prompt: str):
        """非同期データ処理"""
        async with UnifiedHttpClient(self.config, self.logger) as http_client:
            self.http_client = http_client
            
            # 施設ごとに処理
            progress = self.create_progress_tracker(len(df))
            
            for _, row in df.iterrows():
                fac_id_unif = str(row['fac_id_unif'])
                base_url = row['URL']
                
                try:
                    # 施設のURL収集
                    urls = await self._crawl_facility_async(fac_id_unif, base_url)
                    
                    # AI分類
                    if urls:
                        classified_urls = await self._classify_urls_async(urls, prompt, fac_id_unif)
                        self._record_success(classified_urls)
                    else:
                        self._record_failure({'fac_id_unif': fac_id_unif, 'URL': base_url}, "URL収集失敗")
                    
                except Exception as e:
                    self.logger.log_error(f"施設処理エラー: {fac_id_unif}", error=e)
                    self._record_failure({'fac_id_unif': fac_id_unif, 'URL': base_url}, str(e))
                
                progress.update()
                
                # 定期統計ログ出力
                if hasattr(self, 'failure_statistics') and progress.current % self.config.failure_statistics_log_interval == 0:
                    stats = self.failure_statistics.get_statistics()
                    self.logger.log_statistics({
                        'processed_count': stats.total_processed,
                        'success_count': stats.ai_success_count,
                        'failure_count': stats.ai_failure_count,
                        'success_rate': f"{stats.ai_success_rate:.3f}",
                        'failure_breakdown': dict(list(stats.failure_breakdown.items())[:5])  # 上位5件の失敗理由
                    })
                
                # メモリクリーンアップ
                if progress.current % 5 == 0:
                    self.cleanup()
    
    def process_data_sync(self, df: pd.DataFrame, prompt: str):
        """同期データ処理"""
        # 非同期処理を同期実行
        asyncio.run(self.process_data_async(df, prompt))
    
    def process_single_item(self, item: Dict[str, Any], prompt: str) -> List[Dict[str, Any]]:
        """単一アイテム処理（同期版）"""
        # このメソッドはURL収集では使用しない（施設単位処理のため）
        return []
    
    async def _crawl_facility_async(self, fac_id_unif: str, base_url: str) -> List[str]:
        """施設の非同期クローリング"""
        if LOCAL_TEST:
            return self._generate_mock_urls(fac_id_unif, base_url)
        
        self.logger.log_info(f"施設クローリング開始: {fac_id_unif}", fac_id_unif=fac_id_unif, base_url=base_url)
        
        visited_urls = set()
        found_urls = set()
        url_queue = [(base_url, 0)]  # (url, depth)
        
        domain = extract_domain(base_url)
        page_count = 0
        
        while url_queue and page_count < self.max_pages_per_facility:
            current_url, depth = url_queue.pop(0)
            
            if current_url in visited_urls or depth > self.max_depth:
                continue
            
            if not self._should_crawl_url(current_url, domain):
                continue
            
            try:
                # HTML取得
                html_content = await self.http_client.fetch_html_async(current_url)
                if not html_content:
                    continue
                
                visited_urls.add(current_url)
                page_count += 1
                
                # URL抽出
                page_urls = self._extract_urls_from_html(html_content, current_url, domain)
                
                # 医師・外来ページの判定
                if self._is_doctor_or_schedule_page(html_content, current_url):
                    found_urls.add(current_url)
                    self.logger.log_info(f"対象ページ発見: {current_url}")
                
                # 新しいURLをキューに追加
                for url in page_urls:
                    if url not in visited_urls and depth + 1 <= self.max_depth:
                        url_queue.append((url, depth + 1))
                
                # リクエスト間隔調整
                await asyncio.sleep(self.request_interval)
                
            except Exception as e:
                self.logger.log_warning(f"ページ取得エラー: {current_url}", error=e)
                continue
        
        result_urls = list(found_urls)
        self.logger.log_success(
            f"施設クローリング完了: {fac_id_unif}",
            fac_id_unif=fac_id_unif,
            pages_crawled=page_count,
            urls_found=len(result_urls)
        )
        
        return result_urls
    
    def _extract_urls_from_html(self, html_content: str, base_url: str, domain: str) -> List[str]:
        """HTMLからURL抽出"""
        urls = []
        
        # aタグのhref属性を抽出
        href_pattern = r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>'
        matches = re.findall(href_pattern, html_content, re.IGNORECASE)
        
        for match in matches:
            # 相対URLを絶対URLに変換
            absolute_url = urljoin(base_url, match.strip())
            
            if self._should_crawl_url(absolute_url, domain):
                urls.append(absolute_url)
        
        return list(set(urls))  # 重複除去
    
    def _should_crawl_url(self, url: str, allowed_domain: str) -> bool:
        """クローリング対象URLか判定"""
        if not validate_url(url):
            return False
        
        # ドメインチェック
        url_domain = extract_domain(url)
        if url_domain != allowed_domain:
            return False
        
        # 除外キーワードチェック
        url_lower = url.lower()
        for keyword in self.exclude_keywords:
            if keyword in url_lower:
                return False
        
        # ファイル拡張子チェック
        if re.search(r'\\.(pdf|doc|docx|xls|xlsx|zip|jpg|jpeg|png|gif)$', url_lower):
            return False
        
        return True
    
    def _has_doctor_info(self, html_content: str, url: str) -> bool:
        """医師情報が含まれているかチェック"""
        content_lower = html_content.lower()
        url_lower = url.lower()
        
        # 医師情報の特徴的なパターン
        doctor_patterns = [
            r'(経歴|学歴|資格|専門医|認定医|学位|博士|修士)',
            r'(卒業|研修|勤務|着任|就任)',
            r'(専門分野|診療分野|得意分野)'
        ]
        
        # HTMLコンテンツでのマッチング
        has_doctor_content = any(re.search(pattern, content_lower) for pattern in doctor_patterns)
        
        # URL パターンでのマッチング
        doctor_url_patterns = [
            r'/doctor', r'/physician', r'/staff', r'/ishi', r'/senmon',
            r'/doctors', r'/medical_staff'
        ]
        has_doctor_url = any(re.search(pattern, url_lower) for pattern in doctor_url_patterns)
        
        return has_doctor_content or has_doctor_url
    
    def _get_schedule_type(self, html_content: str, url: str) -> Optional[str]:
        """外来担当医表の種別を判定"""
        content_lower = html_content.lower()
        url_lower = url.lower()
        
        # HTML形式のテーブル
        if re.search(r'<table.*?>(.*?曜日.*?)</table>', content_lower, re.DOTALL):
            return 'txt'
        
        # 画像形式
        if re.search(r'<img.*?src=.*?(schedule|tantou|gairai)', content_lower):
            return 'img'
        
        # PDF形式
        if re.search(r'<a.*?href=.*?\.(pdf).*?>(.*?担当|.*?外来)', content_lower):
            return 'pdf'
        
        # URLパターンでの判定
        schedule_url_patterns = [
            r'/outpatient', r'/gairai', r'/schedule', r'/tantou'
        ]
        
        if any(re.search(pattern, url_lower) for pattern in schedule_url_patterns):
            # URL にスケジュール関連があるが、具体的な形式が不明な場合はtxtとしてデフォルト
            return 'txt'
        
        return None
    
    def detect_composite_type(self, html_content: str, url: str) -> Optional[str]:
        """複合タイプを検出"""
        # 機能が無効の場合は何もしない
        if not self.config.enable_composite_type:
            return None
        
        # 医師情報と外来担当医表の両方をチェック
        has_doctor_info = self._has_doctor_info(html_content, url)
        schedule_type = self._get_schedule_type(html_content, url)
        
        # 両方が存在する場合のみ複合タイプ
        if has_doctor_info and schedule_type:
            composite_type = f"sg_{schedule_type}"
            self.logger.log_info(
                f"複合タイプ検出: {url}",
                doctor_info_detected=has_doctor_info,
                schedule_type=schedule_type,
                composite_type=composite_type
            )
            return composite_type
        
        return None
    
    def _apply_priority_rules(self, types: List[str]) -> str:
        """優先順位ルールに従ってタイプを選択"""
        if not types:
            return 'none'
        
        # 設定から優先順位を取得
        priority_map = {t: i for i, t in enumerate(self.config.composite_type_priority)}
        
        # 複合タイプの優先順位も定義
        composite_priority = {
            'sg_txt': 0.5,  # s と g_txt の間
            'sg_img': 2.5,  # g_txt と g_img の間  
            'sg_pdf': 3.5   # g_img と g_pdf の間
        }
        
        def get_priority(type_code):
            if type_code in priority_map:
                return priority_map[type_code]
            elif type_code in composite_priority:
                return composite_priority[type_code]
            else:
                return 999  # 不明なタイプは最低優先度
        
        return min(types, key=get_priority)
    
    def _validate_type_code(self, type_code: str) -> str:
        """タイプコードの検証と正規化"""
        # 有効なタイプコード一覧
        valid_types = {
            's', 'g_txt', 'g_img', 'g_pdf', 'none',
            'sg_txt', 'sg_img', 'sg_pdf'  # 複合タイプ
        }
        
        if type_code in valid_types:
            return type_code
        
        # 不正なタイプコードの場合はデフォルトに
        self.logger.log_warning(f"不正なタイプコード検出、デフォルトに修正: {type_code} -> s")
        return 's'
    
    def _record_composite_type(self, type_code: str, url: str):
        """複合タイプの統計を記録"""
        self.composite_type_stats['total_processed'] += 1
        
        if type_code.startswith('sg_'):
            self.composite_type_stats['composite_detected'] += 1
            
            if type_code in self.composite_type_stats['types']:
                self.composite_type_stats['types'][type_code] += 1
            
            # URL記録（最大100件まで）
            if len(self.composite_type_stats['urls']) < 100:
                self.composite_type_stats['urls'].append({
                    'url': url,
                    'type': type_code
                })
    
    def _log_composite_statistics(self):
        """複合タイプの統計をログ出力"""
        stats = self.composite_type_stats
        total = stats['total_processed']
        detected = stats['composite_detected']
        
        if total > 0:
            detection_rate = (detected / total) * 100
            
            self.logger.log_info(
                f"複合タイプ統計: 処理数={total}, 検出数={detected}, 検出率={detection_rate:.1f}%",
                total_processed=total,
                composite_detected=detected,
                detection_rate_percent=detection_rate,
                sg_txt_count=stats['types']['sg_txt'],
                sg_img_count=stats['types']['sg_img'],
                sg_pdf_count=stats['types']['sg_pdf']
            )
            
            # 複合タイプのURLサンプルを出力
            if stats['urls']:
                sample_urls = stats['urls'][:5]  # 最初の5件
                self.logger.log_info(f"複合タイプURL例: {sample_urls}")
    
    def _is_doctor_or_schedule_page(self, html_content: str, url: str) -> bool:
        """医師・外来担当医ページか判定"""
        content_lower = html_content.lower()
        url_lower = url.lower()
        
        # URLパターンチェック
        doctor_url_patterns = [
            r'/doctor', r'/physician', r'/staff', r'/ishi', r'/senmon',
            r'/doctors', r'/medical_staff', r'/guide/', r'/dept/',
            r'/department', r'/shinryo', r'/clinic'
        ]
        
        schedule_url_patterns = [
            r'/outpatient', r'/gairai', r'/schedule', r'/tantou',
            r'/timetable', r'/calendar', r'/guide/', r'/dept/'
        ]
        
        # 診療科名パターン（日本語）
        department_patterns = [
            r'naika', r'geka', r'shouka', r'seikei', r'jibi', r'ganka',
            r'hinyou', r'shounika', r'sanka', r'fujinka', r'seishin',
            r'hoshasen', r'masui', r'byouri', r'kyuukyuu', r'rehab'
        ]
        
        # URL判定
        for pattern in doctor_url_patterns + schedule_url_patterns + department_patterns:
            if re.search(pattern, url_lower):
                return True
        
        # コンテンツ判定
        doctor_score = sum(1 for keyword in self.doctor_keywords if keyword.lower() in content_lower)
        schedule_score = sum(1 for keyword in self.schedule_keywords if keyword.lower() in content_lower)
        
        # 診療科関連の追加スコア
        dept_keywords = ['診療科', '外来', '医師', '担当医', '専門医', 'スタッフ']
        dept_score = sum(1 for keyword in dept_keywords if keyword in content_lower)
        
        # より緩い閾値による判定（いずれかの条件を満たせばOK）
        if (doctor_score >= 1 or 
            schedule_score >= 1 or 
            dept_score >= 2 or
            ('医師' in content_lower and '診療' in content_lower) or
            ('担当医' in content_lower) or
            ('専門医' in content_lower)):
            return True
        
        return False
    
    async def _classify_urls_async(self, urls: List[str], prompt: str, fac_id_unif: str) -> List[Dict[str, Any]]:
        """URL分類"""
        classified_results = []
        
        for url in urls:
            try:
                # URL分類（単一レコードを返す）
                classification = await self._classify_single_url_async(url, prompt, fac_id_unif)
                if classification:
                    classified_results.append(classification)
                    
            except Exception as e:
                self.logger.log_error(f"URL分類エラー: {url}", error=e)
        
        return classified_results
    
    async def _classify_single_url_async(self, url: str, prompt: str, fac_id_unif: str) -> Optional[Dict[str, Any]]:
        """単一URL分類"""
        try:
            # HTML取得
            html_content = await self.http_client.fetch_html_async(url)
            if not html_content:
                return None
            
            # HTML前処理
            processed_content = self.http_client.preprocess_html(html_content)
            
            # 複合タイプ検出を先に実行
            composite_type = self.detect_composite_type(html_content, url)
            
            # タイトル抽出
            import re
            title_match = re.search(r'<title>([^<]+)</title>', html_content, re.IGNORECASE)
            page_title = title_match.group(1).strip() if title_match else ''
            
            # AI分類処理用のコンテキスト情報を強化
            enhanced_prompt = f"""
{prompt}

【分析対象の情報】
- 分析対象URL: {url}
- fac_id_unif: {fac_id_unif}
- ページタイトル: {page_title}

【重要】URLフィールドには必ず「{url}」を使用してください。

【HTMLコンテンツ】
{processed_content[:50000]}  # 50KB制限
"""
            
            # AI処理実行
            response = self._call_ai_for_classification(processed_content, enhanced_prompt, fac_id_unif, url)
            
            if response:
                # 複合タイプが検出されている場合は優先する
                if composite_type:
                    response['type'] = composite_type
                
                # 統計を記録
                self._record_composite_type(response['type'], url)
                return response
            
        except Exception as e:
            self.logger.log_error(f"URL分類処理エラー: {url}", error=e)
        
        return None
    
    def _call_ai_for_classification(self, content: str, prompt: str, fac_id_unif: str, url: str) -> Optional[Dict[str, Any]]:
        """AI呼び出しと応答解析"""
        try:
            # AI分類処理用のコンテキスト
            context = {
                'fac_id_unif': fac_id_unif,
                'url': url
            }
            
            self.logger.log_info(f"AI分類開始: {url}", **context)
            
            # AI処理実行
            records = self.ai_client.process_with_ai(
                content,
                prompt,
                context,
                content_type="text"
            )
            
            if records and len(records) > 0:
                # 最初のレコードのみ使用（1ページ1レコード原則）
                record = records[0]
                current_time = self.logger.get_jst_now_iso()
                
                # タイプコードの検証と正規化
                raw_type = record.get('type', 's')
                validated_type = self._validate_type_code(raw_type)
                
                # 旧システム形式に合わせて整形
                result = {
                    'fac_id_unif': fac_id_unif,
                    'url': url,  # 実際のURLを強制使用（AIが返したURLは無視）
                    'type': validated_type,
                    'department': record.get('department', '診療科不明'),
                    'page_title': record.get('page_title', ''),
                    'update_datetime': current_time,
                    'ai_version': self.config.ai_model
                }
                
                if len(records) > 1:
                    self.logger.log_warning(f"AI分類で複数レコード検出、最初の1件のみ使用: {url}")
                
                self.logger.log_success(f"AI分類完了: {url} -> {result['type']}", **context)
                
                # 成功統計を更新
                self.failure_statistics.update_success(validated_type)
                
                return result
            else:
                # AI処理結果なし - 透明性のある失敗記録
                failure_reason = "EMPTY_RESPONSE"
                error_details = "AI処理は完了したが結果レコードが空"
                
                # 失敗記録システムを使用して記録
                failure_record = self.failure_recorder.record_failure(url, fac_id_unif, failure_reason, error_details)
                self.failure_statistics.update_failure(failure_record)
                
                return None
            
        except Exception as e:
            # AI処理エラー - 透明性のある失敗記録
            failure_reason = FailureReasonClassifier.classify(e)
            error_details = str(e)
            
            # 失敗記録システムを使用して記録
            failure_record = self.failure_recorder.record_failure(url, fac_id_unif, failure_reason, error_details)
            self.failure_statistics.update_failure(failure_record)
            
            return None
    
    
    
    
    def _generate_mock_urls(self, fac_id_unif: str, base_url: str) -> List[str]:
        """モックURL生成（ローカルテスト用）"""
        domain = extract_domain(base_url)
        
        mock_urls = [
            f"https://{domain}/doctors/",
            f"https://{domain}/staff/",
            f"https://{domain}/outpatient/schedule",
            f"https://{domain}/medical/staff",
            f"https://{domain}/department/internal"
        ]
        
        self.logger.log_info(f"モックURL生成: {len(mock_urls)}件", fac_id_unif=fac_id_unif)
        return mock_urls
    
    def cleanup(self):
        """リソースクリーンアップ（複合タイプ統計出力を含む）"""
        try:
            # 複合タイプ統計を出力
            self._log_composite_statistics()
            
            # 失敗統計の永続化とアラートチェック
            if hasattr(self, 'failure_statistics'):
                # 最終統計をログに出力
                stats = self.failure_statistics.get_statistics()
                self.logger.log_statistics({
                    'total_processed': stats.total_processed,
                    'ai_success_count': stats.ai_success_count,
                    'ai_failure_count': stats.ai_failure_count,
                    'ai_success_rate': f"{stats.ai_success_rate:.3f}",
                    'failure_breakdown': stats.failure_breakdown,
                    'composite_type_stats': stats.composite_type_stats
                })
                
                # 統計をGCSに永続化
                self.failure_statistics.persist_statistics()
                
                # アラートチェック
                alert_manager = AlertManager(self.logger, self.config)
                alert_manager.check_and_alert(stats)
            
            # 基底クラスのクリーンアップを呼び出し
            super().cleanup()
            
        except Exception as e:
            self.logger.log_warning(f"クリーンアップエラー: {str(e)}", error=e)


# URL収集実行関数
def run(config: Config, logger: UnifiedLogger):
    """URL収集実行"""
    processor = UrlCollectorProcessor(config, logger)
    
    # 非同期処理を推奨（環境変数で制御可能）
    import os
    use_async = os.getenv("USE_ASYNC", "true").lower() == "true"
    
    try:
        if use_async:
            asyncio.run(processor.run_async())
        else:
            processor.run_sync()
            
    finally:
        processor.cleanup()