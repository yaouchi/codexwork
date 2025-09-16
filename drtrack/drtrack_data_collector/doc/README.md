# DrTrackデータ収集システム

3つの医療データ収集機能を統合した Cloud Run Jobs アプリケーション

## 🎯 概要

このシステムは以下の3つの機能を単一コンテナで提供します：

- **URL収集** (`url_collect`): 医療施設ウェブサイトから専門医・外来担当医ページのURL収集
- **専門医情報収集** (`doctor_info`): 医師情報ページから専門医情報を抽出
- **外来担当医表収集** (`outpatient`): HTML・画像・PDFから外来担当医表を抽出

## 📁 プロジェクト構成

```
drtrack_data_collector/
├── main.py                 # メインエントリーポイント
├── config.py               # 統一設定管理
├── requirements.txt        # Python依存関係
├── Dockerfile             # コンテナ定義
├── README.md              # このファイル
│
├── common/                # 共通ライブラリ
│   ├── logger.py         # 統一ログシステム
│   ├── gcs_client.py     # GCS操作
│   ├── ai_client.py      # AI処理
│   ├── http_client.py    # HTTP処理
│   └── utils.py          # ユーティリティ
│
├── processors/           # 機能別プロセッサ
│   ├── url_collector.py   # URL収集処理
│   ├── doctor_info.py     # 専門医情報収集
│   ├── outpatient.py      # 外来担当医表収集
│   └── base_processor.py  # プロセッサ基底クラス
│
├── prompts/              # AIプロンプトファイル
│   ├── url_collect_prompt.txt
│   ├── doctor_info_prompt.txt
│   └── outpatient_prompt.txt
│
├── update.sh             # 一括更新スクリプト
├── update-prompts-only.sh # プロンプトのみ更新
├── update-code-only.sh   # コードのみ更新
│
└── tests/              # テスト
    ├── test_local.py   # ローカルテスト
    └── sample_data/    # テストデータ
```

## 🚀 デプロイ・実行方法

### 1. 🛠️ 一括更新スクリプト（推奨）

コードやプロンプトの変更後、以下のスクリプトで一括更新できます：

```bash
# 全て更新（プロンプト + コード + Cloud Run Jobs）
./update.sh

# プロンプトファイルのみ更新
./update-prompts-only.sh

# コードのみ更新（Dockerイメージ + Cloud Run Jobs）
./update-code-only.sh
```

### 2. 手動更新方法

#### 2.1 イメージビルド・プッシュ

```bash
gcloud builds submit --tag asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest
```

#### 2.2 プロンプトファイル更新

```bash
gsutil cp prompts/url_collect_prompt.txt gs://drtrack_test/url_collect/input/prompt.txt
gsutil cp prompts/doctor_info_prompt.txt gs://drtrack_test/doctor_info/input/prompt.txt  
gsutil cp prompts/outpatient_prompt.txt gs://drtrack_test/outpatient/input/prompt.txt
```

#### 2.3 ジョブ作成・更新

```bash
# URL収集ジョブ
gcloud run jobs update drtrack-url-collect \\
  --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \\
  --region=asia-northeast1 \\
  --set-env-vars="JOB_TYPE=url_collect,PROJECT_ID=i-rw-sandbox,INPUT_BUCKET=drtrack_test" \\
  --set-secrets="GEMINIKEY=projects/************/secrets/irw-base-gemini-development-api-key:latest" \\
  --cpu=4 --memory=8Gi --max-retries=1 --task-timeout=10800 \\
  --parallelism=20 --task-count=20

# 専門医情報収集ジョブ
gcloud run jobs update drtrack-doctor-info \\
  --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \\
  --region=asia-northeast1 \\
  --set-env-vars="JOB_TYPE=doctor_info,PROJECT_ID=i-rw-sandbox,INPUT_BUCKET=drtrack_test" \\
  --set-secrets="GEMINIKEY=projects/************/secrets/irw-base-gemini-development-api-key:latest" \\
  --cpu=4 --memory=8Gi --max-retries=1 --task-timeout=10800 \\
  --parallelism=20 --task-count=20

# 外来担当医表収集ジョブ
gcloud run jobs update drtrack-outpatient \\
  --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \\
  --region=asia-northeast1 \\
  --set-env-vars="JOB_TYPE=outpatient,PROJECT_ID=i-rw-sandbox,INPUT_BUCKET=drtrack_test" \\
  --set-secrets="GEMINIKEY=projects/************/secrets/irw-base-gemini-development-api-key:latest" \\
  --cpu=4 --memory=8Gi --max-retries=1 --task-timeout=10800 \\
  --parallelism=20 --task-count=20
```

### 3. ジョブ実行

```bash
# 個別実行
gcloud run jobs execute drtrack-url-collect --region=asia-northeast1
gcloud run jobs execute drtrack-doctor-info --region=asia-northeast1
gcloud run jobs execute drtrack-outpatient --region=asia-northeast1

# 実行状況確認
gcloud run jobs describe drtrack-url-collect --region=asia-northeast1
gcloud logging read "resource.type=cloud_run_job" --limit=50 --format="table(timestamp,textPayload)"
```

## 📊 入出力仕様

### GCSバケット構成

```
drtrack_test/
├── url_collect/
│   ├── input/    # input.csv, prompt.txt
│   ├── log/      # ログファイル
│   └── tsv/      # 結果TSV
├── doctor_info/
│   ├── input/    # input.csv, prompt.txt
│   ├── log/      # ログファイル
│   └── tsv/      # 結果TSV
└── outpatient/
    ├── input/    # input.csv, prompt.txt
    ├── log/      # ログファイル
    └── tsv/      # 結果TSV
```

### 入力ファイル形式

**input.csv**
```csv
fac_id_unif,URL (またはurl)
123456789,https://example-hospital.com/doctors
987654321,https://another-hospital.com/outpatient
```

### 出力形式

#### URL収集 (url_collect)
```
fac_id_unif	url	page_type	confidence_score	output_datetime	ai_version
```

#### 専門医情報 (doctor_info)
```
fac_id_unif	output_order	department	name	position	specialty	licence	others	output_datetime	ai_version	url
```

#### 外来担当医表 (outpatient)
```
fac_id_unif	fac_nm	department	day_of_week	first_followup_visit	doctors_name	position	charge_week	charge_date	specialty	update_date	url_single_table	output_datetime	ai_version
```

## 🧪 ローカルテスト

```bash
# テスト実行
python tests/test_local.py

# または個別機能テスト
export LOCAL_TEST=true
export JOB_TYPE=doctor_info
python main.py
```

## ⚙️ 設定

### 環境変数

| 変数名 | 説明 | デフォルト値 |
|--------|------|-------------|
| `JOB_TYPE` | 実行機能 | 必須 |
| `PROJECT_ID` | GCPプロジェクトID | i-rw-sandbox |
| `INPUT_BUCKET` | 入力バケット名 | drtrack_test |
| `GEMINIKEY` | Gemini APIキー | 必須（シークレット） |
| `LOCAL_TEST` | ローカルテストモード | false |
| `USE_ASYNC` | 非同期処理使用 | true |
| `LOG_LEVEL` | ログレベル | INFO |

### リソース設定

- **CPU**: 4 vCPU（大量データ処理対応）
- **メモリ**: 8GB（画像・PDF処理対応）
- **タイムアウト**: 3時間（10800秒）
- **並列度**: 20タスク

### タスク分割推奨

- **URL収集**: 1タスクあたり5施設（1施設1000+ページ対応）
- **専門医情報**: 1タスクあたり20URL（大学病院1000医師対応）
- **外来担当医表**: 1タスクあたり30URL（マルチモーダル処理考慮）

## 🔍 主要機能

### 統一アーキテクチャ

- **共通ライブラリ**: GCS操作、AI処理、ログ処理を統一
- **構造化ログ**: JSON形式でBigQuery連携対応
- **エラーハンドリング**: Tenacityによる高度なリトライ機能

### マルチモーダル処理

- **HTML**: テキスト抽出・前処理
- **画像**: リサイズ・最適化
- **PDF**: ページ単位での画像変換（最大10ページ）

### 大規模データ対応

- **メモリ効率**: ストリーミング処理でメモリ使用量抑制
- **進捗管理**: 処理状況の詳細ログ
- **中断再開**: 部分結果の保存機能

## 📈 パフォーマンス

### 処理能力

- **URL収集**: 1施設あたり約800ページまで対応
- **専門医情報**: 大学病院1000医師まで対応
- **外来担当医表**: マルチモーダル処理で高精度抽出

### メモリ最適化

- **バッチ処理**: 適切なサイズでの分割処理
- **ガベージコレクション**: 定期的なメモリクリーンアップ
- **コンテンツ制限**: HTML 30,000文字、画像 20MB、PDF 50MB

## 🔧 開発・カスタマイズ

### プロンプト調整

各機能のプロンプトは `prompts/` ディレクトリで管理：
- URL収集用: `url_collect_prompt.txt`
- 専門医情報用: `doctor_info_prompt.txt`
- 外来担当医表用: `outpatient_prompt.txt`

### 新機能追加

1. `processors/` に新プロセッサー追加
2. `BaseProcessor` を継承
3. `main.py` に処理分岐追加
4. プロンプトファイル作成

## 📚 トラブルシューティング

### よくある問題

1. **メモリ不足**
   - バッチサイズを小さくする
   - 並列数を減らす

2. **タイムアウト**
   - `task-timeout` を増やす
   - 入力データを分割する

3. **AI処理エラー**
   - プロンプトを確認
   - コンテンツサイズを調整

### ログ確認

```bash
# Cloud Loggingでログを確認
gcloud logging read "resource.type=cloud_run_job AND jsonPayload.system=drtrack-doctor-info"
```

## 📝 ライセンス

内部使用のみ

## 🤝 サポート

システムに関する質問や問題は開発チームまでお問い合わせください。