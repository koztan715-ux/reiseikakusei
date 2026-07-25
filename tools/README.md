# セミナーアーカイブ note販売 自動化ツール

セミナーの録画/録音を note の有料記事として販売するための、繰り返し使える
半自動化パイプライン。

```
録画/録音ファイル
     │  transcribe.py（ローカルWhisper、無料）
     ▼
文字起こしテキスト(.txt)
     │  note_draft_prompt.md をClaude Codeに貼り付け
     ▼
note記事の下書き（タイトル・目次・価格案・FAQ等）
     │  人が確認・note.comに投稿
     ▼
公開
```

## セットアップ（初回のみ、ご自身のPCで実行）

```bash
pip install faster-whisper
# ffmpeg が入っていない場合
#   mac: brew install ffmpeg
#   Ubuntu/Debian: sudo apt install ffmpeg
```

## 使い方

```bash
python3 tools/transcribe.py セミナー録画.mp4
```

- `セミナー録画.txt`（本文）と `セミナー録画.srt`（タイムスタンプ付き）が生成される
- モデルサイズは `--model` で変更可能（`tiny`〜`large-v3`。大きいほど高精度・低速）
- 長尺の録画はCPU環境だと時間がかかる（目安: `medium`モデルで実時間の1〜2倍程度）

文字起こしができたら `note_draft_prompt.md` の手順に沿ってClaude Codeに
note記事の下書きを依頼する。

## 注意事項

- このパイプラインは「文字起こし」と「下書き生成」までの自動化。
  note.comへの実際の投稿、価格の最終決定、薬機法・景表法上の表現チェックは
  必ず人が行うこと。
- 動画/音声ファイル自体はこのリポジトリにコミットしない（容量・著作権の観点から
  個人の作業フォルダで管理する）。
