"""
DrTrack AI処理クライアント（シンプル版）

旧システムのアプローチを採用してAIの出力を信頼し、最小限の処理で済ませる
"""

import re
from typing import List, Dict, Any, Optional

from config import Config, LOCAL_TEST
from .logger import UnifiedLogger


class SimpleDoctorInfoAIClient:
    """医師情報専用のシンプルAIクライアント（旧システムベース）"""
    
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
            
            # プロンプト構築（シンプル）
            prompt_text = f"{prompt}\n\nHTML:\n{content}"
            
            # AI処理実行
            import google.generativeai as genai
            response = self.model.generate_content(
                prompt_text,
                generation_config=genai.types.GenerationConfig(
                    temperature=self.config.ai_temperature,
                    top_p=0.1,
                    top_k=1,
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
            current_time = self.logger.get_jst_now_iso()
            
            # ヘッダー行を検出してスキップ（旧システムと同様）
            start_idx = 0
            for i, line in enumerate(lines):
                lower_line = line.lower()
                # より包括的なヘッダー検出条件
                header_patterns = [
                    'department' in lower_line and 'name' in lower_line,
                    '診療科' in line and ('名前' in line or 'name' in line),
                    'name' in lower_line and 'position' in lower_line,
                    'name' in lower_line and 'specialty' in lower_line,
                    # カンマ区切りでヘッダー項目が多数含まれる場合
                    line.count(',') >= 4 and ('name' in lower_line or '診療科' in line),
                    # タブ区切りでヘッダー項目が多数含まれる場合
                    line.count('\t') >= 4 and ('name' in lower_line or '診療科' in line),
                    # 英語ヘッダーの組み合わせ
                    'position' in lower_line and 'specialty' in lower_line,
                    'licence' in lower_line and 'others' in lower_line
                ]
                
                if any(header_patterns):
                    start_idx = i + 1
                    self.logger.log_info(
                        f"ヘッダー行を検出してスキップ: {line}",
                        header_line_index=i,
                        **context
                    )
                    break
            
            # 既知のヘッダー値を定義（後処理フィルタ用）
            header_values = {
                'department', 'name', 'position', 'specialty', 'licence', 'others',
                '診療科', '名前', '役職', '専門', '資格', 'その他'
            }
            
            # データ行を処理
            for i in range(start_idx, len(lines)):
                line = lines[i].strip()
                if not line:
                    continue
                
                # タブ区切りまたはカンマ区切りで分割
                if '\t' in line:
                    fields = line.split('\t')
                else:
                    fields = line.split(',')
                
                if len(fields) < 2:  # 最低限、診療科と名前は必要
                    continue
                
                # フィールドを6列に正規化
                while len(fields) < 6:
                    fields.append('')
                
                # フィールドのクリーニング（旧システムと同様）
                def clean_text(text):
                    if not text:
                        return ''
                    # 前後の空白、引用符、括弧を除去
                    cleaned = re.sub(r'^[\s"\'()（）]*|[\s"\'()（）]*$', '', str(text))
                    return cleaned.strip()
                
                department = clean_text(fields[0]) or "診療科"
                name = clean_text(fields[1])
                position = clean_text(fields[2])
                specialty = clean_text(fields[3])
                licence = clean_text(fields[4])
                others = clean_text(fields[5])
                
                # ヘッダー値が混入していないかチェック
                if name.lower() in header_values or department.lower() in header_values:
                    self.logger.log_info(
                        f"ヘッダー値を含む行をスキップ: {line}",
                        **context
                    )
                    continue
                
                # 名前が空の場合はスキップ
                if not name or len(name) < 2:
                    continue
                
                # 明らかに無効なデータをスキップ
                if name in ['N/A', 'なし', '-', '該当なし', '不明']:
                    continue
                
                # output_orderを生成
                output_order = f"{context.get('fac_id_unif', '000000')}_{len(records)+1:05d}"
                
                record = {
                    'fac_id_unif': context.get('fac_id_unif', ''),
                    'output_order': output_order,
                    'department': department,
                    'name': name,
                    'position': position,
                    'specialty': specialty,
                    'licence': licence,
                    'others': others,
                    'output_datetime': current_time,
                    'ai_version': self.config.ai_model,
                    'url': context.get('url', '')
                }
                records.append(record)
            
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
    
    def _generate_mock_response(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """モック応答生成（ローカルテスト用）"""
        current_time = self.logger.get_jst_now_iso()
        
        return [{
            'fac_id_unif': context.get('fac_id_unif', 'mock_fac_123'),
            'output_order': f"{context.get('fac_id_unif', 'mock_fac_123')}_00001",
            'department': 'モック診療科',
            'name': 'モック医師',
            'position': 'モック部長',
            'specialty': 'モック専門',
            'licence': 'モック資格',
            'others': '',
            'output_datetime': current_time,
            'ai_version': 'mock_ai_model',
            'url': context.get('url', 'https://mock-hospital.com/mock-doctor')
        }]