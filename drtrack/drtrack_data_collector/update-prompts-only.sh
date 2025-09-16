#!/bin/bash

# DrTrack データ収集システム - プロンプトのみ更新スクリプト
# 使用方法: ./update-prompts-only.sh

set -e  # エラーで停止

echo "============================================================"
echo "DrTrack プロンプトファイル更新開始"
echo "============================================================"

# 作業ディレクトリに移動
cd /home/ouchi_48196/drtrack_data_collector

echo "プロンプトファイルをGCSにアップロード..."

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
echo "============================================================"
echo "プロンプト更新完了 - Dockerイメージ更新は不要"
echo "============================================================"
echo ""
echo "既存のジョブをそのまま実行できます:"
echo "  gcloud run jobs execute drtrack-url-collect --region=asia-northeast1"
echo ""