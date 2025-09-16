# DrTrackデータ収集システム - デプロイ・運用手順書

## 📋 **事前確認**

### ✅ 必須チェックリスト
1. `gcloud auth list` でログイン確認
2. `gcloud config get-value project` でプロジェクト確認（i-rw-sandbox）
3. `gcloud config set project i-rw-sandbox` でプロジェクト設定
4. `/home/ouchi_48196/` にコードコピー済み確認

---

## 🚀 **初回デプロイ（新システム構築時）**

### 1️⃣ GCSプロンプト配置（初回のみ）

```bash
# プロンプトファイルをGCSに配置
gsutil cp prompts/url_collect_prompt.txt gs://drtrack_test/url_collect/input/prompt.txt
gsutil cp prompts/doctor_info_prompt.txt gs://drtrack_test/doctor_info/input/prompt.txt  
gsutil cp prompts/outpatient_prompt.txt gs://drtrack_test/outpatient/input/prompt.txt

# 配置確認
gsutil ls gs://drtrack_test/*/input/prompt.txt
```

### 2️⃣ Docker Artifactレジストリ作成（初回のみ）

```bash
# レジストリ作成
gcloud artifacts repositories create drtrack-repo \
  --repository-format=docker \
  --location=asia-northeast1 \
  --description="DrTrackデータ収集システム"

# 作成確認
gcloud artifacts repositories list --location=asia-northeast1
```

### 3️⃣ 初回イメージビルド・プッシュ

```bash
# ディレクトリ移動（重要）
cd /home/ouchi_48196/drtrack_data_collector

# イメージビルド・プッシュ
gcloud builds submit --tag asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest
```

### 4️⃣ Cloud Run Jobs 初回作成

#### URL収集ジョブ

```bash
gcloud run jobs create drtrack-url-collect \
  --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \
  --region=asia-northeast1 \
  --service-account="sa-gemini-api-development@i-rw-sandbox.iam.gserviceaccount.com" \
  --set-env-vars="JOB_TYPE=url_collect,PROJECT_ID=i-rw-sandbox,INPUT_BUCKET=drtrack_test" \
  --set-secrets="GEMINIKEY=projects/584227794860/secrets/irw-base-gemini-development-api-key:latest" \
  --cpu=4 --memory=8Gi --max-retries=1 --task-timeout=10800 \
  --parallelism=20
```

#### 専門医情報収集ジョブ

```bash
gcloud run jobs create drtrack-doctor-info \
  --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \
  --region=asia-northeast1 \
  --service-account="sa-gemini-api-development@i-rw-sandbox.iam.gserviceaccount.com" \
  --set-env-vars="JOB_TYPE=doctor_info,PROJECT_ID=i-rw-sandbox,INPUT_BUCKET=drtrack_test" \
  --set-secrets="GEMINIKEY=projects/584227794860/secrets/irw-base-gemini-development-api-key:latest" \
  --cpu=4 --memory=8Gi --max-retries=1 --task-timeout=10800 \
  --parallelism=20
```

#### 外来担当医表収集ジョブ

```bash
gcloud run jobs create drtrack-outpatient \
  --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \
  --region=asia-northeast1 \
  --service-account="sa-gemini-api-development@i-rw-sandbox.iam.gserviceaccount.com" \
  --set-env-vars="JOB_TYPE=outpatient,PROJECT_ID=i-rw-sandbox,INPUT_BUCKET=drtrack_test" \
  --set-secrets="GEMINIKEY=projects/584227794860/secrets/irw-base-gemini-development-api-key:latest" \
  --cpu=4 --memory=8Gi --max-retries=1 --task-timeout=10800 \
  --parallelism=20
```

### 5️⃣ 初回デプロイ確認

```bash
# ジョブ一覧確認
gcloud run jobs list --region=asia-northeast1

# 個別ジョブ詳細確認
gcloud run jobs describe drtrack-url-collect --region=asia-northeast1
gcloud run jobs describe drtrack-doctor-info --region=asia-northeast1  
gcloud run jobs describe drtrack-outpatient --region=asia-northeast1
```

---

## 🔄 **日常運用（コード更新時）**

### 1️⃣ コードコピー・更新

```bash
# /home/ouchi_48196/ にコードをコピー（ユーザー作業）
# その後、ディレクトリ移動
cd /home/ouchi_48196/drtrack_data_collector
```

### 2️⃣ イメージ更新・プッシュ

```bash
# イメージビルド・プッシュ（バージョン更新）
gcloud builds submit --tag asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest
```

### 3️⃣ ジョブ更新（全ジョブ）

```bash
# URL収集ジョブ更新
gcloud run jobs update drtrack-url-collect \
  --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \
  --region=asia-northeast1

# 専門医情報収集ジョブ更新
gcloud run jobs update drtrack-doctor-info \
  --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \
  --region=asia-northeast1

# 外来担当医表収集ジョブ更新
gcloud run jobs update drtrack-outpatient \
  --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \
  --region=asia-northeast1
```

---

## ▶️ **ジョブ実行**

### 個別実行

```bash
# URL収集実行
gcloud run jobs execute drtrack-url-collect --region=asia-northeast1

# 専門医情報収集実行
gcloud run jobs execute drtrack-doctor-info --region=asia-northeast1

# 外来担当医表収集実行  
gcloud run jobs execute drtrack-outpatient --region=asia-northeast1
```

### 全ジョブ順次実行（推奨順序）

```bash
# 1. URL収集 → 2. 専門医情報 → 3. 外来担当医表
echo "1/3: URL収集開始"
gcloud run jobs execute drtrack-url-collect --region=asia-northeast1

echo "2/3: 専門医情報収集開始"
gcloud run jobs execute drtrack-doctor-info --region=asia-northeast1

echo "3/3: 外来担当医表収集開始"
gcloud run jobs execute drtrack-outpatient --region=asia-northeast1

echo "全ジョブ実行完了"
```

---

## 📊 **実行状況確認・ログ確認**

### ジョブ実行状況

```bash
# 実行中ジョブ確認
gcloud run jobs executions list --region=asia-northeast1

# 特定ジョブの実行状況
gcloud run jobs executions describe EXECUTION_NAME --region=asia-northeast1
```

### ログ確認

```bash
# 最新ログ確認
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=drtrack-doctor-info" --limit=50 --format="table(timestamp,jsonPayload.message)"

# エラーログ確認
gcloud logging read "resource.type=cloud_run_job AND severity>=ERROR" --limit=20

# 特定期間のログ確認
gcloud logging read "resource.type=cloud_run_job" --freshness=1h
```

### 出力結果確認

```bash
# TSV出力確認
gsutil ls gs://drtrack_test/*/tsv/

# ログ出力確認
gsutil ls gs://drtrack_test/*/log/

# 最新結果ダウンロード
gsutil cp gs://drtrack_test/doctor_info/tsv/* ./results/
```

---

## ⚙️ **設定変更・パラメータ調整**

### タスク数・並列度変更

```bash
# 並列度変更（例：40並列に変更）
gcloud run jobs update drtrack-doctor-info \
  --parallelism=40 --task-count=40 \
  --region=asia-northeast1
```

### 環境変数更新

```bash
# バッチサイズ変更例
gcloud run jobs update drtrack-doctor-info \
  --update-env-vars="MAX_CONCURRENT_REQUESTS=3" \
  --region=asia-northeast1
```

### プロンプト更新

```bash
# プロンプト更新時
gsutil cp prompts/doctor_info_prompt.txt gs://drtrack_test/doctor_info/input/prompt.txt
```

---

## 🆘 **トラブルシューティング**

### よくある問題と対処

#### 1. ビルドエラー
```bash
# Dockerfileの構文確認
cd /home/ouchi_48196/drtrack_data_collector
docker build --no-cache .
```

#### 2. ジョブ実行エラー
```bash
# 最新のエラーログ確認
gcloud logging read "resource.type=cloud_run_job AND severity=ERROR" --limit=5 --format="table(timestamp,jsonPayload.message)"
```

#### 3. メモリ不足エラー
```bash
# メモリ増強（16GBに変更）
gcloud run jobs update drtrack-doctor-info \
  --memory=16Gi \
  --region=asia-northeast1
```

#### 4. タイムアウトエラー
```bash
# タイムアウト延長（6時間に変更）
gcloud run jobs update drtrack-doctor-info \
  --task-timeout=21600 \
  --region=asia-northeast1
```

### 緊急時リセット

```bash
# ジョブ削除・再作成
gcloud run jobs delete drtrack-doctor-info --region=asia-northeast1
# その後、初回作成コマンドを再実行
```

---

## 💾 **データ管理**

### 入力データ準備

```bash
# 入力CSVファイルアップロード
gsutil cp input.csv gs://drtrack_test/doctor_info/input/input.csv
gsutil cp input.csv gs://drtrack_test/outpatient/input/input.csv
gsutil cp input.csv gs://drtrack_test/url_collect/input/input.csv
```

### 結果データダウンロード

```bash
# 最新結果まとめてダウンロード
mkdir -p results
gsutil -m cp gs://drtrack_test/*/tsv/*.tsv ./results/
gsutil -m cp gs://drtrack_test/*/log/*.log ./results/
```

---

## ⚡ **高速実行用ワンライナー**

### 更新・デプロイ・実行（一括）

```bash
cd /home/ouchi_48196/drtrack_data_collector && gcloud builds submit --tag asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest && gcloud run jobs update drtrack-url-collect --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest --region=asia-northeast1 && gcloud run jobs update drtrack-doctor-info --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest --region=asia-northeast1 && gcloud run jobs update drtrack-outpatient --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest --region=asia-northeast1
```

### よく使うコマンド集

```bash
# 現在のジョブ状況確認
alias job-status='gcloud run jobs list --region=asia-northeast1'

# 最新ログ確認
alias job-logs='gcloud logging read "resource.type=cloud_run_job" --limit=10 --format="table(timestamp,resource.labels.job_name,jsonPayload.message)"'

# 結果ファイル確認
alias job-results='gsutil ls gs://drtrack_test/*/tsv/'
```

---

**🔄 このファイルを最新に保ち、運用時は必ずこの手順に従ってください。**