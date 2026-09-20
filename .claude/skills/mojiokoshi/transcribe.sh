#!/bin/zsh
# 音声ファイルを文字起こしするスクリプト（自分のパソコンの中だけで処理します）
#
# 使い方:
#   ./transcribe.sh <音声ファイル>
#   ./transcribe.sh <音声ファイル> "固有名詞ヒント（例: 山田太郎、〇〇株式会社）"
#
# 固有名詞ヒントを渡すと、人名・会社名の精度が上がります。

set -e

if [ $# -lt 1 ]; then
  echo "使い方:"
  echo "  $0 <音声ファイル>"
  echo "  $0 <音声ファイル> \"固有名詞ヒント\""
  echo "対応形式: mp3, m4a, wav, aiff, flac, mp4, mov など"
  exit 1
fi

INPUT="$1"
PROMPT="${2:-${WHISPER_HINT:-}}"

# 文字起こしの部品（モデル）の置き場所。「道具をそろえる」スキルでここに入ります。
MODEL="${WHISPER_MODEL:-$HOME/whisper-models/ggml-large-v3-turbo.bin}"
OUTPUT_DIR="${TRANSCRIBE_OUT:-$HOME/Desktop/文字起こし結果}"

if [ ! -f "$INPUT" ]; then
  echo "❌ ファイルが見つかりません: $INPUT"
  exit 1
fi

if [ ! -f "$MODEL" ]; then
  echo "❌ 文字起こしの部品が見つかりません: $MODEL"
  echo "   → クロードコードに「文字起こしの道具をそろえて」と言ってください。"
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

BASENAME=$(basename "$INPUT")
NAME="${BASENAME%.*}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TMP_WAV="/tmp/whisper_${TIMESTAMP}.wav"

echo "🎙  入力: $INPUT"
echo "📝 出力先: $OUTPUT_DIR/${NAME}.txt"
echo ""

# 音声を16kHzのwavに変換（whisperが読める形にする）
ffmpeg -y -loglevel error -i "$INPUT" -ar 16000 -ac 1 -c:a pcm_s16le "$TMP_WAV"

# 文字起こし
if [ -n "$PROMPT" ]; then
  whisper-cli -m "$MODEL" -l ja -f "$TMP_WAV" --prompt "$PROMPT" -otxt -of "$OUTPUT_DIR/${NAME}"
else
  whisper-cli -m "$MODEL" -l ja -f "$TMP_WAV" -otxt -of "$OUTPUT_DIR/${NAME}"
fi

rm -f "$TMP_WAV"
echo ""
echo "✅ 完了: $OUTPUT_DIR/${NAME}.txt"
