"""
DrTrack HTTP処理クライアント

HTTP リクエスト送信、HTML処理、画像・PDF処理
"""

import asyncio
import aiohttp
import requests
from typing import Optional, Dict, Any, Union, List
from io import BytesIO
import fitz  # PyMuPDF for PDF processing
from PIL import Image

from config import Config, LOCAL_TEST
from .logger import UnifiedLogger
from .utils import validate_url, clean_html_content


class UnifiedHttpClient:
    """DrTrack HTTP処理クライアント"""
    
    def __init__(self, config: Config, logger: UnifiedLogger):
        self.config = config
        self.logger = logger
        self.session = None
        
        # 共通ヘッダー
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    async def __aenter__(self):
        """非同期コンテキストマネージャー開始"""
        if not LOCAL_TEST:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.config.request_timeout),
                headers=self.headers
            )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """非同期コンテキストマネージャー終了"""
        if self.session:
            await self.session.close()
    
    async def fetch_html_async(self, url: str) -> Optional[str]:
        """非同期HTML取得"""
        if LOCAL_TEST:
            return self._generate_mock_html(url)
        
        if not validate_url(url):
            self.logger.log_error(f"無効なURL: {url}", url=url)
            return None
        
        # HTTP URLをHTTPSに自動変換を試みる
        original_url = url
        if url.startswith('http://'):
            https_url = url.replace('http://', 'https://', 1)
            self.logger.log_info(f"HTTPSでの接続を試行: {original_url} -> {https_url}")
            
            # まずHTTPSで試行
            try:
                async with self.session.get(https_url) as response:
                    if response.status == 200:
                        url = https_url  # HTTPS接続成功
                        self.logger.log_success(f"HTTPS接続成功: {https_url}")
                    else:
                        self.logger.log_warning(f"HTTPS接続失敗 (status={response.status}), HTTPで再試行")
            except Exception as e:
                self.logger.log_warning(f"HTTPS接続失敗: {str(e)}, HTTPで再試行")
        
        try:
            self.logger.log_info(f"HTML取得開始: {url}")
            
            async with self.session.get(url) as response:
                if response.status == 200:
                    content = await response.text(encoding='utf-8')
                    
                    # コンテンツサイズチェック
                    if len(content) > self.config.max_content_length:
                        content = content[:self.config.max_content_length]
                        self.logger.log_warning(
                            f"HTMLコンテンツを切り詰めました: {self.config.max_content_length}文字",
                            url=url
                        )
                    
                    self.logger.log_success(
                        f"HTML取得完了: {len(content)}文字",
                        url=url,
                        content_length=len(content)
                    )
                    
                    return content
                else:
                    self.logger.log_error(
                        f"HTTP エラー: {response.status}",
                        url=url,
                        status_code=response.status
                    )
                    return None
        
        except Exception as e:
            self.logger.log_error(f"HTML取得エラー: {str(e)}", error=e, url=url)
            return None
    
    def fetch_html_sync(self, url: str) -> Optional[str]:
        """同期HTML取得"""
        if LOCAL_TEST:
            return self._generate_mock_html(url)
        
        if not validate_url(url):
            self.logger.log_error(f"無効なURL: {url}", url=url)
            return None
        
        try:
            self.logger.log_info(f"HTML取得開始（同期）: {url}")
            
            response = requests.get(
                url,
                timeout=self.config.request_timeout,
                headers=self.headers
            )
            response.raise_for_status()
            
            content = response.text
            
            # コンテンツサイズチェック
            if len(content) > self.config.max_content_length:
                content = content[:self.config.max_content_length]
                self.logger.log_warning(
                    f"HTMLコンテンツを切り詰めました: {self.config.max_content_length}文字",
                    url=url
                )
            
            self.logger.log_success(
                f"HTML取得完了（同期）: {len(content)}文字",
                url=url,
                content_length=len(content)
            )
            
            return content
        
        except Exception as e:
            self.logger.log_error(f"HTML取得エラー（同期）: {str(e)}", error=e, url=url)
            return None
    
    async def fetch_image_async(self, url: str, max_size: int = 20 * 1024 * 1024) -> Optional[bytes]:
        """非同期画像取得"""
        if LOCAL_TEST:
            return self._generate_mock_image()
        
        if not validate_url(url):
            self.logger.log_error(f"無効なURL: {url}", url=url)
            return None
        
        try:
            self.logger.log_info(f"画像取得開始: {url}")
            
            async with self.session.get(url) as response:
                if response.status == 200:
                    # サイズチェック
                    content_length = response.headers.get('content-length')
                    if content_length and int(content_length) > max_size:
                        self.logger.log_error(
                            f"画像サイズが制限を超過: {content_length} bytes",
                            url=url,
                            max_size=max_size
                        )
                        return None
                    
                    content = await response.read()
                    
                    if len(content) > max_size:
                        self.logger.log_error(
                            f"画像サイズが制限を超過: {len(content)} bytes",
                            url=url,
                            max_size=max_size
                        )
                        return None
                    
                    # 画像形式確認
                    if not self._is_valid_image(content):
                        self.logger.log_error(f"無効な画像形式", url=url)
                        return None
                    
                    self.logger.log_success(
                        f"画像取得完了: {len(content)} bytes",
                        url=url,
                        content_size=len(content)
                    )
                    
                    return content
                else:
                    self.logger.log_error(
                        f"HTTP エラー: {response.status}",
                        url=url,
                        status_code=response.status
                    )
                    return None
        
        except Exception as e:
            self.logger.log_error(f"画像取得エラー: {str(e)}", error=e, url=url)
            return None
    
    async def fetch_pdf_async(self, url: str, max_size: int = 50 * 1024 * 1024) -> Optional[bytes]:
        """非同期PDF取得"""
        if LOCAL_TEST:
            return self._generate_mock_pdf()
        
        if not validate_url(url):
            self.logger.log_error(f"無効なURL: {url}", url=url)
            return None
        
        try:
            self.logger.log_info(f"PDF取得開始: {url}")
            
            async with self.session.get(url) as response:
                if response.status == 200:
                    # サイズチェック
                    content_length = response.headers.get('content-length')
                    if content_length and int(content_length) > max_size:
                        self.logger.log_error(
                            f"PDFサイズが制限を超過: {content_length} bytes",
                            url=url,
                            max_size=max_size
                        )
                        return None
                    
                    content = await response.read()
                    
                    if len(content) > max_size:
                        self.logger.log_error(
                            f"PDFサイズが制限を超過: {len(content)} bytes",
                            url=url,
                            max_size=max_size
                        )
                        return None
                    
                    # PDF形式確認
                    if not self._is_valid_pdf(content):
                        self.logger.log_error(f"無効なPDF形式", url=url)
                        return None
                    
                    self.logger.log_success(
                        f"PDF取得完了: {len(content)} bytes",
                        url=url,
                        content_size=len(content)
                    )
                    
                    return content
                else:
                    self.logger.log_error(
                        f"HTTP エラー: {response.status}",
                        url=url,
                        status_code=response.status
                    )
                    return None
        
        except Exception as e:
            self.logger.log_error(f"PDF取得エラー: {str(e)}", error=e, url=url)
            return None
    
    def preprocess_html(self, html_content: str) -> str:
        """HTML前処理"""
        if not html_content:
            return ""
        
        try:
            # HTMLクリーンアップ
            cleaned_content = clean_html_content(html_content)
            
            # 長さ制限
            if len(cleaned_content) > self.config.max_content_length:
                cleaned_content = cleaned_content[:self.config.max_content_length]
                self.logger.log_warning(
                    f"HTML前処理後にコンテンツを切り詰めました: {self.config.max_content_length}文字"
                )
            
            return cleaned_content
        
        except Exception as e:
            self.logger.log_error(f"HTML前処理エラー: {str(e)}", error=e)
            return html_content
    
    def process_image_for_ai(self, image_data: bytes) -> Optional[bytes]:
        """AI処理用画像前処理"""
        if LOCAL_TEST:
            return image_data
        
        try:
            # PIL で画像を読み込み
            image = Image.open(BytesIO(image_data))
            
            # サイズ制限（Gemini API制限対応）
            max_dimension = 3072
            if image.width > max_dimension or image.height > max_dimension:
                # アスペクト比を保持してリサイズ
                ratio = min(max_dimension / image.width, max_dimension / image.height)
                new_size = (int(image.width * ratio), int(image.height * ratio))
                image = image.resize(new_size, Image.Resampling.LANCZOS)
                
                self.logger.log_info(
                    f"画像リサイズ完了: {new_size[0]}x{new_size[1]}",
                    original_size=(image.width, image.height),
                    new_size=new_size
                )
            
            # JPEG形式で出力
            output = BytesIO()
            image.convert('RGB').save(output, format='JPEG', quality=85)
            
            return output.getvalue()
        
        except Exception as e:
            self.logger.log_error(f"画像前処理エラー: {str(e)}", error=e)
            return image_data
    
    def convert_pdf_to_images(self, pdf_data: bytes, max_pages: int = 10) -> List[bytes]:
        """PDF を画像に変換"""
        if LOCAL_TEST:
            return [self._generate_mock_image()]
        
        try:
            doc = fitz.open(stream=pdf_data, filetype="pdf")
            images = []
            
            page_count = min(len(doc), max_pages)
            self.logger.log_info(f"PDF変換開始: {page_count}ページ")
            
            for page_num in range(page_count):
                page = doc.load_page(page_num)
                
                # 画像として描画（200 DPI）
                mat = fitz.Matrix(200/72, 200/72)
                pix = page.get_pixmap(matrix=mat)
                
                # PNGバイトとして取得
                img_data = pix.pil_tobytes(format="JPEG", quality=85)
                images.append(img_data)
            
            doc.close()
            
            self.logger.log_success(f"PDF変換完了: {len(images)}ページ")
            return images
        
        except Exception as e:
            self.logger.log_error(f"PDF変換エラー: {str(e)}", error=e)
            return []
    
    def _is_valid_image(self, content: bytes) -> bool:
        """画像形式確認"""
        try:
            Image.open(BytesIO(content))
            return True
        except:
            return False
    
    def _is_valid_pdf(self, content: bytes) -> bool:
        """PDF形式確認"""
        try:
            fitz.open(stream=content, filetype="pdf")
            return True
        except:
            return False
    
    def _generate_mock_html(self, url: str) -> str:
        """モックHTML生成"""
        return f"""
        <html>
        <body>
        <h1>モック病院</h1>
        <div class="staff">
            <h2>医師紹介</h2>
            <p>診療科: モック内科</p>
            <p>医師名: モック太郎</p>
            <p>役職: 部長</p>
        </div>
        <div class="schedule">
            <h2>外来担当医表</h2>
            <table>
            <tr><th>診療科</th><th>月</th><th>火</th></tr>
            <tr><td>モック内科</td><td>モック太郎</td><td>モック花子</td></tr>
            </table>
        </div>
        <!-- Mock URL: {url} -->
        </body>
        </html>
        """
    
    def _generate_mock_image(self) -> bytes:
        """モック画像生成"""
        # 1x1 pixel JPEG
        return bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46])
    
    def _generate_mock_pdf(self) -> bytes:
        """モックPDF生成"""
        # 最小PDFヘッダー
        return b'%PDF-1.4\nMock PDF Content'