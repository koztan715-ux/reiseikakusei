#!/usr/bin/env python3
"""
セミナーアーカイブ（動画/音声）をローカルWhisperで文字起こしするスクリプト。

セットアップ (初回のみ):
    pip install faster-whisper
    # ffmpeg が必要 (mac: brew install ffmpeg / Ubuntu: apt install ffmpeg)

使い方:
    python3 transcribe.py セミナー録画.mp4
    python3 transcribe.py セミナー録画.mp4 --model medium --out 文字起こし.txt

出力:
    <入力ファイル名>.txt  … 本文のみのプレーンテキスト（note下書き生成の入力に使う）
    <入力ファイル名>.srt  … タイムスタンプ付き字幕形式（該当箇所の見返しに便利）
"""
import argparse
import sys
from pathlib import Path


def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}".replace(".", ",")


def main():
    parser = argparse.ArgumentParser(description="セミナー録画/録音をローカルWhisperで文字起こしする")
    parser.add_argument("input", help="入力ファイル（mp4/mp3/wav 等）")
    parser.add_argument(
        "--model",
        default="medium",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisperモデルサイズ。大きいほど精度は上がるが遅くなる（デフォルト: medium）",
    )
    parser.add_argument("--language", default="ja", help="言語コード（デフォルト: ja）")
    parser.add_argument("--out", help="出力テキストファイル名（デフォルト: 入力ファイル名.txt）")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"入力ファイルが見つかりません: {input_path}")

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper がインストールされていません。`pip install faster-whisper` を実行してください。")

    txt_path = Path(args.out) if args.out else input_path.with_suffix(".txt")
    srt_path = input_path.with_suffix(".srt")

    print(f"モデル読み込み中: {args.model} （初回はダウンロードが走ります）")
    model = WhisperModel(args.model, device="cpu", compute_type="int8")

    print(f"文字起こし開始: {input_path}")
    segments, info = model.transcribe(
        str(input_path),
        language=args.language,
        vad_filter=True,  # 無音区間をスキップして高速化
    )

    with open(txt_path, "w", encoding="utf-8") as txt_f, open(srt_path, "w", encoding="utf-8") as srt_f:
        for i, seg in enumerate(segments, start=1):
            text = seg.text.strip()
            txt_f.write(text + "\n")
            srt_f.write(f"{i}\n")
            srt_f.write(f"{format_timestamp(seg.start)} --> {format_timestamp(seg.end)}\n")
            srt_f.write(f"{text}\n\n")
            print(f"[{format_timestamp(seg.start)}] {text}")

    print(f"\n完了。\n本文: {txt_path}\n字幕: {srt_path}")


if __name__ == "__main__":
    main()
