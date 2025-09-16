"""
URL収集用シンプルAIクライアント（旧システムベース）

旧システムのアプローチを採用してAIの出力を信頼し、最小限の処理で済ませる
"""

import re
from typing import List, Dict, Any, Optional

from config import Config, LOCAL_TEST
from .logger import UnifiedLogger


class SimpleURLCollectAIClient:
    """URL収集専用のシンプルAIクライアント（旧システムベース）"""
    
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
            prompt_text = f"{prompt}\n\nPAGE_TEXT: {content}\nURL: {context.get('url', '')}\nPAGE_TITLE: {context.get('page_title', '')}\nANCHOR_TEXTS: {context.get('anchor_texts', [])}\nIMAGE_ALTS: {context.get('image_alts', [])}"
            
            # AI処理実行
            import google.generativeai as genai
            response = self.model.generate_content(
                prompt_text,
                generation_config=genai.types.GenerationConfig(
                    temperature=self.config.ai_temperature,
                    top_p=0.1,
                    top_k=1,
                    max_output_tokens=4096
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
            
            # ヘッダー行を検出してスキップ
            start_idx = 0
            for i, line in enumerate(lines):
                lower_line = line.lower()
                # ヘッダー検出条件
                header_patterns = [
                    'fac_id_unif' in lower_line and 'url' in lower_line,
                    'type' in lower_line and 'department' in lower_line,
                    line.count('\t') >= 5 and ('url' in lower_line or 'type' in lower_line),
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
                
                if len(fields) < 3:  # 最低限必要なフィールド数
                    continue
                
                # フィールドを7列に正規化
                while len(fields) < 7:
                    fields.append('')
                
                # フィールドのクリーニング
                def clean_text(text):
                    if not text:
                        return ''
                    # 前後の空白、引用符、括弧を除去
                    cleaned = re.sub(r'^[\s"\'()（）]*|[\s"\'()（）]*$', '', str(text))
                    return cleaned.strip()
                
                fac_id_unif = clean_text(fields[0]) or context.get('fac_id_unif', '')
                url = clean_text(fields[1]) or context.get('url', '')
                page_type = clean_text(fields[2])
                department = clean_text(fields[3]) or "診療科"
                page_title = clean_text(fields[4]) or context.get('page_title', '')
                
                # typeが有効な分類コードかチェック
                valid_types = ['s', 'g_txt', 'g_img', 'g_pdf']
                if page_type not in valid_types:
                    continue
                
                # URLが空の場合はスキップ
                if not url:
                    continue
                
                record = {
                    'fac_id_unif': fac_id_unif,
                    'url': url,
                    'type': page_type,
                    'department': department,
                    'page_title': page_title,
                    'update_datetime': current_time,
                    'ai_version': self.config.ai_model
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
            'url': context.get('url', 'https://mock-hospital.com/mock-page'),
            'type': 's',
            'department': 'モック診療科',
            'page_title': 'モックページタイトル',
            'update_datetime': current_time,
            'ai_version': 'mock_ai_model'
        }]