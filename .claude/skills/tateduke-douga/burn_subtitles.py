#!/usr/bin/env python3
"""SRTの字幕を動画に焼き込む（白抜き・黒フチ・センター揃え）。

このMacのffmpegはlibass無しの最小構成ビルドで subtitles/ass/drawtext フィルタが
使えないため、Pillowで字幕画像を描いて overlay フィルタで合成する。

単体でも使える:
    python3 burn_subtitles.py 入力.mp4 字幕.srt 出力.mp4 [bottom|middle] [文字サイズ]
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ModuleNotFoundError:
    import sys
    sys.exit(
        "\n必要な部品が入っていません: Pillow（画像を扱う部品）\n"
        "クロードコードに「動画編集の道具をそろえて」と言ってください。\n"
        "（すでに準備した方は、別の python で動かしている可能性があります。\n"
        "  Mac なら /usr/bin/python3 で試してみてください）\n")

# 字幕に使う日本語フォント。使っているパソコンにあるものを自動で探します。
# 好きなフォントを使いたいときは、環境変数 SUBTITLE_FONT にファイルの場所を入れてください。
def _find_font():
    import os
    cand = [os.environ.get("SUBTITLE_FONT", "")]
    cand += [
        # Mac
        "/System/Library/Fonts/ヒラギノ角ゴシック W7.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        # Windows
        "C:/Windows/Fonts/YuGothB.ttc",
        "C:/Windows/Fonts/meiryob.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
        # Linux
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ]
    for c in cand:
        if c and Path(c).exists():
            return c
    raise SystemExit(
        "日本語フォントが見つかりませんでした。\n"
        "クロードコードに「字幕用の日本語フォントを探して設定して」と言ってください。")

FONT_PATH = _find_font()
FONT_SIZE = 64
STROKE = 6            # 黒フチの太さ（文字サイズ64のときの値。以降は比例）
LINE_GAP = 20         # 行間（同上）
SIDE_MARGIN = 70      # 左右の余白
BOTTOM_MARGIN = 170   # 下揃えのときの画面下からの距離

# 行頭に置いてはいけない文字（禁則処理）
NO_LINE_START = "、。，．っゃゅょぁぃぅぇぉャュョッァィゥェォー」』）］！？"


def parse_srt(path):
    text = Path(path).read_text(encoding="utf-8")
    pattern = re.compile(
        r"(\d\d):(\d\d):(\d\d),(\d\d\d)\s*-->\s*(\d\d):(\d\d):(\d\d),(\d\d\d)\s*\n(.*?)(?=\n\s*\n|\Z)",
        re.S,
    )
    cues = []
    for m in pattern.finditer(text):
        g = m.groups()
        start = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000
        end = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000
        body = " ".join(line.strip() for line in g[8].strip().splitlines())
        if body:
            cues.append((start, end, body))
    return cues


def wrap(text, font, max_width):
    """日本語は単語区切りが無いので文字単位で折り返す。

    ただし単純に詰めると最終行だけ極端に短くなって不格好なので、
    必要な行数を出したうえで各行の長さを均等に割り振る。
    """
    n_lines, cur = 1, ""
    for ch in text:
        if font.getlength(cur + ch) <= max_width:
            cur += ch
        else:
            n_lines += 1
            cur = ch
    if n_lines == 1:
        return [text]

    per = -(-len(text) // n_lines)
    lines, pos = [], 0
    for i in range(n_lines):
        end = len(text) if i == n_lines - 1 else min(len(text), pos + per)
        while end < len(text) and text[end] in NO_LINE_START and end > pos + 1:
            end += 1
        if font.getlength(text[pos:end]) > max_width:   # 均等割りで溢れたら詰め直す
            end = pos
            while end < len(text) and font.getlength(text[pos:end + 1]) <= max_width:
                end += 1
        lines.append(text[pos:end])
        pos = end
        if pos >= len(text):
            break
    return [ln for ln in lines if ln]


def resolve_top(position, h, block_h):
    """字幕ブロックの上端Y座標を決める。

    position は "bottom" / "middle" のほか、数値（上からの割合）も取れる。
    0.6 なら「上から6割＝下から4割」の高さに文字の中心が来る。
    """
    if position == "middle":
        return (h - block_h) // 2
    if position == "bottom":
        return h - BOTTOM_MARGIN - block_h
    return int(h * float(position) - block_h / 2)


def render(cue_text, size, font, position, font_size):
    w, h = size
    # フチ・行間は文字サイズに比例させる（大きくしたときに詰まって見えないように）
    stroke = max(2, round(font_size * STROKE / 64))
    line_gap = round(font_size * LINE_GAP / 64)

    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    lines = wrap(cue_text, font, w - SIDE_MARGIN * 2)
    line_h = font_size + line_gap
    block_h = line_h * len(lines)

    top = max(0, min(h - block_h, resolve_top(position, h, block_h)))
    for i, line in enumerate(lines):
        draw.text(
            (w // 2, top + i * line_h),
            line,
            font=font,
            fill=(255, 255, 255, 255),
            stroke_width=stroke,
            stroke_fill=(0, 0, 0, 255),
            anchor="ma",  # 水平中央・上基準
        )
    return img


def video_size(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    ).stdout.strip().split(",")
    return int(out[0]), int(out[1])


def burn(src, srt, dst, position="bottom", font_size=FONT_SIZE, quiet=False):
    size = video_size(src)
    font = ImageFont.truetype(FONT_PATH, font_size, index=0)
    cues = parse_srt(srt)
    if not quiet:
        print(f"  字幕 {len(cues)}件 / {size[0]}x{size[1]} / 配置 {position} / {font_size}px")

    with tempfile.TemporaryDirectory() as tmp:
        inputs, chain, prev = [], [], "[0:v]"
        for i, (start, end, body) in enumerate(cues):
            png = f"{tmp}/sub{i:03d}.png"
            render(body, size, font, position, font_size).save(png)
            inputs += ["-i", png]
            label = f"[v{i}]"
            chain.append(
                f"{prev}[{i + 1}:v]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'{label}"
            )
            prev = label

        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src]
                       + inputs
                       + ["-filter_complex", ";".join(chain), "-map", prev, "-map", "0:a",
                          "-c:v", "libx264", "-crf", "20", "-preset", "medium",
                          "-pix_fmt", "yuv420p", "-c:a", "copy",
                          "-movflags", "+faststart", dst], check=True)
    return len(cues)


if __name__ == "__main__":
    pos = sys.argv[4] if len(sys.argv) > 4 else "bottom"
    fs = int(sys.argv[5]) if len(sys.argv) > 5 else FONT_SIZE
    burn(sys.argv[1], sys.argv[2], sys.argv[3], pos, fs)
    print(f"出力: {sys.argv[3]}")
