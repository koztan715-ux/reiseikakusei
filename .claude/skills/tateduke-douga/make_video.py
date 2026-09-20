#!/usr/bin/env python3
"""動画1本を投稿できる形まで一気に仕上げる。

  カット（無音・フィラー・語尾・録り始め）→ 文字起こし → 字幕焼き込み → BGM合成 → 検証

使い方:
    python3 make_video.py IMG_1234.MOV
    python3 make_video.py IMG_1234.MOV --bgm 音源/akinoayumi.mp3 --ratio 5
    python3 make_video.py IMG_1234.MOV --pos middle --size 96

主なオプション:
    --bgm PATH    BGMの音源。省略するとBGM無しで仕上げる
    --ratio N     喋り声:音楽 の比。5なら 5:1（既定 5。大きいほど音楽が小さい）
    --pos         字幕の位置 bottom / middle（既定 bottom）
    --size N      字幕の文字サイズ（既定 64。1.5倍にしたいなら96）
    --out PATH    完成品の出力先（既定は 入力名_完成.mp4）
    --prompt STR  文字起こしに渡す固有名詞ヒント
"""
import argparse
import os
import difflib
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import burn_subtitles
import cut_filler

# 文字起こしの部品（モデル）の置き場所。「道具をそろえる」スキルでここに入ります。
MODEL = Path(os.environ.get("WHISPER_MODEL",
                            Path.home() / "whisper-models/ggml-large-v3-turbo.bin"))
# よく出てくる人名・固有名詞をここに書いておくと、文字起こしの精度が上がります。
DEFAULT_PROMPT = os.environ.get("WHISPER_HINT", "")
FADE_IN = 1.5
FADE_OUT = 2.5


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "csv=p=0", str(path)]).stdout.strip())


def mean_volume(path, limit=None):
    cmd = ["ffmpeg", "-hide_banner"]
    if limit:
        cmd += ["-t", f"{limit}"]
    cmd += ["-i", str(path), "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    return float(re.search(r"mean_volume: (-?[\d.]+) dB", err).group(1))


def peak_volume(path):
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-map", "0:a:0",
                          "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(re.search(r"max_volume: (-?[\d.]+) dB", err).group(1))


def transcribe(video, out_base, prompt):
    """カット後の動画からSRTを作る。必ずカット後に実行すること（時刻がずれるため）。"""
    with tempfile.TemporaryDirectory() as tmp:
        wav = f"{tmp}/a.wav"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
             "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav])
        run(["whisper-cli", "-m", str(MODEL), "-l", "ja", "-f", wav, "--prompt", prompt,
             "-mc", "0", "--entropy-thold", "2.8", "--temperature-inc", "0.2",
             "-osrt", "-of", str(out_base), "--no-prints"])
    return Path(f"{out_base}.srt")


def srt_text(path):
    body = [ln for ln in Path(path).read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().isdigit() and "-->" not in ln]
    return re.sub(r"[、。 　]", "", "".join(body))


def mix_bgm(video, bgm, dst, ratio):
    """喋り声:音楽 = ratio:1 になるゲインを実測から計算して合成する。"""
    dur = duration(video)
    speech, music = mean_volume(video), mean_volume(bgm, limit=dur)
    gain = speech - 20 * math.log10(ratio) - music
    fade_at = max(0.0, dur - FADE_OUT)
    print(f"  喋り声 {speech:.1f}dB / 音楽 {music:.1f}dB → 音楽を {gain:.1f}dB 調整（{ratio:g}:1）")

    flt = (f"[1:a]atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,volume={gain:.1f}dB,"
           f"afade=t=in:st=0:d={FADE_IN},afade=t=out:st={fade_at:.3f}:d={FADE_OUT}[bgm];"
           f"[0:a][bgm]amix=inputs=2:duration=first:normalize=0[aout]")
    # 映像は再エンコードせず音だけ差し替える
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video), "-i", str(bgm),
         "-filter_complex", flt, "-map", "0:v", "-map", "[aout]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dst)])


def main():
    p = argparse.ArgumentParser(description="動画を投稿できる形まで一気に仕上げる")
    p.add_argument("src")
    p.add_argument("--bgm")
    p.add_argument("--ratio", type=float, default=5)
    p.add_argument("--pos", default="bottom",
                   help="字幕の位置。bottom / middle / 数値（上からの割合。0.6なら下から4割の高さ）")
    p.add_argument("--size", type=int, default=64)
    p.add_argument("--out")
    p.add_argument("--prompt", default=DEFAULT_PROMPT)
    p.add_argument("--min-silence", type=float, default=cut_filler.MIN_SILENCE)
    p.add_argument("--min-sustain", type=float, default=cut_filler.MIN_SUSTAIN)
    a = p.parse_args()

    src = Path(a.src).expanduser().resolve()
    if not src.exists():
        sys.exit(f"ファイルがありません: {src}")
    if not MODEL.exists():
        sys.exit(f"whisperのモデルがありません: {MODEL}")

    out = Path(a.out).expanduser() if a.out else src.with_name(f"{src.stem}_完成.mp4")
    work = src.parent / f"{src.stem}_作業用"
    work.mkdir(exist_ok=True)
    cut_mp4, sub_mp4 = work / "1_カット.mp4", work / "2_字幕.mp4"

    print(f"■ 素材: {src.name}")
    print("① カット")
    cut_filler.cut(str(src), str(cut_mp4), a.min_silence, a.min_sustain)

    print("② 文字起こし")
    srt = transcribe(cut_mp4, work / "字幕", a.prompt)
    print(f"  {srt.name} を作成")

    print("③ 字幕を焼き込み")
    burn_subtitles.burn(str(cut_mp4), str(srt), str(sub_mp4), a.pos, a.size)

    if a.bgm:
        print("④ BGMを合成")
        mix_bgm(sub_mp4, Path(a.bgm).expanduser(), out, a.ratio)
    else:
        print("④ BGM無し（--bgm 未指定）")
        sub_mp4.replace(out)

    print("⑤ 検証")
    # 元の音声と突き合わせて、カットで言葉が欠けていないか確かめる
    orig_srt = transcribe(src, work / "元の字幕", a.prompt)
    sim = difflib.SequenceMatcher(None, srt_text(orig_srt), srt_text(srt)).ratio()
    peak = peak_volume(out)
    print(f"  文字起こしの一致率 : {sim * 100:.1f}%  {'OK' if sim >= 0.9 else '★要確認（言葉が欠けたかも）'}")
    print(f"  ピーク音量         : {peak:.1f}dB  {'OK' if peak < -0.5 else '★音割れの恐れ'}")
    print(f"  尺                 : {duration(src):.2f}秒 → {duration(out):.2f}秒")
    print(f"\n■ 完成: {out}")
    print(f"  （中間ファイルは {work.name}/ に残しています）")


if __name__ == "__main__":
    main()
