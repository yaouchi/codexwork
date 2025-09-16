#!/bin/bash

# DrTrack データ収集システム - 一括更新スクリプト
# 使用方法: ./update.sh

set -e  # エラーで停止

echo "============================================================"
echo "DrTrack データ収集システム 一括更新開始"
echo "============================================================"

# 作業ディレクトリに移動
cd /home/ouchi_48196/drtrack_data_collector

echo "1. プロンプトファイルをGCSにアップロード..."
echo "   - URL収集プロンプト更新..."
gsutil cp prompts/url_collect_prompt.txt gs://drtrack_test/url_collect/input/prompt.txt

echo "   - 専門医情報プロンプト更新..."
gsutil cp prompts/doctor_info_prompt.txt gs://drtrack_test/doctor_info/input/prompt.txt

echo "   - 外来担当医表プロンプト更新..."
gsutil cp prompts/outpatient_prompt.txt gs://drtrack_test/outpatient/input/prompt.txt

echo "   - 専門医情報検証プロンプト更新..."
gsutil cp prompts/doctor_info_validation_prompt.txt gs://drtrack_test/doctor_info_validation/input/prompt.txt

echo "✓ プロンプトファイル更新完了"

echo ""
echo "2. Dockerイメージビルド・プッシュ..."
gcloud builds submit --tag asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest

echo "✓ Dockerイメージ更新完了"

echo ""
echo "3. Cloud Run Jobsサービス更新..."

echo "   - URL収集ジョブ更新..."
gcloud run jobs update drtrack-url-collect \
  --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \
  --region=asia-northeast1

echo "   - 専門医情報収集ジョブ更新..."
gcloud run jobs update drtrack-doctor-info \
  --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \
  --region=asia-northeast1

echo "   - 外来担当医表収集ジョブ更新..."
gcloud run jobs update drtrack-outpatient \
  --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \
  --region=asia-northeast1

echo "   - 専門医情報検証ジョブ更新..."
gcloud run jobs update drtrack-doctor-info-validation \
  --image=asia-northeast1-docker.pkg.dev/i-rw-sandbox/drtrack-repo/drtrack-job:latest \
  --region=asia-northeast1 \
  --service-account=drtrack-cloudrun-sa@i-rw-sandbox.iam.gserviceaccount.com \
  --no-allow-unauthenticated \
  --vpc-connector=projects/i-rw-sandbox/locations/asia-northeast1/connectors/drtrack-vpc \
  --execution-environment=gen2 \
  --set-secrets="GEMINIKEY=projects/i-rw-sandbox/secrets/gemini-api-key:latest"

echo "✓ Cloud Run Jobs更新完了"

echo ""
echo "============================================================"
echo "DrTrack データ収集システム 一括更新完了"
echo "============================================================"
echo ""
echo "実行可能なジョブ:"
echo "  - drtrack-url-collect"
echo "  - drtrack-doctor-info" 
echo "  - drtrack-outpatient"
echo "  - drtrack-doctor-info-validation"
echo ""
echo "ジョブ実行例:"
echo "  gcloud run jobs execute drtrack-url-collect --region=asia-northeast1"
echo ""