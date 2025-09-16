# DrTrackデータ収集システム - Dockerfile

FROM python:3.11-slim

# 作業ディレクトリ設定
WORKDIR /app

# システムパッケージのインストール（ビルド効率化）
RUN apt-get update && apt-get install -y \
    # 基本システム依存関係
    ca-certificates \
    curl \
    # Python拡張のビルド用
    gcc \
    g++ \
    # 開発ヘッダー
    python3-dev \
    # ネットワーク・暗号化ライブラリ
    libssl-dev \
    libffi-dev \
    # 画像処理ライブラリ（Pillow用）
    libjpeg-dev \
    libpng-dev \
    # PDF処理用（PyMuPDF - パッケージがない場合はpipでビルド）
    libfreetype6-dev \
    # システムライブラリ
    libglib2.0-0 \
    # ビルド後にクリーンアップ
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Python依存関係のインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションファイルのコピー
COPY . .

# 実行権限設定
RUN chmod +x main.py

# 非rootユーザーでの実行
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# ヘルスチェック
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# エントリーポイント
ENTRYPOINT ["python", "main.py"]

# デフォルト環境変数（Cloud Run Jobsで上書きされる）
ENV JOB_TYPE=doctor_info
ENV PROJECT_ID=i-rw-sandbox
ENV INPUT_BUCKET=drtrack_test
ENV LOG_LEVEL=INFO
ENV USE_ASYNC=true

# メタデータ
LABEL version="1.0.0"
LABEL description="DrTrackデータ収集システム - マルチモーダル対応"