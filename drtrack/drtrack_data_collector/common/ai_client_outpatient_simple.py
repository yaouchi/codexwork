"""
外来情報用シンプルAIクライアント（旧システムベース）

旧システムの強力な偽データ検出と統一処理アプローチを現行システムに適用
"""

import re
import time
from typing import List, Dict, Any, Optional

from config import Config, LOCAL_TEST
from .logger import UnifiedLogger


class SimpleOutpatientAIClient:
    """外来情報専用のシンプルAIクライアント（旧システムベース）"""
    
    def __init__(self, config: Config, logger: UnifiedLogger):
        self.config = config
        self.logger = logger
        
        # ローカルテスト時はAI処理をモック化
        if LOCAL_TEST:
            self.logger.log_info("ローカルテストモード: AI処理をモック化")
            self._mock_mode = True
            return
        else:
            self._mock_mode = False
        
        # Gemini API設定
        try:
            import google.generativeai as genai
            genai.configure(api_key=config.gemini_key)
            self.model = genai.GenerativeModel(model_name=config.ai_model)
            self.logger.log_success(f"AI初期化完了: {config.ai_model}")
        except Exception as e:
            self.logger.log_error(f"AI初期化エラー: {str(e)}", error=e)
            raise
    
    def process_with_ai(
        self,
        content: str,
        prompt: str,
        context: Dict[str, Any],
        content_type: str = "text"
    ) -> List[Dict[str, Any]]:
        """AI処理（旧システムのシンプルアプローチ）"""
        
        if self._mock_mode:
            return self._generate_mock_response(context)
        
        try:
            self.logger.log_info(
                f"AI処理開始: {context.get('url', 'unknown')}",
                **context
            )
            
            # コンテンツサイズチェック
            if len(content) > self.config.max_content_length:
                content = content[:self.config.max_content_length]
                self.logger.log_warning(
                    f"コンテンツを切り詰めました: {self.config.max_content_length}文字",
                    original_length=len(content)
                )
            
            # 旧システムの強力なプロンプト強化
            enhanced_prompt = f"""
{prompt}

【入力パラメータ - 絶対に使用すること】
施設コード（fac_id_unif）: {context.get('fac_id_unif', '')}
URL（url_single_table）: {context.get('url', '')}

重要: これらの値は出力時に必ずそのまま使用してください。
サンプルデータ（123456789、https://example.com、○○病院など）は絶対に使用しないでください。

【最終確認】
- 医師名が架空（山田太郎、佐藤一郎等）になっていないか確認
- プレースホルダー（〇〇△△）を使用していないか確認
- 実際のHTML/PDF内容のみを参照しているか確認
- 推測や補完を行っていないか確認

【コンテンツ】
{content}
"""
            
            # AI処理実行（旧システムの厳格設定）
            import google.generativeai as genai
            response = self.model.generate_content(
                enhanced_prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0,      # 創造性を完全に抑制
                    top_p=0.1,         # より確実性の高い応答のみ
                    top_k=1,           # 最も確実な選択肢のみ
                    max_output_tokens=8192
                )
            )
            
            # レスポンス解析（旧システムベース）
            records = self._parse_simple_response(response.text, context)
            
            self.logger.log_success(
                f"AI処理完了: {len(records)}件",
                record_count=len(records),
                **context
            )
            
            return records
            
        except Exception as e:
            self.logger.log_error(
                f"AI処理エラー: {str(e)}",
                error=e,
                **context
            )
            return []
    
    def _parse_simple_response(self, response_text: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """シンプルなレスポンス解析（旧システムベース）"""
        try:
            # AIの出力からコードブロックを除去
            tsv_content = re.sub(r'```[^`]*```', '', response_text, flags=re.DOTALL).strip()
            if not tsv_content:
                tsv_content = response_text.strip()
            
            # 行に分割
            lines = [line.strip() for line in tsv_content.split('\n') if line.strip()]
            if not lines:
                self.logger.log_warning(
                    "AIレスポンスが空です",
                    response_text=response_text[:200],
                    **context
                )
                return []
            
            records = []
            output_datetime_jst = self.logger.get_jst_now_iso()
            
            # ヘッダー行を検出してスキップ
            start_idx = 0
            for i, line in enumerate(lines):
                lower_line = line.lower()
                # ヘッダー検出条件
                header_patterns = [
                    'fac_id_unif' in lower_line and 'department' in lower_line,
                    'doctors_name' in lower_line and 'specialty' in lower_line,
                    line.count('\t') >= 10 and ('fac_id' in lower_line or 'department' in lower_line),
                ]
                
                if any(header_patterns):
                    start_idx = i + 1
                    self.logger.log_info(
                        f"ヘッダー行を検出してスキップ: {line}",
                        header_line_index=i,
                        **context
                    )
                    break
            
            # データ行を処理
            for i in range(start_idx, len(lines)):
                line = lines[i].strip()
                if not line:
                    continue
                
                # タブ区切りで分割
                fields = line.split('\t')
                
                if len(fields) < 6:  # 最低限必要なフィールド数
                    continue
                
                # フィールドを14列に正規化（DDL仕様）
                while len(fields) < 14:
                    fields.append('')
                
                # フィールドのクリーニング
                def clean_text(text):
                    if not text:
                        return ''
                    # 前後の空白、引用符、括弧を除去
                    cleaned = re.sub(r'^[\s"\'()（）]*|[\s"\'()（）]*$', '', str(text))
                    return cleaned.strip()
                
                # フィールド抽出と検証（旧システム方式）
                fac_id_unif_field = clean_text(fields[0]) or context.get('fac_id_unif', '')
                fac_nm = clean_text(fields[1]) or ""
                department = clean_text(fields[2]) or ""
                day_of_week = clean_text(fields[3]) or ""
                first_followup_visit = clean_text(fields[4]) or ""
                doctors_name = clean_text(fields[5]) or ""
                position = clean_text(fields[6]) or ""
                charge_week = clean_text(fields[7]) or ""
                charge_date = clean_text(fields[8]) or ""
                specialty = clean_text(fields[9]) or ""
                update_date = clean_text(fields[10]) or ""
                url_single_table = clean_text(fields[11]) or context.get('url', '')
                
                # データ品質チェック（旧システムの強力なチェック）
                if not fac_id_unif_field or fac_id_unif_field == '123456789':
                    fac_id_unif_field = context.get('fac_id_unif', '')
                
                if not url_single_table or url_single_table == 'https://example.com':
                    url_single_table = context.get('url', '')
                
                # サンプルデータの検出と修正
                if fac_nm in ['○○病院', 'サンプル病院', '医療法人 平野同仁会 総合病院']:
                    fac_nm = '不明'
                
                # 医師名の品質チェック（旧システムの強力な検証）
                if not self._is_valid_doctor_name(doctors_name):
                    self.logger.log_warning(
                        f"無効な医師名を検出してスキップ: {doctors_name}",
                        **context
                    )
                    continue
                
                # 列配置の修正（旧システムの修正ロジック）
                charge_date, specialty = self._fix_column_placement(charge_date, specialty)
                
                # 診療科名は必須、医師名は「-」等も含めて有効
                if not department:
                    continue
                
                record = {
                    'fac_id_unif': fac_id_unif_field,
                    'fac_nm': fac_nm,
                    'department': department,
                    'day_of_week': day_of_week,
                    'first_followup_visit': first_followup_visit,
                    'doctors_name': doctors_name,
                    'position': position,
                    'charge_week': charge_week,
                    'charge_date': charge_date,
                    'specialty': specialty,
                    'update_date': update_date,
                    'url_single_table': url_single_table,
                    'output_datetime': output_datetime_jst,
                    'ai_version': self.config.ai_model
                }
                records.append(record)
            
            # 旧システムの品質チェック
            quality_issues = self._validate_output_quality(records, context)
            
            # 偽データが検出された場合は全レコードを破棄
            if self._has_fake_data_issues(quality_issues):
                self.logger.log_error(
                    "偽データが検出されたため全レコードを破棄",
                    **context
                )
                return []
            
            self.logger.log_success(
                f"レスポンス解析完了: {len(records)}レコード抽出",
                records_parsed=len(records),
                total_lines=len(lines),
                skipped_from_index=start_idx,
                **context
            )
            
            return records
            
        except Exception as e:
            self.logger.log_error(
                "レスポンス解析エラー",
                error=e,
                response_text=response_text[:500],
                **context
            )
            return []
    
    def _is_valid_doctor_name(self, doctors_name: str) -> bool:
        """医師名の妥当性をチェック（調整版：休診情報も含める）"""
        if not doctors_name or doctors_name.strip() == '':
            return False
        
        # 休診・空白情報も有効として扱う（外来表では重要な情報）
        if doctors_name.strip() in ['-', '休診', '―', '・', '×', '※']:
            return True
        
        # 偽データの検出（最優先）
        if self._detect_fake_data(doctors_name):
            return False
        
        # 診療科名パターンの定義
        department_patterns = [
            r'.*科$',  # ○○科で終わる
            r'.*内科$',  # ○○内科で終わる
            r'.*外科$',  # ○○外科で終わる
            r'^内科$', r'^外科$', r'^小児科$', r'^産婦人科$', r'^眼科$', r'^耳鼻咽喉科$',
            r'^皮膚科$', r'^泌尿器科$', r'^整形外科$', r'^脳神経外科$', r'^形成外科$',
            r'^循環器科$', r'^循環器内科$', r'^呼吸器科$', r'^呼吸器内科$', r'^消化器科$',
            r'^消化器内科$', r'^神経内科$', r'^精神科$', r'^放射線科$', r'^麻酔科$',
            r'^リハビリテーション科$', r'^血管外科$', r'^心臓血管外科$', r'^乳腺科$',
            r'^糖尿病内科$', r'^腎臓内科$', r'^血液内科$', r'^肝臓内科$', r'^漢方内科$',
            r'^脳神経内科$', r'^歯科口腔外科$', r'^ウロギネ科$'
        ]
        
        # 診療科名パターンにマッチする場合は無効
        for pattern in department_patterns:
            if re.match(pattern, doctors_name.strip()):
                return False
        
        # 有効な医師名パターン（大学名、応援医師なども含む）
        valid_patterns = [
            r'.*医師$',  # ○○医師
            r'.*医大$',  # ○○医大
            r'.*大学$',  # ○○大学
            r'[ぁ-んァ-ヶー一-龯]+',  # 日本語の人名
            r'[A-Za-z\s]+',  # 英語名
        ]
        
        # 有効パターンのいずれかにマッチすれば有効
        for pattern in valid_patterns:
            if re.search(pattern, doctors_name.strip()):
                return True
        
        return False
    
    def _detect_fake_data(self, doctors_name: str) -> bool:
        """偽データの検出（旧システムの強力な検出）"""
        if not doctors_name or doctors_name.strip() in ['-', '']:
            return False
        
        # 架空の医師名パターン（Gemini 2.5が生成しやすいパターン）
        fake_name_patterns = [
            r'山田.*太郎', r'佐藤.*一郎', r'鈴木.*次郎', r'田中.*三郎',
            r'高橋.*四郎', r'伊藤.*五郎', r'渡辺.*六郎', r'山本.*七郎',
            r'加藤.*八郎', r'小林.*九郎', r'吉田.*十郎',
            r'〇〇.*△△', r'○○.*△△',  # プレースホルダー
            r'.*五十[一-九]?$', r'.*六十[一-九]?$',  # 連番パターン
            r'.*七十[一-九]?$', r'.*八十[一-九]?$',
            # より具体的な偽名パターン
            r'^山田\s*太郎$', r'^佐藤\s*一郎$', r'^鈴木\s*次郎$',
            r'^田中\s*三郎$', r'^高橋\s*四郎$', r'^伊藤\s*五郎$',
            r'^渡辺\s*六郎$', r'^山本\s*七郎$', r'^加藤\s*八郎$',
            r'^小林\s*九郎$', r'^吉田\s*十郎$'
        ]
        
        # 偽データパターンにマッチする場合は偽データ
        for pattern in fake_name_patterns:
            if re.match(pattern, doctors_name.strip()):
                return True
        
        return False
    
    def _fix_column_placement(self, charge_date: str, specialty: str) -> tuple:
        """列配置の修正（旧システムの修正ロジック）"""
        # 時間パターンの定義
        time_patterns = [
            r'\d{1,2}:\d{2}[〜～-]\d{1,2}:\d{2}',  # 8:30〜11:30
            r'午前', r'午後',  # 午前、午後
            r'\d{1,2}時[〜～-]\d{1,2}時',  # 8時〜11時
            r'\d{1,2}:\d{2}まで',  # 10:00まで
        ]
        
        # specialtyに時間情報が入っている場合
        if specialty:
            for pattern in time_patterns:
                if re.search(pattern, specialty):
                    # specialtyの時間情報をcharge_dateに移動
                    if not charge_date or charge_date.strip() in ['-', '']:
                        charge_date = specialty
                        specialty = ''
                        break
        
        return charge_date, specialty
    
    def _validate_output_quality(self, records: List[Dict[str, Any]], context: Dict[str, Any]) -> List[str]:
        """出力データの品質をチェック（旧システムベース）"""
        issues = []
        
        for i, record in enumerate(records):
            # サンプルデータの検出
            if record.get('fac_id_unif') == '123456789':
                issues.append(f"レコード{i}: サンプルfac_id_unif検出")
            
            if record.get('url_single_table') == 'https://example.com':
                issues.append(f"レコード{i}: サンプルURL検出")
            
            if record.get('fac_nm') in ['○○病院', 'サンプル病院']:
                issues.append(f"レコード{i}: サンプル病院名検出")
            
            # 医師名の品質チェック
            doctors_name = record.get('doctors_name', '')
            if not self._is_valid_doctor_name(doctors_name):
                issues.append(f"レコード{i}: 無効な医師名「{doctors_name}」")
            
            # 列配置の品質チェック
            specialty = record.get('specialty', '')
            if specialty:
                time_patterns = [r'\d{1,2}:\d{2}[〜～-]\d{1,2}:\d{2}', r'午前', r'午後']
                for pattern in time_patterns:
                    if re.search(pattern, specialty):
                        issues.append(f"レコード{i}: specialty列に時間情報が混入「{specialty}」")
                        break
        
        if issues:
            self.logger.log_warning(
                f"データ品質警告: {len(issues)}件の問題を検出",
                **context
            )
            for issue in issues:
                self.logger.log_warning(issue, **context)
        
        return issues
    
    def _has_fake_data_issues(self, quality_issues: List[str]) -> bool:
        """偽データ問題があるかチェック（旧システムベース）"""
        fake_data_keywords = [
            "偽データ検出", "無効な医師名", "サンプル", "架空"
        ]
        
        for issue in quality_issues:
            for keyword in fake_data_keywords:
                if keyword in issue:
                    return True
        
        return False
    
    def _generate_mock_response(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """モック応答生成（ローカルテスト用）"""
        current_time = self.logger.get_jst_now_iso()
        
        return [{
            'fac_id_unif': context.get('fac_id_unif', 'mock_fac_123'),
            'fac_nm': 'モック病院',
            'department': 'モック診療科',
            'day_of_week': '月曜日',
            'first_followup_visit': '初診・再診',
            'doctors_name': 'モック医師',
            'position': '医師',
            'charge_week': '1-4週',
            'charge_date': '9:00-12:00',
            'specialty': 'モック専門',
            'update_date': '',
            'url_single_table': context.get('url', 'https://mock-hospital.com/mock-page'),
            'output_datetime': current_time,
            'ai_version': 'mock_ai_model'
        }]