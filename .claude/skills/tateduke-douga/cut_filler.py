#!/usr/bin/env python3
"""無音・フィラー（えーとー等）・間延びした語尾をまとめて詰める。

伸ばし音は「音は出ているのにスペクトルがほとんど変化しない」ので、
隣接フレームのスペクトル変化量(flux)で判定する。実測値は
    フィラー 0.16 / 通常の発話 0.40 前後 / 無音 0.51
なので 0.25 を境にすれば安全に切り分けられる。

単体でも使える:
    python3 cut_filler.py 入力.MOV 出力.mp4
"""
import subprocess
import sys
import tempfile
import wave

try:
    import numpy as np
except ModuleNotFoundError:
    import sys
    sys.exit(
        "\n必要な部品が入っていません: numpy（計算する部品）\n"
        "クロードコードに「動画編集の道具をそろえて」と言ってください。\n"
        "（すでに準備した方は、別の python で動かしている可能性があります。\n"
        "  Mac なら /usr/bin/python3 で試してみてください）\n")

SILENCE_DB = -42      # これ未満を無音とみなす
MIN_SILENCE = 0.60    # 無音とみなす最短の長さ（秒）
PAD = 0.10            # 無音を切るときに残す余白（秒）
FLUX_TH = 0.25        # これ未満を「伸ばし音」とみなす
MIN_SUSTAIN = 0.55    # 伸ばし音として処理する最短の長さ（秒）
KEEP_SUSTAIN = 0.25   # 語尾を詰めるとき残す長さ（秒）
FILLER_RATIO = 0.60   # 発話のかたまりのこの割合以上が伸ばし音なら丸ごと削除
HEAD_PAD = 0.08       # 最初の発話の手前に残す助走（秒）
TAIL_PAD = 0.30       # 最後の発話の後に残す余韻（秒）


def analyze(wav_path):
    w = wave.open(wav_path)
    sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    n, hop = 400, 160
    frames = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n)
    spec = np.abs(np.fft.rfft(frames, axis=1))
    rms = 20 * np.log10(np.sqrt((frames ** 2).mean(1)) + 1e-10)
    norm = spec / (spec.sum(1, keepdims=True) + 1e-12)
    flux = np.r_[0, np.abs(np.diff(norm, axis=0)).sum(1)]
    return np.arange(len(rms)) * hop / sr, rms, flux, len(x) / sr


def runs_of(mask, t, min_len, bridge=8):
    """Trueが続く区間を返す。bridgeフレーム以内の途切れは繋ぐ。"""
    out, i = [], 0
    while i < len(mask):
        if not mask[i]:
            i += 1
            continue
        j = i
        while j < len(mask):
            if mask[j]:
                j += 1
            elif j + bridge < len(mask) and mask[j:j + bridge].any():
                j += 1
            else:
                break
        a, b = t[i], t[min(j, len(t) - 1)]
        if b - a >= min_len:
            out.append((a, b))
        i = j
    return out


def merge(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals)
    out = [list(intervals[0])]
    for a, b in intervals[1:]:
        if a <= out[-1][1] + 0.01:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [tuple(x) for x in out]


def cut(src, dst, min_silence=MIN_SILENCE, min_sustain=MIN_SUSTAIN, quiet=False):
    """srcから不要な間を取り除いてdstへ書き出し、処理内容を返す。"""
    with tempfile.TemporaryDirectory() as tmp:
        wav = f"{tmp}/a.wav"
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src,
                        "-map", "0:a:0", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav],
                       check=True)
        t, rms, flux, dur = analyze(wav)

    silences = runs_of(rms < SILENCE_DB, t, min_silence)
    sustains = runs_of((flux < FLUX_TH) & (rms > SILENCE_DB), t, min_sustain)

    # 無音に挟まれた「発話のかたまり」を作る
    chunks, cursor = [], 0.0
    for a, b in silences:
        if a - cursor > 0.05:
            chunks.append((cursor, a))
        cursor = b
    if dur - cursor > 0.05:
        chunks.append((cursor, dur))

    remove = [(a + PAD, b - PAD) for a, b in silences if b - a > 2 * PAD]
    report, filler_chunks = [], []
    for a, b in sustains:
        chunk = next((c for c in chunks if c[0] - 0.05 <= a and b <= c[1] + 0.05), None)
        if chunk and (b - a) / (chunk[1] - chunk[0]) >= FILLER_RATIO:
            remove.append(chunk)                       # フィラーだけの塊 → 丸ごと削除
            filler_chunks.append(chunk)
            report.append((chunk[0], chunk[1], "フィラー丸ごと削除"))
        else:
            remove.append((a + KEEP_SUSTAIN, b))       # 語尾の伸ばし → 短く詰める
            report.append((a + KEEP_SUSTAIN, b, "語尾を詰める"))

    # 頭とお尻は余白を残さず、最初の発話の直前／最後の発話の直後で切る。
    # 残さないと録り始め・録り終わりの無音が細切れで残る。
    speech = [c for c in chunks if c not in filler_chunks]
    if speech:
        head, tail = speech[0][0], speech[-1][1]
        if head - HEAD_PAD > 0:
            remove.append((0.0, head - HEAD_PAD))
            report.append((0.0, head - HEAD_PAD, "録り始めの無音を削除"))
        if tail + TAIL_PAD < dur:
            remove.append((tail + TAIL_PAD, dur))
            report.append((tail + TAIL_PAD, dur, "録り終わりの無音を削除"))

    keep, cursor = [], 0.0
    for a, b in merge(remove):
        if a - cursor > 0.05:
            keep.append((cursor, a))
        cursor = max(cursor, b)
    if dur - cursor > 0.05:
        keep.append((cursor, dur))
    kept = sum(b - a for a, b in keep)

    if not quiet:
        print(f"  元の尺   : {dur:.2f}秒")
        print(f"  無音     : {len(silences)}箇所 / 伸ばし音 {len(sustains)}箇所")
        for a, b, why in sorted(report):
            print(f"    {a:6.2f}→{b:6.2f} ({b - a:5.2f}s) {why}")
        print(f"  カット後 : {kept:.2f}秒（{dur - kept:.2f}秒カット / {(dur - kept) / dur * 100:.1f}%）")

    parts = []
    for i, (a, b) in enumerate(keep):
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a:0]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
    parts.append("".join(f"[v{i}][a{i}]" for i in range(len(keep)))
                 + f"concat=n={len(keep)}:v=1:a=1[vout][aout]")

    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
                    "-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]",
                    "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", dst], check=True)
    return {"duration": dur, "kept": kept, "report": report}


if __name__ == "__main__":
    cut(sys.argv[1], sys.argv[2])
    print(f"出力: {sys.argv[2]}")
