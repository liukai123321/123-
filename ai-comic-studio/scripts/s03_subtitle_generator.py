"""
s03 — 字幕生成模块
===================
功能：
1. 从 edge-tts 时间戳直接生成字幕（推荐，无额外成本）
2. 若无时间戳，用 faster-whisper 进行语音识别
3. 生成 ASS 格式字幕（支持描边、阴影等抖音风格）
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional

import pysubs2

logger = logging.getLogger("pipeline.subtitle")


# ============================================================
# 从 edge-tts 时间戳生成字幕
# ============================================================

def _segments_to_ass_events(segments: list[dict],
                            max_line_width: int = 18,
                            max_lines: int = 2) -> list[pysubs2.SSAEvent]:
    """
    将 TTS 分段信息转换为 ASS 字幕事件

    策略：
    - 若段落文本超过 max_line_width 字，自动断行
    - 最多显示 max_lines 行
    """
    events = []

    for seg in segments:
        text = seg.get("text", "").strip()
        start = seg.get("start", 0)
        end = seg.get("end", 0)

        if not text or end <= start:
            continue

        # 自动断行
        if len(text) > max_line_width:
            # 在标点或空格处断行
            display_text = _auto_wrap(text, max_line_width, max_lines)
        else:
            display_text = text

        # 换行符替换为 ASS 换行符
        display_text = display_text.replace("\n", "\\N")

        event = pysubs2.SSAEvent(
            start=pysubs2.make_time(s=start),
            end=pysubs2.make_time(s=end),
            text=display_text,
        )
        events.append(event)

    return events


def _auto_wrap(text: str, max_width: int, max_lines: int) -> str:
    """
    自动断行：优先在标点处断行，否则在字数限制处断行
    """
    import re

    if len(text) <= max_width:
        return text

    lines = []
    remaining = text

    for _ in range(max_lines - 1):
        if len(remaining) <= max_width:
            lines.append(remaining)
            remaining = ""
            break

        # 在 max_width 范围内找最后一个标点
        segment = remaining[:max_width]
        # 标点位置（从右向左找）
        punct_pos = -1
        for i in range(len(segment) - 1, -1, -1):
            if segment[i] in "，。！？、；：,.!?;:":
                punct_pos = i
                break

        if punct_pos > len(segment) // 2:
            line = segment[:punct_pos + 1]
            lines.append(line)
            remaining = remaining[punct_pos + 1:]
        else:
            lines.append(segment)
            remaining = remaining[max_width:]

    if remaining:
        lines.append(remaining)

    return "\n".join(lines)


def _build_ass_style(config: dict) -> pysubs2.SSAStyle:
    """
    根据配置构建 ASS 字幕样式

    ASS 格式说明:
    - 字体名、字号、主色、次色、描边色、阴影色
    - 描边宽度、阴影深度
    - 对齐方式、边距
    """
    style_cfg = config.get("subtitle", {}).get("style", {})

    style = pysubs2.SSAStyle()
    style.fontname = style_cfg.get("font", "微软雅黑")
    style.fontsize = style_cfg.get("font_size", 30)
    style.primary_color = pysubs2.Color.from_ass(style_cfg.get("primary_color", "&H00FFFFFF"))
    style.secondary_color = pysubs2.Color.from_ass(style_cfg.get("secondary_color", "&H000000FF"))
    style.outline_color = pysubs2.Color.from_ass(style_cfg.get("outline_color", "&H00000000"))
    style.back_color = pysubs2.Color.from_ass("&H80000000")  # 半透明黑阴影
    style.outline = style_cfg.get("outline_width", 3)
    style.shadow = style_cfg.get("shadow_width", 1)
    style.margin_v = style_cfg.get("margin_v", 70)
    style.margin_l = 20
    style.margin_r = 20
    style.alignment = style_cfg.get("alignment", 2)  # 2=底部居中
    style.bold = False
    style.encoding = 1  # Default

    return style


def generate_from_tts_timestamps(tts_info_file: str, config: dict,
                                 output_dir: str) -> str:
    """
    从 edge-tts 时间戳信息直接生成字幕

    参数:
        tts_info_file: s02 输出的 tts_info.json 路径
        config: 配置字典
        output_dir: 字幕输出目录

    返回: ASS 字幕文件路径
    """
    with open(tts_info_file, "r", encoding="utf-8") as f:
        tts_info = json.load(f)

    segments = tts_info.get("segments", [])
    if not segments:
        logger.error("TTS 时间戳为空，无法生成字幕")
        return ""

    sub_cfg = config.get("subtitle", {})
    max_width = sub_cfg.get("max_line_width", 18)
    max_lines = sub_cfg.get("max_lines", 2)

    # 生成字幕事件
    events = _segments_to_ass_events(segments, max_width, max_lines)

    # 创建字幕文件
    subs = pysubs2.SSAFile()
    subs.styles["Default"] = _build_ass_style(config)
    subs.events = events

    # 设置脚本信息
    subs.info["Title"] = "AI漫剧字幕"
    subs.info["Original Script"] = "ai-comic-studio"
    subs.info["ScriptType"] = "v4.00+"

    # 导出
    subtitle_dir = Path(output_dir) / "subtitles"
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    output_path = subtitle_dir / "subtitle.ass"

    subs.save(str(output_path))
    logger.info(f"字幕生成完成: {output_path} ({len(events)} 条)")

    return str(output_path)


# ============================================================
# faster-whisper 语音识别（备用方案）
# ============================================================

def _transcribe_with_whisper(audio_file: str, config: dict) -> list[dict]:
    """
    用 faster-whisper 对音频进行语音识别

    当 use_tts_timestamps=False 或 TTS 时间戳不可用时使用
    """
    sub_cfg = config.get("subtitle", {})
    model_name = sub_cfg.get("model", "medium")
    device = sub_cfg.get("device", "auto")
    compute_type = sub_cfg.get("compute_type", "int8")
    language = sub_cfg.get("language", "zh")

    logger.info(f"加载 Whisper 模型: {model_name} (device={device}, compute={compute_type})")

    try:
        from faster_whisper import WhisperModel

        # 自动选择设备
        if device == "auto":
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"

        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        segments, info = model.transcribe(audio_file, language=language,
                                          beam_size=5, vad_filter=True)

        result = []
        for seg in segments:
            result.append({
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text.strip(),
            })

        logger.info(f"语音识别完成: {len(result)} 句")
        return result

    except ImportError:
        logger.error("faster-whisper 未安装，请运行: pip install faster-whisper")
        return []
    except Exception as e:
        logger.error(f"语音识别失败: {e}")
        return []


def generate_from_audio(audio_file: str, config: dict,
                        output_dir: str) -> str:
    """
    从音频文件用 Whisper 识别生成字幕（备用方案）
    """
    segments = _transcribe_with_whisper(audio_file, config)
    if not segments:
        return ""

    sub_cfg = config.get("subtitle", {})
    max_width = sub_cfg.get("max_line_width", 18)
    max_lines = sub_cfg.get("max_lines", 2)

    events = _segments_to_ass_events(segments, max_width, max_lines)

    subs = pysubs2.SSAFile()
    subs.styles["Default"] = _build_ass_style(config)
    subs.events = events
    subs.info["Title"] = "AI漫剧字幕（Whisper）"
    subs.info["ScriptType"] = "v4.00+"

    subtitle_dir = Path(output_dir) / "subtitles"
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    output_path = subtitle_dir / "subtitle.ass"

    subs.save(str(output_path))
    logger.info(f"字幕生成完成(Whisper): {output_path} ({len(events)} 条)")

    return str(output_path)


# ============================================================
# 阶段主入口
# ============================================================

def process(project_dir: str, audio_result: dict | None = None) -> str:
    """
    阶段主入口：生成字幕文件

    参数:
        project_dir: 项目目录
        audio_result: s02 的输出结果（含 tts_segments 信息）

    返回: ASS 字幕文件路径，失败返回空字符串
    """
    logger.info("=" * 40)
    logger.info("阶段3: 字幕生成")
    logger.info("=" * 40)

    # 加载配置
    import yaml
    config_path = Path(__file__).parent.parent / "config" / "pipeline.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    working_dir = Path(project_dir) / "working"
    sub_cfg = config.get("subtitle", {})
    use_tts = sub_cfg.get("use_tts_timestamps", True)

    # 优先使用 edge-tts 时间戳
    tts_info_file = working_dir / "audio" / "tts_info.json"
    if use_tts and tts_info_file.exists():
        logger.info("使用 edge-tts 时间戳生成字幕")
        return generate_from_tts_timestamps(
            str(tts_info_file), config, str(working_dir))

    # 后备方案：用 Whisper 识别
    mix_file = working_dir / "mix_final.wav"
    if mix_file.exists():
        logger.info("使用 Whisper 语音识别生成字幕")
        return generate_from_audio(str(mix_file), config, str(working_dir))

    logger.error("无可用的音频时间戳或语音文件")
    return ""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                       format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    import sys
    project = sys.argv[1] if len(sys.argv) > 1 else "demo"
    process(f"projects/{project}")
