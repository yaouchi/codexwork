#!/usr/bin/env python3
"""
DrTrackデータ収集システム - メインエントリーポイント

4つの機能を環境変数JOB_TYPEで切り替え実行:
- url_collect: URL収集
- doctor_info: 専門医情報収集  
- outpatient: 外来担当医表収集
- doctor_info_validation: 専門医情報検証

使用方法:
    python main.py
    
環境変数:
    JOB_TYPE: 実行機能 (url_collect/doctor_info/outpatient/doctor_info_validation)
    GEMINIKEY: Gemini APIキー (Cloud Run Jobsでシークレット設定)
    PROJECT_ID: GCPプロジェクトID
    INPUT_BUCKET: 入力バケット名
    CLOUD_RUN_TASK_INDEX: タスクインデックス
    CLOUD_RUN_TASK_COUNT: 総タスク数
"""

import sys
import os
import traceback
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config import Config
from common.logger import UnifiedLogger
from processors import url_collector, doctor_info, outpatient, doctor_info_validation


def main():
    """メイン処理"""
    logger = None
    
    try:
        # 設定読み込み
        config = Config.from_env()
        
        # ログ設定
        logger = UnifiedLogger(
            system_name=f"drtrack-{config.job_type}",
            task_index=config.task_index,
            task_count=config.task_count
        )
        
        # 開始ログ
        logger.log_success("=" * 60)
        logger.log_success(f"DrTrackデータ収集システム開始: {config.job_type.upper()}")
        logger.log_success(f"タスク: {config.task_index+1}/{config.task_count}")
        logger.log_success(f"プロジェクト: {config.project_id}")
        logger.log_success("=" * 60)
        
        # 設定検証
        config.validate()
        logger.log_success("設定検証完了")
        
        # 機能別処理実行
        if config.job_type == "url_collect":
            logger.log_success("URL収集処理を開始")
            url_collector.run(config, logger)
            
        elif config.job_type == "doctor_info":
            logger.log_success("専門医情報収集処理を開始")
            doctor_info.run(config, logger)
            
        elif config.job_type == "outpatient":
            logger.log_success("外来担当医表収集処理を開始")
            outpatient.run(config, logger)
            
        elif config.job_type == "doctor_info_validation":
            logger.log_success("専門医情報検証処理を開始")
            doctor_info_validation.run(config, logger)
            
        else:
            raise ValueError(f"未対応のJOB_TYPE: {config.job_type}")
        
        # 成功ログ
        logger.log_success("=" * 60)
        logger.log_success(f"{config.job_type.upper()}処理が正常に完了しました")
        logger.log_success("=" * 60)
        
        return 0
        
    except KeyboardInterrupt:
        if logger:
            logger.log_warning("ユーザーによる中断")
        else:
            print("ユーザーによる中断")
        return 130  # SIGINT exit code
        
    except Exception as e:
        error_msg = f"致命的エラー: {str(e)}"
        
        if logger:
            logger.log_error("=" * 60)
            logger.log_error(error_msg)
            logger.log_error("=" * 60)
            logger.log_error("エラー詳細:")
            logger.log_error(traceback.format_exc())
        else:
            print(f"ERROR: {error_msg}")
            print("エラー詳細:")
            print(traceback.format_exc())
        
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)