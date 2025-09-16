#!/bin/bash

# DrTrack 専門医情報検証機能 - 初期設定スクリプト
# 使用方法: ./setup-doctor-info-validation.sh

set -e  # エラーで停止

echo "============================================================"
echo "DrTrack 専門医情報検証機能 初期設定開始"
echo "============================================================"

# 作業ディレクトリに移動
cd /home/ouchi_48196/drtrack_data_collector

echo "1. GCSディレクトリの作成..."

echo "   - プロンプト用ディレクトリ作成..."
gsutil -m mkdir -p gs://drtrack_test/doctor_info_validation/input/ 2>/dev/null || echo "   (既に存在しています)"

echo "   - 結果用ディレクトリ作成..."
gsutil -m mkdir -p gs://drtrack_test/doctor_info_validation/tsv/ 2>/dev/null || echo "   (既に存在しています)"

echo "   - ログ用ディレクトリ作成..."
gsutil -m mkdir -p gs://drtrack_test/doctor_info_validation/log/ 2>/dev/null || echo "   (既に存在しています)"

echo "✓ GCSディレクトリ作成完了"

echo ""
echo "2. プロンプトファイルの初期アップロード..."
gsutil cp prompts/doctor_info_validation_prompt.txt gs://drtrack_test/doctor_info_validation/input/prompt.txt

echo "✓ プロンプトファイル配置完了"

echo ""
echo "3. Dockerイメージの確認・ビルド..."
echo "   現在のイメージをビルド・プッシュします..."
gcloud builds submit --tag asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest

echo "✓ Dockerイメージ準備完了"

echo ""
echo "4. Cloud Run Jobs新規作成..."

# 既存ジョブの確認
if gcloud run jobs describe drtrack-doctor-info-validation --region=asia-northeast1 >/dev/null 2>&1; then
    echo "   ジョブが既に存在しています。更新します..."
    gcloud run jobs update drtrack-doctor-info-validation \
      --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \
      --region=asia-northeast1 \
      --service-account=drtrack-cloudrun-sa@i-rw-sandbox.iam.gserviceaccount.com \
      --no-allow-unauthenticated \
      --vpc-connector=projects/i-rw-sandbox/locations/asia-northeast1/connectors/drtrack-vpc \
      --execution-environment=gen2 \
      --set-secrets="GEMINIKEY=projects/i-rw-sandbox/secrets/gemini-api-key:latest"
else
    echo "   新規ジョブを作成します..."
    gcloud run jobs create drtrack-doctor-info-validation \
      --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \
      --region=asia-northeast1 \
      --set-env-vars="JOB_TYPE=doctor_info_validation" \
      --task-count=10 \
      --parallelism=10 \
      --memory=2Gi \
      --cpu=1 \
      --max-retries=3 \
      --task-timeout=3600 \
      --service-account=drtrack-cloudrun-sa@i-rw-sandbox.iam.gserviceaccount.com \
      --no-allow-unauthenticated \
      --vpc-connector=projects/i-rw-sandbox/locations/asia-northeast1/connectors/drtrack-vpc \
      --execution-environment=gen2 \
      --set-secrets="GEMINIKEY=projects/i-rw-sandbox/secrets/gemini-api-key:latest"
fi

echo "✓ Cloud Run Jobs設定完了"

echo ""
echo "============================================================"
echo "DrTrack 専門医情報検証機能 初期設定完了"
echo "============================================================"
echo ""
echo "設定内容:"
echo "  - ジョブ名: drtrack-doctor-info-validation"
echo "  - タスク数: 10並列"
echo "  - メモリ: 2Gi"
echo "  - CPU: 1"
echo "  - タイムアウト: 3600秒"
echo ""
echo "実行方法:"
echo "  gcloud run jobs execute drtrack-doctor-info-validation --region=asia-northeast1"
echo ""
echo "注意事項:"
echo "  - 実行前に gs://drtrack_test/doctor_info/tsv/ に検証対象TSVファイルがあることを確認してください"
echo "  - 結果は gs://drtrack_test/doctor_info_validation/tsv/ に出力されます"
echo ""
echo "今後の更新は ./update.sh で実行できます"
echo ""