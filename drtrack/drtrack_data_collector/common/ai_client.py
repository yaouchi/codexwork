"""
DrTrack AI処理クライアント

Gemini APIを使用したAI処理
"""

import asyncio
import threading
import time
from typing import List, Dict, Any, Optional, Union
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential

from config import Config, LOCAL_TEST
from .logger import UnifiedLogger


class UnifiedAIClient:
    """DrTrack AI処理クライアント"""
    
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
            genai.configure(api_key=config.gemini_key)
            self.model = genai.GenerativeModel(model_name=config.ai_model)
            self.logger.log_success(f"AI初期化完了: {config.ai_model}")
        except Exception as e:
            self.logger.log_error(f"AI初期化エラー: {str(e)}", error=e)
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    def process_with_ai(
        self,
        content: Union[str, bytes],
        prompt: str,
        context: Dict[str, Any],
        content_type: str = "text"
    ) -> List[Dict[str, Any]]:
        """AI処理（リトライ付き）"""
        
        # ローカルテストモード
        if self._mock_mode:
            return self._generate_mock_response(content_type, context)
        
        try:
            self.logger.log_info(
                f"AI処理開始: {content_type}",
                content_type=content_type,
                **context
            )
            
            # コンテンツサイズチェック
            if content_type == "text" and isinstance(content, str):
                if len(content) > self.config.max_content_length:
                    content = content[:self.config.max_content_length]
                    self.logger.log_warning(
                        f"コンテンツを切り詰めました: {self.config.max_content_length}文字",
                        original_length=len(content)
                    )
            
            # AI処理実行
            response = self._call_ai_api(content, prompt, content_type)
            
            # レスポンス解析
            records = self._parse_ai_response(response, context)
            
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
                content_type=content_type,
                **context
            )
            raise
    
    def _call_ai_api(
        self,
        content: Union[str, bytes],
        prompt: str,
        content_type: str
    ) -> str:
        """AI API呼び出し（タイムアウト対応）"""
        
        # 生成設定
        generation_config = genai.types.GenerationConfig(
            temperature=self.config.ai_temperature,
            top_p=0.1,
            top_k=1,
            max_output_tokens=8192
        )
        
        # プロンプト強化
        enhanced_prompt = f"""
{prompt}

【重要指示】
- 実際のコンテンツから正確な情報のみを抽出してください
- 推測や補完は行わないでください  
- サンプルデータ（123456789、https://example.com等）は使用しないでください
- 医師名は実在する名前のみ出力してください
"""
        
        # スレッドベースのタイムアウト処理
        result = {'response': None, 'error': None, 'completed': False}
        
        def ai_call():
            try:
                if content_type == "text":
                    enhanced_prompt_with_content = f"{enhanced_prompt}\n\nコンテンツ:\n{content}"
                    response = self.model.generate_content(
                        enhanced_prompt_with_content,
                        generation_config=generation_config
                    )
                else:
                    # 画像・PDFの場合
                    response = self.model.generate_content(
                        [content, enhanced_prompt],
                        generation_config=generation_config
                    )
                
                result['response'] = response.text
                result['completed'] = True
                
            except Exception as e:
                result['error'] = str(e)
                result['completed'] = True
        
        # スレッド実行
        thread = threading.Thread(target=ai_call)
        thread.daemon = True
        thread.start()
        
        # タイムアウト待機
        start_time = time.time()
        while not result['completed'] and (time.time() - start_time) < self.config.ai_timeout:
            time.sleep(0.5)
        
        # 結果確認
        if not result['completed']:
            raise TimeoutError(f"AI処理がタイムアウトしました ({self.config.ai_timeout}秒)")
        
        if result['error']:
            raise Exception(f"AI API呼び出しエラー: {result['error']}")
        
        return result['response']
    
    def _parse_ai_response(self, response: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """AI応答の解析"""
        
        # コードブロック除去
        import re
        response = re.sub(r'```[^`]*```', '', response, flags=re.DOTALL).strip()
        
        if not response:
            self.logger.log_warning("AI応答が空です")
            return []
        
        
        # TSV形式として解析
        lines = response.split('\n')
        records = []
        
        
        # ヘッダー行を探す
        header_row = -1
        for i, line in enumerate(lines):
            if any(header in line.lower() for header in ['fac_id_unif', 'url', 'department']):
                header_row = i
                break
        
        if header_row >= 0:
            start_idx = header_row + 1
        else:
            start_idx = 0
            
        
        # データ行を処理
        current_time = self.logger.get_jst_now_iso()
        
        for i in range(start_idx, len(lines)):
            line = lines[i].strip()
            if not line:
                continue
            
            
            fields = line.split('\t')
            
            if len(fields) < 3:  # 最低限のフィールド数
                self.logger.log_warning(f"フィールド数不足: {len(fields)}個 < 3個")
                continue
            
            # 基本レコード作成（機能別でオーバーライド）
            record = self._create_record_from_fields(fields, context, current_time)
            if record:
                records.append(record)
            else:
                self.logger.log_warning(f"レコード作成失敗: fields={fields}")
        
        self.logger.log_info(f"AI応答解析完了: {len(records)}レコード抽出")
        return records
    
    def _create_record_from_fields(
        self,
        fields: List[str],
        context: Dict[str, Any],
        current_time: str
    ) -> Optional[Dict[str, Any]]:
        """フィールドからレコード作成（機能別でオーバーライド）"""
        
        # url_collect用の処理
        if self.config.job_type == "url_collect":
            if len(fields) >= 7:
                return {
                    'fac_id_unif': fields[0],
                    'url': fields[1],
                    'type': fields[2],
                    'department': fields[3],
                    'page_title': fields[4],
                    'update_datetime': current_time,  # TSVの値ではなく現在時刻を使用
                    'ai_version': self.config.ai_model  # TSVの値ではなく実際のモデル名を使用
                }
            elif len(fields) >= 3:
                # 最小限のフィールドでもレコード作成を試みる
                return {
                    'fac_id_unif': context.get('fac_id_unif', ''),
                    'url': context.get('url', ''),
                    'type': fields[0] if fields[0] in ['s', 'g_txt', 'g_img', 'g_pdf', 'sg_txt', 'sg_img', 'sg_pdf'] else 's',
                    'department': fields[1] if len(fields) > 1 else '診療科不明',
                    'page_title': fields[2] if len(fields) > 2 else '',
                    'update_datetime': current_time,
                    'ai_version': self.config.ai_model
                }
        
        # doctor_info用の処理
        elif self.config.job_type == "doctor_info":
            if len(fields) >= 4:  # 最低限：output_order, department, position, name
                # 実際のAI出力形式に基づくマッピング:
                # [output_order, department, position, name, specialty/licence, url]
                # または [output_order, department, position, name, specialty, licence, url] 等
                
                # specialty と licence を分離して処理
                specialty = ''
                licence = ''
                others = ''
                
                # URLを検出
                url_field = ''
                remaining_fields = []
                
                if len(fields) > 4:
                    # 最後のフィールドがURLかチェック
                    if fields[-1].startswith('http'):
                        url_field = fields[-1]
                        remaining_fields = fields[4:-1] if len(fields) > 5 else []
                    else:
                        remaining_fields = fields[4:]
                
                # remaining_fieldsからspecialty, licence, othersを抽出
                if remaining_fields:
                    all_text = ' '.join(remaining_fields)
                    
                    # 専門分野パターン（specialty）
                    specialty_patterns = [
                        r'循環器', r'消化器', r'呼吸器', r'腎臓', r'糖尿病', r'血液',
                        r'神経内科', r'リウマチ', r'感染症', r'内分泌', r'腫瘍',
                        r'一般外科', r'心臓血管外科', r'脳神経外科', r'整形外科',
                        r'小児科', r'産婦人科', r'泌尿器科', r'皮膚科', r'眼科',
                        r'耳鼻咽喉科', r'精神科', r'放射線科', r'麻酔科', r'救急'
                    ]
                    
                    # 資格・認定パターン（licence）
                    licence_patterns = [
                        r'日本[^、，\s]+学会[^、，\s]*専門医',
                        r'日本[^、，\s]+学会[^、，\s]*認定医',
                        r'日本[^、，\s]+学会[^、，\s]*指導医',
                        r'[^、，\s]+専門医',
                        r'[^、，\s]+認定医',
                        r'[^、，\s]+指導医',
                        r'医学博士',
                        r'[^、，\s]+評議員',
                        r'[^、，\s]+理事'
                    ]
                    
                    import re
                    
                    # specialty抽出
                    specialty_list = []
                    for pattern in specialty_patterns:
                        if re.search(pattern, all_text):
                            specialty_list.append(pattern)
                    
                    # licence抽出
                    licence_list = []
                    for pattern in licence_patterns:
                        matches = re.findall(pattern, all_text)
                        licence_list.extend(matches)
                    
                    # リストを「/」で結合
                    specialty = '/'.join(specialty_list) if specialty_list else ''
                    licence = '/'.join(licence_list) if licence_list else ''
                    
                    # othersは元のテキスト（必要に応じて）
                    if len(remaining_fields) > 2:
                        others = remaining_fields[-1] if not remaining_fields[-1].startswith('http') else ''
                
                # AI出力のログから判明したパターン:
                # - 実際の出力順序: [output_order, department, position, name, ...]
                # - positionとnameの位置が入れ替わっている
                
                # フィールドの基本割り当て
                output_order = fields[0] if len(fields) > 0 else f"{context.get('fac_id_unif', '000000')}_00001"
                department = fields[1] if len(fields) > 1 else '診療科不明'
                position = fields[2] if len(fields) > 2 else ''
                name = fields[3] if len(fields) > 3 else ''
                
                
                # 実際のログデータから判明した問題:
                # nameに役職（「名誉院長」「院長」など）が入っている
                # positionに名前（「佐川 克明」「中村 政宏」など）が入っている
                # つまり、fields[2]とfields[3]が逆
                
                # 役職パターン（厳密）
                position_patterns = [
                    r'^名誉院長$', r'^院長$', r'^副院長$',
                    r'^.+部長$', r'^.+科長$', r'^.+医長$', r'^.+医員$',
                    r'^診療部長$', r'^理事長$', r'^理事$', r'^医師$'
                ]
                
                # まず、positionとnameを判定して入れ替える
                # positionフィールドが役職パターンに一致しない場合、逆転している可能性が高い
                position_matched = False
                for pattern in position_patterns:
                    if re.match(pattern, position):
                        position_matched = True
                        break
                
                # nameフィールドが役職パターンに一致する場合、確実に逆転している
                name_is_position = False
                for pattern in position_patterns:
                    if re.match(pattern, name):
                        name_is_position = True
                        break
                
                # 入れ替え処理
                if name_is_position or (not position_matched and len(position) > 0 and not position.startswith('http')):
                    # positionとnameを入れ替える
                    position, name = name, position
                    self.logger.log_info(f"入れ替え後: pos={position}, name={name}")
                
                # 重複を除去
                if licence:
                    licence_items = licence.split('/')
                    unique_licence = []
                    for item in licence_items:
                        if item not in unique_licence:
                            unique_licence.append(item)
                    licence = '/'.join(unique_licence)
                
                return {
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
                    'url': url_field if url_field else context.get('url', '')
                }
            else:
                return None
        
        # outpatient用の処理
        elif self.config.job_type == "outpatient":
            if len(fields) >= 12:
                # プロンプト仕様に従った正しいマッピング:
                # fac_id_unif	fac_nm	department	day_of_week	first_followup_visit	doctors_name	position	charge_week	charge_date	specialty	update_date	url_single_table	output_datetime	ai_version
                return {
                    'fac_id_unif': fields[0] if len(fields) > 0 else context.get('fac_id_unif', ''),
                    'fac_nm': fields[1] if len(fields) > 1 else '',
                    'department': fields[2] if len(fields) > 2 else '',
                    'day_of_week': fields[3] if len(fields) > 3 else '',
                    'first_followup_visit': fields[4] if len(fields) > 4 else '',
                    'doctors_name': fields[5] if len(fields) > 5 else '',
                    'position': fields[6] if len(fields) > 6 else '',
                    'charge_week': fields[7] if len(fields) > 7 else '',
                    'charge_date': fields[8] if len(fields) > 8 else '',
                    'specialty': fields[9] if len(fields) > 9 else '',
                    'update_date': fields[10] if len(fields) > 10 else '',
                    'url_single_table': fields[11] if len(fields) > 11 else context.get('url', ''),
                    'output_datetime': current_time,
                    'ai_version': self.config.ai_model
                }
            else:
                # フィールド数不足の場合はスキップ
                return None
        
        # 基本実装（他の機能用）
        return {
            'output_datetime': current_time,
            'ai_version': self.config.ai_model
        }
    
    def _generate_mock_response(self, content_type: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """モック応答生成（ローカルテスト用）"""
        current_time = self.logger.get_jst_now_iso()
        
        # 機能別のモック応答
        if self.config.job_type == "url_collect":
            # 複合分類のモック応答例
            return [{
                'fac_id_unif': context.get('fac_id_unif', 'mock_fac_123'),
                'url': context.get('url', 'https://mock-hospital.com/mock-page'),
                'type': 'sg_txt',  # 複合分類を例として使用
                'department': '消化器内科',
                'page_title': 'モック消化器内科のご案内',
                'update_datetime': current_time,
                'ai_version': 'mock_ai_model'
            }]
        
        elif self.config.job_type == "doctor_info":
            return [{
                'fac_id_unif': context.get('fac_id_unif', 'mock_fac_123'),
                'output_order': 1,
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
        
        elif self.config.job_type == "outpatient":
            return [{
                'fac_id_unif': context.get('fac_id_unif', 'mock_fac_123'),
                'fac_nm': 'モック病院',
                'department': 'モック診療科',
                'day_of_week': '月',
                'first_followup_visit': '初診・再診',
                'doctors_name': 'モック医師',
                'position': 'モック部長',
                'charge_week': '',
                'charge_date': '9:00-12:00',
                'specialty': 'モック専門外来',
                'update_date': '',
                'url_single_table': context.get('url', 'https://mock-hospital.com/mock-schedule'),
                'output_datetime': current_time,
                'ai_version': 'mock_ai_model'
            }]
        
        return []
    
    async def process_batch_async(
        self,
        batch_items: List[Dict[str, Any]],
        prompt: str,
        processor_func
    ) -> List[Dict[str, Any]]:
        """バッチ非同期処理"""
        if self._mock_mode:
            # モックモードでは同期処理
            results = []
            for item in batch_items:
                result = processor_func(item, prompt)
                results.extend(result)
            return results
        
        # 非同期処理（実装は各プロセッサで）
        return await self._process_batch_with_semaphore(batch_items, prompt, processor_func)
    
    async def _process_batch_with_semaphore(
        self,
        batch_items: List[Dict[str, Any]],
        prompt: str,
        processor_func
    ) -> List[Dict[str, Any]]:
        """セマフォを使用したバッチ処理"""
        semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)
        
        async def process_with_limit(item):
            async with semaphore:
                return processor_func(item, prompt)
        
        tasks = [process_with_limit(item) for item in batch_items]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 結果をフラット化
        all_records = []
        for result in results:
            if isinstance(result, Exception):
                self.logger.log_error(f"バッチ処理エラー: {str(result)}", error=result)
            elif isinstance(result, list):
                all_records.extend(result)
        
        return all_records