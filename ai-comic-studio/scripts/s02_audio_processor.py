"""
s02 — 音频处理模块
===================
功能：
1. edge-tts 配音生成（含单词级时间戳）
2. BGM 处理（裁剪、循环、淡入淡出）
3. 配音 + BGM 混音
4. 输出字幕时间戳信息供 s03 使用
"""

import os
import json
import asyncio
import logging
from pathlib import Path
from typing import Optional

import edge_tts
from pydub import AudioSegment

logger = logging.getLogger("pipeline.audio")

# ============================================================
# TTS 配音生成
# ============================================================

async def _tts_single(text: str, voice: str, rate: str, volume: str,
                      output_path: str) -> list[dict]:
    """
    用 edge-tts 生成单段配音，返回单词级时间戳

    返回: [{"text": "今天", "offset": 1.23, "duration": 0.45}, ...]
    """
    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
    timestamps = []

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            with open(output_path, "ab") as f:
                f.write(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            timestamps.append({
                "text": chunk["text"],
                "offset": chunk["offset"] / 1_000_0000,  # 100ns → 秒
                "duration": chunk["duration"] / 1_000_0000,
            })

    return timestamps


def generate_tts(text_lines: list[str], config: dict,
                 working_dir: str) -> list[dict]:
    """
    批量生成 TTS 配音

    参数:
        text_lines: 剧本每行文本
        config: 配置字典 (audio.tts 部分)
        working_dir: 工作目录

    返回: 每句的音频信息和时间戳
    """
    tts_cfg = config.get("audio", {}).get("tts", {})
    voice = tts_cfg.get("voice", "zh-CN-XiaoxiaoNeural")
    rate = tts_cfg.get("rate", "+0%")
    volume = tts_cfg.get("volume", "+0%")

    audio_dir = Path(working_dir) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    segments = []
    tasks = []

    for i, line in enumerate(text_lines):
        if not line.strip():
            continue
        output_path = str(audio_dir / f"tts_{i:04d}.mp3")
        tasks.append(_tts_single(line, voice, rate, volume, output_path))

    # 并行执行所有 TTS 任务
    all_timestamps = asyncio.run(_run_tts_tasks(tasks))

    # 构建分段信息
    current_offset = 0.0
    valid_lines = [l for l in text_lines if l.strip()]
    for i, (line, ts) in enumerate(zip(valid_lines, all_timestamps)):
        if ts:
            seg_duration = ts[-1]["offset"] + ts[-1]["duration"]
        else:
            seg_duration = 0.0

        segments.append({
            "index": i,
            "text": line,
            "file": f"audio/tts_{i:04d}.mp3",
            "start": round(current_offset, 3),
            "end": round(current_offset + seg_duration, 3),
            "duration": round(seg_duration, 3),
            "word_timestamps": ts,
        })
        current_offset += seg_duration

    logger.info(f"TTS 配音完成: {len(segments)} 句, 总时长 {current_offset:.1f}s")

    # 保存时间戳信息供字幕模块使用
    tts_info = {
        "segments": segments,
        "total_duration": round(current_offset, 3),
    }
    info_path = Path(working_dir) / "audio" / "tts_info.json"
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(tts_info, f, ensure_ascii=False, indent=2)

    return segments


async def _run_tts_tasks(tasks):
    """并发执行所有 TTS 任务"""
    results = await asyncio.gather(*tasks)
    return results


# ============================================================
# BGM 处理
# ============================================================

def process_bgm(bgm_file: str, total_duration: float, config: dict,
                output_dir: str) -> str:
    """
    处理背景音乐

    参数:
        bgm_file: BGM 文件路径
        total_duration: 需要填充的总时长（秒）
        config: 配置字典
        output_dir: 输出目录

    返回: 处理后的 BGM 文件路径
    """
    bgm_cfg = config.get("audio", {}).get("bgm", {})
    fade_in = bgm_cfg.get("fade_in", 2.0)
    fade_out = bgm_cfg.get("fade_out", 3.0)
    loop = bgm_cfg.get("loop", True)
    target_volume = bgm_cfg.get("volume", 0.3)

    output_path = Path(output_dir) / "bgm_processed.mp3"

    if not bgm_file or not os.path.exists(bgm_file):
        logger.warning("未找到 BGM 文件，跳过背景音乐处理")
        return ""

    logger.info(f"处理 BGM: {bgm_file}")

    try:
        bgm = AudioSegment.from_file(bgm_file)
        bgm_duration = len(bgm) / 1000.0  # 秒

        # 循环或裁剪
        if loop and bgm_duration < total_duration:
            repeats = int(total_duration // bgm_duration) + 1
            bgm = bgm * repeats

        # 裁剪到目标时长（毫秒）
        target_ms = int(total_duration * 1000)
        bgm = bgm[:target_ms]

        # 音量调整
        # pydub 的 dB 调整: 原 volume=1.0 对应 0dB
        import math
        if target_volume < 1.0:
            db_change = 20 * math.log10(max(target_volume, 0.01))
            bgm = bgm.apply_gain(db_change)

        # 淡入淡出
        if fade_in > 0:
            bgm = bgm.fade_in(int(fade_in * 1000))
        if fade_out > 0:
            bgm = bgm.fade_out(int(fade_out * 1000))

        bgm.export(str(output_path), format="mp3", bitrate="192k")
        logger.info(f"BGM 处理完成: {output_path}")

        return str(output_path)

    except Exception as e:
        logger.error(f"BGM 处理失败: {e}")
        return ""


# ============================================================
# 混音
# ============================================================

def mix_audio(tts_segments: list[dict], bgm_file: str, config: dict,
              output_dir: str) -> str:
    """
    配音 + BGM 混音

    返回: 混音后的音频文件路径
    """
    mix_cfg = config.get("audio", {}).get("mix", {})
    sample_rate = mix_cfg.get("sample_rate", 44100)
    channels = mix_cfg.get("channels", 2)

    output_path = Path(output_dir) / "mix_final.wav"

    logger.info("开始混音...")

    # 1. 合并所有 TTS 分段为完整音轨
    tts_dir = Path(output_dir) / "audio"
    tts_audio_dir = Path(output_dir) / "audio"
    # 修正路径：TTS 文件在 {working}/audio/ 下
    tts_audio_dir = Path(output_dir) / "audio"

    combined_tts = AudioSegment.silent(duration=0)

    for seg in tts_segments:
        seg_path = tts_audio_dir / Path(seg["file"]).name
        if not seg_path.exists():
            logger.warning(f"TTS 分段不存在: {seg_path}")
            continue

        # 加载当前段落
        seg_audio = AudioSegment.from_file(str(seg_path))

        # 对齐到时间线位置
        silence_before = int(seg["start"] * 1000) - len(combined_tts)
        if silence_before > 0:
            combined_tts += AudioSegment.silent(duration=silence_before)
        elif silence_before < 0:
            # 重叠时直接叠加
            combined_tts = combined_tts.overlay(seg_audio,
                                                position=int(seg["start"] * 1000))
            continue

        combined_tts += seg_audio

    # 2. 如果有 BGM，混入背景音乐
    if bgm_file and os.path.exists(bgm_file):
        bgm = AudioSegment.from_file(bgm_file)
        # BGM 长度与配音匹配
        bgm = bgm[:len(combined_tts)]

        # 混音：配音 100% + BGM 按比例
        final = combined_tts.overlay(bgm)
    else:
        final = combined_tts

    # 3. 设置输出参数
    final = final.set_frame_rate(sample_rate).set_channels(channels)

    # 4. 导出
    final.export(str(output_path), format="wav")
    logger.info(f"混音完成: {output_path} ({len(final)/1000:.1f}s)")

    return str(output_path)


# ============================================================
# 阶段主入口
# ============================================================

def process(project_dir: str, material_index: dict | None = None) -> dict:
    """
    阶段主入口：执行完整的音频处理流程

    返回: 音频处理结果信息
        {
            "tts_segments": [...],
            "total_duration": float,
            "bgm_file": str,
            "mix_file": str,
        }
    """
    logger.info("=" * 40)
    logger.info("阶段2: 音频处理")
    logger.info("=" * 40)

    # 加载配置
    import yaml
    config_path = Path(__file__).parent.parent / "config" / "pipeline.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 加载素材索引
    if material_index is None:
        index_path = Path(project_dir) / "working" / "material_index.json"
        if index_path.exists():
            with open(index_path, "r", encoding="utf-8") as f:
                material_index = json.load(f)
        else:
            logger.error("素材索引不存在，请先运行 s01")
            return {}

    working_dir = Path(project_dir) / "working"

    # 1. 获取剧本
    scripts = material_index.get("materials", {}).get("scripts", [])
    if not scripts:
        logger.error("未找到剧本文件")
        return {}

    text_lines = scripts[0].get("lines", [])
    if not text_lines:
        logger.error("剧本为空")
        return {}

    logger.info(f"剧本: {scripts[0]['name']} ({len(text_lines)} 行)")

    # 2. TTS 配音
    tts_segments = generate_tts(text_lines, config, str(working_dir))
    total_duration = sum(s["duration"] for s in tts_segments)

    # 3. BGM 处理
    bgm_list = material_index.get("materials", {}).get("bgm", [])
    bgm_file = ""
    if bgm_list:
        input_dir = Path(project_dir) / "input"
        bgm_file = str(input_dir / bgm_list[0]["file"])

    processed_bgm = process_bgm(bgm_file, total_duration, config,
                                str(working_dir))

    # 4. 混音
    mix_file = mix_audio(tts_segments, processed_bgm, config, str(working_dir))

    result = {
        "tts_segments": tts_segments,
        "total_duration": total_duration,
        "bgm_file": processed_bgm,
        "mix_file": mix_file,
    }

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                       format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    import sys
    project = sys.argv[1] if len(sys.argv) > 1 else "demo"
    process(f"projects/{project}")
