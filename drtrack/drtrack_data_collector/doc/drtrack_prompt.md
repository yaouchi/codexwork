# 医療施設データ収集システム統合開発プロンプト

## 概要
3つの既存医療データ収集システム（専門医情報、外来担当医表、URL収集）を統合し、単一コンテナで環境変数による機能切り替えが可能な統一システムを構築してください。

## 作業ディレクトリ
```
/home/nao/claudework/drtrack/drtrack_data_collector/
```

## 要求仕様

### 1. アーキテクチャ設計
- **統一コンテナ方式**: 1つのDockerイメージで3機能を切り替え
- **環境変数制御**: `JOB_TYPE`環境変数で機能選択（url_collect/doctor_info/outpatient）
- **共通ライブラリ**: GCS操作、AI処理、ログ処理を統一
- **既存仕様踏襲**: 出力項目・処理ロジックは現行システムを基本的に維持

### 2. ディレクトリ構成
```
drtrack_data_collector/
├── Dockerfile                    # 統一コンテナ定義
├── requirements.txt              # 統一依存関係
├── main.py                      # エントリーポイント
├── config.py                    # 統一設定管理
├── common/                      # 共通ライブラリ
│   ├── __init__.py
│   ├── gcs_client.py           # 統一GCS操作
│   ├── ai_client.py            # 統一AI処理
│   ├── logger.py               # 統一ログシステム
│   └── utils.py                # 共通ユーティリティ
├── processors/                  # 機能別プロセッサ
│   ├── __init__.py
│   ├── base_processor.py       # 基底プロセッサ
│   ├── url_collector.py        # URL収集処理
│   ├── doctor_info.py          # 専門医情報処理
│   └── outpatient.py           # 外来担当医表処理
├── prompts/                     # AIプロンプト
│   ├── url_collect_prompt.txt
│   ├── doctor_info_prompt.txt
│   └── outpatient_prompt.txt
├── tests/                       # テスト（ローカル実行用）
│   ├── __init__.py
│   ├── test_local.py           # ローカルテスト
│   └── sample_data/            # テストデータ
│       ├── sample_input.csv
│       └── sample_prompts/
└── README.md                    # 運用ドキュメント
```

### 3. GCS連携設定

#### バケット構成（プロジェクト: i-rw-sandbox）
```
drtrack_test/
├── doctor_info/
│   ├── input/     # input.csv, prompt.txt
│   ├── log/       # .log ファイル
│   └── tsv/       # 出力TSV
├── outpatient/
│   ├── input/     # input.csv, prompt.txt  
│   ├── log/       # .log ファイル
│   └── tsv/       # 出力TSV
└── url_collect/
    ├── input/     # input.csv, prompt.txt
    ├── log/       # .log ファイル
    └── tsv/       # 出力TSV
```

#### 入力ファイル仕様
- **input.csv**: `fac_id_unif`,`URL`または`url` 列を含むCSV（列名は大文字小文字どちらも対応）
- **prompt.txt**: 各機能用のAIプロンプト（GCS側から読み込み）

#### 出力ファイル仕様
- **ログファイル**: `{JOB_TYPE}_task_{task_index}_{timestamp}.log`
- **TSVファイル**: `{JOB_TYPE}_result_task_{task_index}_{timestamp}.tsv`

### 4. 機能別出力項目（既存仕様を踏襲）

#### URL収集 (url_collect)
```
fac_id_unif, url, page_type, confidence_score, output_datetime, ai_version
```

#### 専門医情報 (doctor_info)  
```
fac_id_unif, output_order, department, name, position, specialty, licence, others, output_datetime, ai_version, url
```

#### 外来担当医表 (outpatient)
```
fac_id_unif, fac_nm, department, day_of_week, first_followup_visit, doctors_name, position, charge_week, charge_date, specialty, update_date, url_single_table, output_datetime, ai_version
```

### 5. 環境変数設定

#### 実行時設定
- `JOB_TYPE`: 機能選択 (url_collect/doctor_info/outpatient)
- `CLOUD_RUN_TASK_INDEX`: タスクインデックス（Cloud Run Jobs自動設定）
- `CLOUD_RUN_TASK_COUNT`: 総タスク数（Cloud Run Jobs自動設定）

#### アプリケーション設定
- `PROJECT_ID`: i-rw-sandbox
- `INPUT_BUCKET`: drtrack_test  
- `LOG_LEVEL`: INFO
- `AI_MODEL`: gemini-2.5-flash-lite-preview-06-17

#### シークレット設定
- `GEMINIKEY`: `--set-secrets="GEMINIKEY=projects/************/secrets/irw-base-gemini-development-api-key:latest"`

### 6. コンテナ環境推奨スペック

#### リソース設定
- **CPU**: 4 vCPU（大量ページ処理・AI並列処理対応）
- **メモリ**: 8GB（HTMLパース・画像処理・大量データ処理対応）
- **タイムアウト**: 10800秒（3時間）
- **最大タスク数**: 20並列

#### タスク分割推奨（大規模処理対応）
- **URL収集**: 1タスクあたり5施設（1施設1000+ページ対応）
- **専門医情報**: 1タスクあたり20URL（大学病院1000医師対応）  
- **外来担当医表**: 1タスクあたり30URL（マルチモーダル処理考慮）

#### 進捗管理・中断再開対応
- **進捗ログ**: 処理済みURL/施設IDを詳細記録
- **中断時対応**: 処理失敗時も部分結果をTSV保存
- **再実行支援**: ログから未処理分を特定可能な形式で出力

### 7. ローカルテスト機能
- AIを使わないモックモードでの動作確認
- サンプルデータでの入出力テスト
- 環境変数 `LOCAL_TEST=true` でモック有効化
- `python tests/test_local.py` でローカル実行可能

### 8. Cloud Run Jobs デプロイ方式

#### ビルド・デプロイ
```bash
# 1. ビルド（1回）
gcloud builds submit --tag asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest

# 2. ジョブ作成/更新（各機能ごと）
gcloud run jobs update drtrack-url-collect \
  --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \
  --region=asia-northeast1 \
  --set-env-vars="JOB_TYPE=url_collect,PROJECT_ID=i-rw-sandbox,INPUT_BUCKET=drtrack_test" \
  --set-secrets="GEMINIKEY=projects/************/secrets/irw-base-gemini-development-api-key:latest" \
  --cpu=4 --memory=8Gi --max-retries=1 --task-timeout=10800 \
  --parallelism=20 --task-count=20

gcloud run jobs update drtrack-doctor-info \
  --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \
  --region=asia-northeast1 \
  --set-env-vars="JOB_TYPE=doctor_info,PROJECT_ID=i-rw-sandbox,INPUT_BUCKET=drtrack_test" \
  --set-secrets="GEMINIKEY=projects/************/secrets/irw-base-gemini-development-api-key:latest" \
  --cpu=4 --memory=8Gi --max-retries=1 --task-timeout=10800 \
  --parallelism=20 --task-count=20

gcloud run jobs update drtrack-outpatient \
  --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \
  --region=asia-northeast1 \
  --set-env-vars="JOB_TYPE=outpatient,PROJECT_ID=i-rw-sandbox,INPUT_BUCKET=drtrack_test" \
  --set-secrets="GEMINIKEY=projects/************/secrets/irw-base-gemini-development-api-key:latest" \
  --cpu=4 --memory=8Gi --max-retries=1 --task-timeout=10800 \
  --parallelism=20 --task-count=20
```

#### 実行
```bash
# 個別実行
gcloud run jobs execute drtrack-url-collect --region=asia-northeast1
gcloud run jobs execute drtrack-doctor-info --region=asia-northeast1  
gcloud run jobs execute drtrack-outpatient --region=asia-northeast1
```

### 9. 実装時の注意事項

#### 大規模処理対応
- **メモリ効率**: ストリーミング処理でメモリ使用量を抑制
- **進捗保存**: 定期的に処理済み状況をログ・TSVに保存
- **エラー耐性**: 一部エラーでも処理継続、詳細エラーログ出力
- **中断再開**: タイムアウト時も部分結果を保存し再実行可能に

#### 既存システムからの移植
- **dr_info_new**: 非同期処理・構造化ログ・エラーハンドリングを基準とする
- **outpatient_multi**: マルチモーダル処理（HTML/Image/PDF）ロジックを移植
- **url_collect_v3**: クローリング・AI分類ロジックを移植

#### タスク分散処理
- **動的負荷分散**: 入力サイズに応じて適切にタスク分割
- **処理状況ログ**: どのタスクがどの範囲を処理中かを明確に記録
- **失敗タスク特定**: エラー時にどの施設・URLで失敗したかを特定可能

#### 変更時の確認要求
- 出力項目の変更
- 処理ロジックの大幅変更
- 依存関係の大幅変更
- GCS パス構造の変更

#### GCS移植対応
- 絶対パス・相対パス設定を適切に
- 外部依存を最小限に（pandas, google-cloud-storage, aiohttp等の標準的なライブラリのみ）
- 環境変数チェック・バリデーション強化

### 10. 成果物
1. 動作する統一システム（上記ディレクトリ構成）
2. 各機能のプロンプトファイル
3. ローカルテスト機能
4. デプロイ用ドキュメント（README.md）
5. 既存システムから新システムへの移行ガイド

---

このプロンプトに基づいて、統一医療データ収集システムを構築してください。