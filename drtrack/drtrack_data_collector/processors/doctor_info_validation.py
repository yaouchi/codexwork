"""
医師情報検証プロセッサ（独立実装版）

doctor_info.pyの出力TSVを検証し、品質向上を図る
doctor_info.pyと同じパターンで実装
"""

import os
import io
import re
import asyncio
import pandas as pd
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import time
import google.generativeai as genai

from config import Config, LOCAL_TEST
from common.logger import UnifiedLogger
from common.gcs_client import UnifiedGCSClient
from common.ai_client import UnifiedAIClient
from common.http_client import UnifiedHttpClient


@dataclass
class ValidationResult:
    """検証結果"""
    validation_status: str
    validation_message: str
    corrected_name: str
    corrected_department: str
    corrected_position: str
    corrected_specialty: str
    corrected_licence: str
    corrected_others: str
    
    # デバッグフィールド
    ai_response_raw: str = ""
    parsing_attempts: List[str] = field(default_factory=list)
    html_excerpt: str = ""
    processing_time: float = 0.0


class DoctorInfoValidationProcessor:
    """医師情報検証プロセッサ（独立実装）"""
    
    def __init__(self, config: Config, logger: UnifiedLogger):
        self.config = config
        self.logger = logger
        
        # クライアント初期化
        self.gcs_client = UnifiedGCSClient(config, logger)
        self.ai_client = UnifiedAIClient(config, logger)
        self.http_client = None
        
        # 設定値（環境変数から取得可能）
        self.batch_size = int(os.getenv('VALIDATION_BATCH_SIZE', '5'))
        self.max_chars = int(os.getenv('VALIDATION_MAX_CHARS', '30000'))
        # AI温度を0.0に設定して完全に決定的な出力にする
        self.ai_temperature = float(os.getenv('VALIDATION_AI_TEMPERATURE', '0.0'))
        self.debug_mode = os.getenv('VALIDATION_DEBUG_MODE', 'true').lower() == 'true'
        
        # 処理結果
        self.all_records = []
        self.validation_stats = {
            'total_processed': 0,
            'valid_count': 0,
            'partial_count': 0,
            'invalid_count': 0,
            'notfound_count': 0,
            'parsing_failures': 0,
            'processing_errors': 0,
            'natural_language_extractions': 0  # 自然言語抽出の使用回数を追跡
        }
    
    async def run_async(self):
        """非同期実行エントリーポイント"""
        try:
            self.logger.log_info("=== 医師情報検証処理開始（独立実装版） ===")
            
            # doctor_info フォルダのTSVファイルを読み込み
            input_data = await self._read_tsv_files_from_gcs()
            
            if input_data.empty:
                self.logger.log_warning("処理対象データがありません")
                return
            
            # タスク分割
            task_data = self.gcs_client.get_task_data(input_data)
            self.logger.log_info(f"検証対象: {len(task_data)}件")
            
            # プロンプト読み込み
            prompt = await self._read_prompt_from_gcs()
            
            # HTTP Clientを使用した非同期処理（doctor_info.pyパターン）
            async with UnifiedHttpClient(self.config, self.logger) as http_client:
                self.http_client = http_client
                
                # バッチ処理で検証実行
                for i in range(0, len(task_data), self.batch_size):
                    batch_df = task_data.iloc[i:i + self.batch_size]
                    await self._process_batch_async(batch_df, prompt)
                    
                    self.logger.log_info(f"バッチ {i // self.batch_size + 1} 完了: {len(batch_df)}件")
                    
                    # バッチ間隔
                    await asyncio.sleep(0.5)
            
            # 結果保存
            if self.all_records:
                await self._save_validation_results()
            
            self._log_final_statistics()
            self.logger.log_info("=== 医師情報検証処理完了 ===")
            
        except Exception as e:
            self.logger.log_error(f"医師情報検証処理でエラーが発生: {str(e)}")
            raise
    
    def run_sync(self):
        """同期実行"""
        return asyncio.run(self.run_async())
    
    async def _read_tsv_files_from_gcs(self) -> pd.DataFrame:
        """GCSからdoctor_info/tsv/のTSVファイルを読み込み"""
        try:
            # doctor_info フォルダのTSVファイルを取得
            bucket_name = self.config.input_bucket
            prefix = 'doctor_info/tsv/'
            
            # GCSクライアントを直接使用してファイル一覧を取得
            bucket = self.gcs_client.storage_client.bucket(bucket_name)
            blobs = [blob.name for blob in bucket.list_blobs(prefix=prefix)]
            
            all_data = []
            for blob_name in blobs:
                if blob_name.endswith('.tsv'):
                    # GCSから直接ダウンロード
                    blob = bucket.blob(blob_name)
                    content = blob.download_as_text(encoding='utf-8')
                    
                    # TSVをDataFrameに変換
                    df = pd.read_csv(
                        io.StringIO(content),
                        sep='\t',
                        dtype=str,
                        na_filter=False
                    )
                    
                    if not df.empty:
                        all_data.append(df)
                        self.logger.log_info(f"TSVファイル読み込み: {blob_name} ({len(df)}行)")
            
            if not all_data:
                self.logger.log_warning("読み込み可能なTSVファイルが見つかりません")
                return pd.DataFrame()
            
            # 全データを結合
            combined_data = pd.concat(all_data, ignore_index=True)
            
            # 列名正規化（url → URL）
            if 'url' in combined_data.columns and 'URL' not in combined_data.columns:
                combined_data = combined_data.rename(columns={'url': 'URL'})
                self.logger.log_info("列名を正規化: url -> URL")
            
            self.logger.log_success(f"入力データ読み込み完了: {len(combined_data)}行")
            
            return combined_data
            
        except Exception as e:
            self.logger.log_error(f"TSVファイル読み込みエラー: {str(e)}")
            raise
    
    async def _read_prompt_from_gcs(self) -> str:
        """検証専用プロンプトファイルを読み込み"""
        try:
            # 検証専用プロンプトファイル読み込み（正しいパス）
            bucket_name = self.config.input_bucket
            prompt_path = f'{self.config.job_type}/input/prompt.txt'  # doctor_info_validation/input/prompt.txt
            
            bucket = self.gcs_client.storage_client.bucket(bucket_name)
            blob = bucket.blob(prompt_path)
            
            if blob.exists():
                content = blob.download_as_text(encoding='utf-8')
                self.logger.log_success(f"検証プロンプト読み込み完了: {len(content)}文字")
                return content
            else:
                self.logger.log_warning(f"プロンプトファイルが見つかりません: gs://{bucket_name}/{prompt_path}")
                
        except Exception as e:
            self.logger.log_error(f"プロンプトファイル読み込みエラー: {str(e)}")
        
        # フォールバック: デフォルトプロンプト
        return """あなたは医療機関の専門医情報を検証する専門家です。
以下の医師情報がWebページに実際に存在するか、記載内容が正しいかを検証してください。

必ず以下のTSV形式（タブ区切り）で1行のみ出力してください：
validation_status[TAB]validation_message[TAB]corrected_name[TAB]corrected_department[TAB]corrected_position[TAB]corrected_specialty[TAB]corrected_licence[TAB]corrected_others

検証ステータス:
- VALID: 医師名と診療科が正しく、他の項目も概ね正しい
- PARTIAL: 医師は存在し名前と診療科は合っているが、他の項目に相違や欠落がある
- INVALID: 該当医師がHTMLに全く存在しない
- NOTFOUND: 技術的理由で検証不可
"""
    
    async def _process_batch_async(self, batch_df: pd.DataFrame, prompt: str):
        """バッチ非同期処理（doctor_info.pyパターン）"""
        semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)
        
        tasks = []
        for _, row in batch_df.iterrows():
            task = self._process_single_record_async(row, prompt, semaphore)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 結果処理
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.log_error(f"レコード処理エラー: {str(result)}")
                self.validation_stats['processing_errors'] += 1
                row = batch_df.iloc[i]
                error_result = self._create_error_result(row, str(result))
                self.all_records.extend(error_result)
            elif result:
                self.all_records.extend(result)
    
    async def _process_single_record_async(
        self, 
        record: pd.Series, 
        prompt: str, 
        semaphore: asyncio.Semaphore
    ) -> List[Dict[str, Any]]:
        """単一レコード非同期処理（doctor_info.pyパターン準拠）"""
        start_time = time.time()
        
        async with semaphore:
            try:
                url = record.get('URL', '')
                fac_id_unif = record.get('fac_id_unif', '')
                
                if not url:
                    self.logger.log_warning(f"URL情報が見つかりません: {fac_id_unif}")
                    return self._create_error_result(record, "URL不明")
                
                # HTML取得（doctor_info.pyパターン）
                html_content = await self.http_client.fetch_html_async(url)
                if not html_content:
                    return self._create_error_result(record, "HTML取得失敗")
                
                # HTML前処理（doctor_info.pyパターン）
                processed_content = self.http_client.preprocess_html(html_content)
                if not processed_content.strip():
                    return self._create_error_result(record, "HTML前処理後に空")
                
                # コンテキスト設定（doctor_info.pyパターン）
                context = {
                    'url': url,
                    'fac_id_unif': fac_id_unif
                }
                
                # プロンプト生成（医師情報を組み込み）
                enhanced_prompt = self._generate_enhanced_prompt(record, prompt)
                
                # AI検証実行（検証専用処理 - 生レスポンス取得）
                raw_ai_response = self._call_ai_for_validation(
                    processed_content,
                    enhanced_prompt
                )
                
                if not raw_ai_response:
                    return self._create_error_result(record, "AI応答なし")
                
                # レスポンス解析（5段階フォールバック）
                validation_result = self._parse_ai_response_robust(
                    raw_ai_response, 
                    record
                )
                
                # 統計更新
                self._update_validation_statistics(validation_result.validation_status)
                self.validation_stats['total_processed'] += 1
                
                # デバッグ情報設定
                validation_result.processing_time = time.time() - start_time
                validation_result.ai_response_raw = str(raw_ai_response)
                if len(processed_content) > 500:
                    validation_result.html_excerpt = processed_content[:500] + "..."
                else:
                    validation_result.html_excerpt = processed_content
                
                # デバッグログ
                if self.debug_mode:
                    self._log_validation_attempt(record, validation_result)
                
                return [self._validation_result_to_dict(record, validation_result)]
                
            except Exception as e:
                self.logger.log_error(f"レコード処理エラー: {str(e)}")
                return self._create_error_result(record, str(e))
    
    def _generate_enhanced_prompt(self, record: pd.Series, base_prompt: str) -> str:
        """医師情報を組み込んだプロンプトを生成"""
        try:
            # 医師情報を取得
            name = record.get('name', '')
            department = record.get('department', '')
            position = record.get('position', '')
            specialty = record.get('specialty', '')
            licence = record.get('licence', '')
            others = record.get('others', '')
            
            # プロンプト内のプレースホルダーを置換
            enhanced_prompt = base_prompt.format(
                name=name,
                department=department,
                position=position,
                specialty=specialty,
                licence=licence,
                others=others
            )
            
            return enhanced_prompt
            
        except Exception as e:
            self.logger.log_warning(f"プロンプト生成エラー: {str(e)}")
            # フォーマットエラーの場合は、プレースホルダーを手動で置換
            try:
                enhanced_prompt = base_prompt.replace('{name}', str(name))
                enhanced_prompt = enhanced_prompt.replace('{department}', str(department))
                enhanced_prompt = enhanced_prompt.replace('{position}', str(position))
                enhanced_prompt = enhanced_prompt.replace('{specialty}', str(specialty))
                enhanced_prompt = enhanced_prompt.replace('{licence}', str(licence))
                enhanced_prompt = enhanced_prompt.replace('{others}', str(others))
                return enhanced_prompt
            except:
                return base_prompt
    
    def _call_ai_for_validation(self, content: str, prompt: str) -> str:
        """検証専用AI処理（生レスポンス文字列を返す）"""
        try:
            # ローカルテスト時はモック応答（最優先チェック）
            if LOCAL_TEST:
                self.logger.log_info("ローカルテストモード: モック検証応答を返します")
                return "VALID\t検証成功\t医師名\t診療科\t部長\t専門分野\t資格\tその他情報"
            
            # AI Clientのmodel存在チェック
            if not hasattr(self.ai_client, 'model') or self.ai_client.model is None:
                self.logger.log_error("AI Clientのmodel未初期化")
                return "NOTFOUND\t技術的エラー\t\t\t\t\t\t"
            
            # コンテンツサイズ制限
            if len(content) > self.max_chars:
                content = content[:self.max_chars]
                self.logger.log_warning(f"検証用コンテンツを切り詰めました: {self.max_chars}文字")
            
            # プロンプト構築
            full_prompt = f"{prompt}\n\nHTML:\n{content}"
            
            # AI生成実行（完全決定的設定）
            response = self.ai_client.model.generate_content(
                full_prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.0,        # 完全決定的
                    top_p=0.1,             # 最小値
                    top_k=1,               # 最上位のみ選択
                    max_output_tokens=256, # 短い出力に制限（TSV1行のみ必要）
                    candidate_count=1      # 候補数を1に限定
                )
            )
            
            ai_response_text = response.text if response.text else ""
            
            # 🔍 AIの生レスポンスを詳細ログ出力（デバッグ用）
            self.logger.log_info(
                f"🤖 AI生レスポンス詳細:",
                response_length=len(ai_response_text),
                response_preview=ai_response_text[:200] if ai_response_text else "(空)",
                response_full=ai_response_text,  # 完全なレスポンスを記録
                contains_tab='\t' in ai_response_text,
                contains_newline='\n' in ai_response_text,
                starts_with_status=ai_response_text[:10] if ai_response_text else "",
                line_count=ai_response_text.count('\n') + 1 if ai_response_text else 0
            )
            
            return ai_response_text
            
        except Exception as e:
            self.logger.log_error(f"検証用AI処理エラー: {str(e)}")
            return "NOTFOUND\t処理エラー\t\t\t\t\t\t"
    
    def _parse_ai_response_robust(self, response_text: str, original_record: pd.Series) -> ValidationResult:
        """堅牢なAIレスポンス解析（5段階フォールバック）"""
        parsing_attempts = []
        
        # 🔍 解析開始の詳細ログ
        self.logger.log_info(
            f"📊 AIレスポンス解析開始:",
            doctor_name=original_record.get('name', ''),
            response_type=type(response_text).__name__,
            response_length=len(str(response_text)),
            response_raw=str(response_text)[:100] + "..." if len(str(response_text)) > 100 else str(response_text)
        )
        
        # AI応答がDict形式の場合の処理
        if isinstance(response_text, dict):
            response_text = response_text.get('content', str(response_text))
        elif not isinstance(response_text, str):
            response_text = str(response_text)
        
        # 第1段階: 標準TSV解析（タブ区切り）
        try:
            self.logger.log_info("🔍 第1段階: タブ区切り解析を試行")
            result = self._try_tab_separated_parsing(response_text)
            if result:
                parsing_attempts.append("tab_separated")
                result.parsing_attempts = parsing_attempts
                self.logger.log_success("✅ タブ区切り解析成功")
                return result
        except Exception as e:
            parsing_attempts.append(f"tab_separated_failed: {str(e)}")
            self.logger.log_warning(f"❌ タブ区切り解析失敗: {str(e)}")
        
        # 第2段階: スペース区切り解析
        try:
            self.logger.log_info("🔍 第2段階: スペース区切り解析を試行")
            result = self._try_space_separated_parsing(response_text)
            if result:
                parsing_attempts.append("space_separated")
                result.parsing_attempts = parsing_attempts
                self.logger.log_success("✅ スペース区切り解析成功")
                return result
        except Exception as e:
            parsing_attempts.append(f"space_separated_failed: {str(e)}")
            self.logger.log_warning(f"❌ スペース区切り解析失敗: {str(e)}")
        
        # 第3段階: 正規表現ベース解析
        try:
            self.logger.log_info("🔍 第3段階: 正規表現解析を試行")
            result = self._try_regex_parsing(response_text)
            if result:
                parsing_attempts.append("regex_based")
                result.parsing_attempts = parsing_attempts
                self.logger.log_success("✅ 正規表現解析成功")
                return result
        except Exception as e:
            parsing_attempts.append(f"regex_failed: {str(e)}")
            self.logger.log_warning(f"❌ 正規表現解析失敗: {str(e)}")
        
        # 第4段階: カンマ区切り解析
        try:
            self.logger.log_info("🔍 第4段階: カンマ区切り解析を試行")
            result = self._try_comma_separated_parsing(response_text)
            if result:
                parsing_attempts.append("comma_separated")
                result.parsing_attempts = parsing_attempts
                self.logger.log_success("✅ カンマ区切り解析成功")
                return result
        except Exception as e:
            parsing_attempts.append(f"comma_separated_failed: {str(e)}")
            self.logger.log_warning(f"❌ カンマ区切り解析失敗: {str(e)}")
        
        # 第5段階: 自然言語処理による情報抽出（最後の手段）
        self.logger.log_warning(
            f"⚠️ 全解析手法失敗 - 自然言語抽出に移行:",
            doctor_name=original_record.get('name', ''),
            failed_attempts=parsing_attempts,
            ai_response_problematic=response_text
        )
        
        try:
            result = self._try_natural_language_extraction(response_text, original_record)
            if result:
                parsing_attempts.append("natural_language")
                result.parsing_attempts = parsing_attempts
                return result
        except Exception as e:
            parsing_attempts.append(f"natural_language_failed: {str(e)}")
        
        # 最終段階: 解析失敗
        self.validation_stats['parsing_failures'] += 1
        self._log_parsing_failure(response_text, parsing_attempts)
        
        return ValidationResult(
            validation_status="NOTFOUND",
            validation_message="解析失敗",
            corrected_name=original_record.get('name', ''),
            corrected_department=original_record.get('department', ''),
            corrected_position="",
            corrected_specialty="",
            corrected_licence="",
            corrected_others="",
            ai_response_raw=response_text,
            parsing_attempts=parsing_attempts
        )
    
    def _try_tab_separated_parsing(self, response_text: str) -> Optional[ValidationResult]:
        """第1段階: タブ区切り解析"""
        lines = response_text.strip().split('\n')
        for line in lines:
            if '\t' in line:
                parts = line.split('\t')
                if len(parts) >= 3:  # 最低限 status, message, name があれば処理
                    # 8個のフィールドに合わせて不足分を空文字で埋める
                    while len(parts) < 8:
                        parts.append("")
                    return ValidationResult(
                        validation_status=parts[0].strip(),
                        validation_message=parts[1].strip(),
                        corrected_name=parts[2].strip(),
                        corrected_department=parts[3].strip(),
                        corrected_position=parts[4].strip(),
                        corrected_specialty=parts[5].strip(),
                        corrected_licence=parts[6].strip(),
                        corrected_others=parts[7].strip()
                    )
        return None
    
    def _try_space_separated_parsing(self, response_text: str) -> Optional[ValidationResult]:
        """第2段階: スペース区切り解析"""
        lines = response_text.strip().split('\n')
        for line in lines:
            parts = re.split(r'\s{2,}', line.strip())
            if len(parts) >= 8:
                return ValidationResult(
                    validation_status=parts[0].strip(),
                    validation_message=parts[1].strip(),
                    corrected_name=parts[2].strip(),
                    corrected_department=parts[3].strip(),
                    corrected_position=parts[4].strip(),
                    corrected_specialty=parts[5].strip(),
                    corrected_licence=parts[6].strip(),
                    corrected_others=parts[7].strip() if len(parts) > 7 else ""
                )
        return None
    
    def _try_regex_parsing(self, response_text: str) -> Optional[ValidationResult]:
        """第3段階: 正規表現ベース解析"""
        patterns = [
            r'(VALID|PARTIAL|INVALID|NOTFOUND)\s*[:\-\|]\s*(.+)',
            r'ステータス[:\s]*([A-Z]+)',
            r'判定[:\s]*([A-Z]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, response_text, re.IGNORECASE)
            if match:
                status = match.group(1).upper()
                if status in ['VALID', 'PARTIAL', 'INVALID', 'NOTFOUND']:
                    return ValidationResult(
                        validation_status=status,
                        validation_message="正規表現抽出",
                        corrected_name="",
                        corrected_department="",
                        corrected_position="",
                        corrected_specialty="",
                        corrected_licence="",
                        corrected_others=""
                    )
        return None
    
    def _try_comma_separated_parsing(self, response_text: str) -> Optional[ValidationResult]:
        """第4段階: カンマ区切り解析"""
        lines = response_text.strip().split('\n')
        for line in lines:
            if ',' in line:
                parts = [part.strip() for part in line.split(',')]
                if len(parts) >= 8:
                    return ValidationResult(
                        validation_status=parts[0].strip(),
                        validation_message=parts[1].strip(),
                        corrected_name=parts[2].strip(),
                        corrected_department=parts[3].strip(),
                        corrected_position=parts[4].strip(),
                        corrected_specialty=parts[5].strip(),
                        corrected_licence=parts[6].strip(),
                        corrected_others=parts[7].strip() if len(parts) > 7 else ""
                    )
        return None
    
    def _try_natural_language_extraction(self, response_text: str, original_record: pd.Series) -> Optional[ValidationResult]:
        """第5段階: 自然言語処理による情報抽出（最終手段として使用を制限）"""
        # 自然言語抽出の使用をカウント
        self.validation_stats['natural_language_extractions'] += 1
        
        # 警告ログを出力
        self.logger.log_warning(
            f"自然言語抽出を使用 (fac_id: {original_record.get('fac_id_unif', 'unknown')}, "
            f"name: {original_record.get('name', 'unknown')})"
        )
        
        # より厳密なステータスキーワード検出
        response_lower = response_text.lower()
        
        # 明確なキーワードがある場合のみステータスを判定
        if any(kw in response_lower for kw in ['invalid', '無効', '存在しない', '見つかりません', '該当なし']):
            return ValidationResult(
                validation_status="INVALID",
                validation_message="自然言語判定:無効",
                corrected_name="",
                corrected_department="",
                corrected_position="",
                corrected_specialty="",
                corrected_licence="",
                corrected_others=""
            )
        elif any(kw in response_lower for kw in ['partial', '部分的', '一部']):
            return ValidationResult(
                validation_status="PARTIAL",
                validation_message="自然言語判定:部分一致",
                corrected_name=original_record.get('name', ''),
                corrected_department=original_record.get('department', ''),
                corrected_position=original_record.get('position', ''),
                corrected_specialty=original_record.get('specialty', ''),
                corrected_licence=original_record.get('licence', ''),
                corrected_others=original_record.get('others', '')
            )
        elif any(kw in response_lower for kw in ['valid', '正しい', '一致', '確認']):
            return ValidationResult(
                validation_status="VALID",
                validation_message="自然言語判定:有効",
                corrected_name=original_record.get('name', ''),
                corrected_department=original_record.get('department', ''),
                corrected_position=original_record.get('position', ''),
                corrected_specialty=original_record.get('specialty', ''),
                corrected_licence=original_record.get('licence', ''),
                corrected_others=original_record.get('others', '')
            )
        
        # 明確なキーワードがない場合はNOTFOUNDとして扱う
        return ValidationResult(
            validation_status="NOTFOUND",
            validation_message="TSV解析失敗",
            corrected_name=original_record.get('name', ''),
            corrected_department=original_record.get('department', ''),
            corrected_position="",
            corrected_specialty="",
            corrected_licence="",
            corrected_others=""
        )
    
    def _update_validation_statistics(self, status: str):
        """検証統計情報を更新"""
        if status == 'VALID':
            self.validation_stats['valid_count'] += 1
        elif status == 'PARTIAL':
            self.validation_stats['partial_count'] += 1
        elif status == 'INVALID':
            self.validation_stats['invalid_count'] += 1
        elif status == 'NOTFOUND':
            self.validation_stats['notfound_count'] += 1
    
    def _log_validation_attempt(self, record: pd.Series, result: ValidationResult):
        """検証試行の詳細ログ"""
        self.logger.log_info(
            f"検証詳細",
            doctor_name=record.get('name', ''),
            department=record.get('department', ''),
            validation_status=result.validation_status,
            validation_message=result.validation_message,
            processing_time=result.processing_time,
            parsing_attempts=result.parsing_attempts
        )
    
    def _log_parsing_failure(self, response_text: str, attempts: List[str]):
        """解析失敗の詳細ログ"""
        self.logger.log_error(
            f"レスポンス解析失敗",
            response_text=response_text[:200] + "..." if len(response_text) > 200 else response_text,
            parsing_attempts=attempts
        )
    
    def _create_error_result(self, record: pd.Series, error_message: str) -> List[Dict[str, Any]]:
        """エラー時の結果を作成"""
        result = {
            'fac_id_unif': record.get('fac_id_unif', ''),
            'output_order': record.get('output_order', ''),
            'name': record.get('name', ''),
            'department': record.get('department', ''),
            'position': record.get('position', ''),
            'specialty': record.get('specialty', ''),
            'licence': record.get('licence', ''),
            'others': record.get('others', ''),
            'validation_status': 'NOTFOUND',
            'validation_message': error_message[:20],
            'corrected_name': record.get('name', ''),
            'corrected_department': record.get('department', ''),
            'corrected_position': '',
            'corrected_specialty': '',
            'corrected_licence': '',
            'corrected_others': ''
        }
        
        self.validation_stats['notfound_count'] += 1
        return [result]
    
    def _validation_result_to_dict(self, record: pd.Series, result: ValidationResult) -> Dict[str, Any]:
        """ValidationResultを辞書に変換（正しい列名で出力）"""
        from datetime import datetime, timezone, timedelta
        
        # JST時刻を取得
        jst = timezone(timedelta(hours=9))
        jst_time = datetime.now(jst).strftime('%Y-%m-%d %H:%M:%S')
        
        return {
            'fac_id_unif': record.get('fac_id_unif', ''),
            'url': record.get('url', record.get('URL', '')),  # url または URL列を探す
            'output_order': record.get('output_order', ''),
            # originalプレフィックス付きの元データ
            'original_name': record.get('name', ''),
            'original_department': record.get('department', ''),
            'original_position': record.get('position', ''),
            'original_specialty': record.get('specialty', ''),
            'original_licence': record.get('licence', ''),
            'original_others': record.get('others', ''),
            # 検証結果
            'validation_status': result.validation_status,
            'validation_message': result.validation_message,
            # correctedプレフィックス付きの修正データ
            'corrected_name': result.corrected_name,
            'corrected_department': result.corrected_department,
            'corrected_position': result.corrected_position,
            'corrected_specialty': result.corrected_specialty,
            'corrected_licence': result.corrected_licence,
            'corrected_others': result.corrected_others,
            # メタデータ
            'validation_datetime': jst_time,
            'ai_version': self.config.ai_model  # config.pyから実際のモデル名を取得
        }
    
    async def _save_validation_results(self):
        """検証結果を保存"""
        try:
            if not self.all_records:
                return
            
            # TSV形式で保存
            self.gcs_client.upload_tsv(self.all_records)
            
            self.logger.log_success(f"検証結果保存完了: {len(self.all_records)}件")
            
        except Exception as e:
            self.logger.log_error(f"検証結果保存エラー: {str(e)}")
            raise
    
    def _log_final_statistics(self):
        """最終統計情報をログ出力"""
        total = self.validation_stats['total_processed']
        if total == 0:
            return
        
        # 自然言語抽出の警告
        nl_count = self.validation_stats.get('natural_language_extractions', 0)
        if nl_count > 0:
            self.logger.log_warning(
                f"⚠️ 自然言語抽出を{nl_count}回使用しました。"
                f"AIがTSVフォーマットで応答していない可能性があります。"
            )
        
        self.logger.log_success(
            "=== 医師情報検証統計 ===",
            total_processed=total,
            valid_count=self.validation_stats['valid_count'],
            valid_rate=f"{self.validation_stats['valid_count'] / total * 100:.1f}%",
            partial_count=self.validation_stats['partial_count'],
            partial_rate=f"{self.validation_stats['partial_count'] / total * 100:.1f}%",
            invalid_count=self.validation_stats['invalid_count'],
            invalid_rate=f"{self.validation_stats['invalid_count'] / total * 100:.1f}%",
            notfound_count=self.validation_stats['notfound_count'],
            notfound_rate=f"{self.validation_stats['notfound_count'] / total * 100:.1f}%",
            natural_language_extractions=nl_count,
            parsing_failures=self.validation_stats['parsing_failures'],
            processing_errors=self.validation_stats['processing_errors']
        )
    
    def cleanup(self):
        """リソース清理"""
        try:
            # 最終統計を出力
            self._log_final_statistics()
            
            # ログをGCSにアップロード
            if hasattr(self, 'gcs_client') and self.gcs_client:
                log_path = self.gcs_client.upload_log()
                if log_path:
                    self.logger.log_success(f"ログアップロード完了: {log_path}")
            
            # メモリクリーンアップ
            from common.utils import cleanup_memory
            cleanup_memory()
            
            self.logger.log_info("リソース清理完了")
        except Exception as e:
            self.logger.log_warning(f"リソース清理エラー: {e}")


def run(config: Config, logger: UnifiedLogger) -> None:
    """モジュールレベルの実行関数（独立実装）"""
    processor = None
    
    try:
        logger.log_info("DoctorInfoValidationProcessor初期化開始")
        processor = DoctorInfoValidationProcessor(config, logger)
        logger.log_info("DoctorInfoValidationProcessor初期化完了")
        
        # 非同期処理を推奨（大学病院1000医師対応）
        use_async = os.getenv("USE_ASYNC", "true").lower() == "true"
        logger.log_info(f"実行モード: {'async' if use_async else 'sync'}")
        
        if use_async:
            asyncio.run(processor.run_async())
        else:
            processor.run_sync()
            
    except Exception as e:
        if logger:
            logger.log_error(f"医師情報検証処理でエラーが発生: {str(e)}")
            import traceback
            logger.log_error(f"スタックトレース:\n{traceback.format_exc()}")
        raise
        
    finally:
        if processor:
            processor.cleanup()