"""
s04 — 视频组装模块
===================
功能：
1. 根据素材和TTS时间戳构建时间线
2. 对图片应用 Ken Burns 动画效果
3. 拼接片段 + 转场
4. 叠加 ASS 字幕
5. 混入配音 + BGM
6. 输出合成视频
"""

import os
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

from scripts.utils import get_ffmpeg_path

logger = logging.getLogger("pipeline.assemble")


# ============================================================
# 时间线构建
# ============================================================

def build_timeline(material_index: dict, tts_segments: list[dict],
                   config: dict) -> list[dict]:
    """
    构建时间线

    算法：将图片按 TTS 段落等分分配，使画面与配音内容对齐

    返回时间线片段列表:
    {
        "type": "image" | "video",
        "source": "images/01.png",
        "start": 0.0,          # 时间线起始时间
        "end": 4.0,            # 时间线结束时间
        "duration": 4.0,
        "transition": "fade"   # 转场类型
    }
    """
    materials = material_index.get("materials", {})
    images = materials.get("images", [])
    videos = materials.get("videos", [])
    total_duration = tts_segments[-1]["end"] if tts_segments else 0

    timeline = []
    video_cfg = config.get("video", {})
    default_transition = video_cfg.get("transition", {}).get("default", "fade")
    trans_duration = video_cfg.get("transition", {}).get("duration", 0.5)
    image_duration = video_cfg.get("image_duration", 4.0)

    if not images and not videos:
        logger.error("没有图片或视频素材")
        return []

    # 优先处理视频片段
    current_time = 0.0

    # 按 TTS 段落分配图片
    if images:
        # 策略：将总时长按图片数量等分
        # 如果 TTS 有分段，尽量对齐
        num_images = len(images)
        tts_count = len(tts_segments)

        for i, img in enumerate(images):
            # 计算当前图片的起止时间
            if tts_count > 0:
                # 按 TTS 段落数等分
                seg_start = int(i * tts_count / num_images)
                seg_end = int((i + 1) * tts_count / num_images)
                if seg_end > tts_count:
                    seg_end = tts_count
                if seg_start >= tts_count:
                    seg_start = tts_count - 1
                    seg_end = tts_count

                start_time = tts_segments[seg_start]["start"] if seg_start < tts_count else current_time
                end_time = tts_segments[seg_end - 1]["end"] if seg_end > 0 else total_duration
                duration = end_time - start_time
            else:
                start_time = current_time
                duration = image_duration
                end_time = start_time + duration

            if duration <= 0:
                duration = image_duration
                end_time = start_time + duration

            timeline.append({
                "type": "image",
                "source": img["file"],
                "start": round(start_time, 3),
                "end": round(end_time, 3),
                "duration": round(duration, 3),
                "transition": default_transition,
                "transition_duration": trans_duration,
            })
            current_time = end_time

    # 添加视频片段
    for v in videos:
        timeline.append({
            "type": "video",
            "source": v["file"],
            "start": round(current_time, 3),
            "end": round(current_time + v.get("duration", 5), 3),
            "duration": v.get("duration", 5),
            "transition": default_transition,
            "transition_duration": trans_duration,
        })
        current_time += v.get("duration", 5)

    logger.info(f"时间线构建完成: {len(timeline)} 片段, 总时长 {current_time:.1f}s")
    return timeline


# ============================================================
# Ken Burns 效果（ffmpeg 实现）
# ============================================================

def _render_ken_burns(image_path: str, duration: float,
                      resolution: tuple[int, int],
                      output_path: str, config: dict) -> bool:
    """
    使用 ffmpeg zoompan 滤镜实现 Ken Burns 动态效果

    效果：图片在播放过程中缓慢放大 + 微小平移
    """
    kb_cfg = config.get("video", {}).get("ken_burns", {})
    zoom_max = kb_cfg.get("zoom_max", 1.15)
    pan_enabled = kb_cfg.get("pan", True)

    w, h = resolution
    fps = config.get("project", {}).get("fps", 24)
    frame_count = int(duration * fps)

    # zoompan 滤镜
    # z: 从 1.0 线性变化到 zoom_max
    # x/y: 保持居中或微平移
    zoom_step = (zoom_max - 1.0) / frame_count

    if pan_enabled:
        # 带缓动的缩放
        filter_str = (
            f"zoompan=z='if(lte(zoom,1.0),1.0,min(zoom+{zoom_step:.5f},{zoom_max}))':"
            f"d={frame_count}:"
            f"x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':"
            f"s={w}x{h}"
        )
    else:
        # 仅缩放，不移动
        filter_str = (
            f"zoompan=z='if(lte(zoom,1.0),1.0,min(zoom+{zoom_step:.5f},{zoom_max}))':"
            f"d={frame_count}:"
            f"s={w}x{h}"
        )

    cmd = [
        get_ffmpeg_path(), "-y",
        "-i", image_path,
        "-filter_complex", filter_str,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-t", str(duration),
        "-an",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error(f"Ken Burns 渲染失败: {result.stderr[:200]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("Ken Burns 渲染超时")
        return False
    except FileNotFoundError:
        logger.error("ffmpeg 未安装，请先安装 ffmpeg")
        return False


# ============================================================
# 视频合成
# ============================================================

def assemble_video(timeline: list[dict], audio_file: str,
                   subtitle_file: str, output_path: str,
                   config: dict, project_dir: str) -> bool:
    """
    合成最终视频

    流程：
    1. 逐个渲染时间线片段为独立视频文件
    2. 用 concat 协议拼接所有片段（含转场）
    3. 叠加字幕（ASS 滤镜）
    4. 混入音频
    """
    fps = config.get("project", {}).get("fps", 24)
    resolution = tuple(config.get("output", {}).get("resolution", [1080, 1920]))
    input_dir = Path(project_dir) / "input"
    segments_dir = Path(project_dir) / "working" / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"开始渲染视频 ({resolution[0]}x{resolution[1]}, {fps}fps)")

    # 1. 渲染每个片段
    segment_files = []
    for i, seg in enumerate(timeline):
        seg_output = str(segments_dir / f"seg_{i:04d}.mp4")
        success = False

        if seg["type"] == "image":
            img_path = str(input_dir / seg["source"])
            if os.path.exists(img_path):
                success = _render_ken_burns(
                    img_path, seg["duration"], resolution,
                    seg_output, config
                )
        elif seg["type"] == "video":
            # 视频片段：直接裁剪到目标分辨率
            vid_path = str(input_dir / seg["source"])
            if os.path.exists(vid_path):
                success = _render_video_segment(
                    vid_path, seg["duration"], resolution,
                    seg_output, fps
                )

        if success:
            segment_files.append(seg_output)
            logger.info(f"  片段 {i + 1}/{len(timeline)}: {seg['source']} -> OK")
        else:
            logger.warning(f"  片段 {i + 1}/{len(timeline)}: {seg['source']} -> 失败，跳过")

    if not segment_files:
        logger.error("没有成功渲染的片段")
        return False

    # 2. 拼接所有片段（含转场）
    logger.info("拼接所有片段...")
    concat_file = str(segments_dir.parent / "concat_list.txt")

    # 写入 concat demuxer 列表
    with open(concat_file, "w", encoding="utf-8") as f:
        for sf in segment_files:
            # 使用相对路径或转义路径
            f.write(f"file '{Path(sf).as_posix()}'\n")

    temp_concat = str(segments_dir.parent / "concat_temp.mp4")
    concat_cmd = [
        get_ffmpeg_path(), "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_file,
        "-c", "copy",
        temp_concat,
    ]

    try:
        result = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error(f"拼接失败: {result.stderr[:200]}")
            return False
    except Exception as e:
        logger.error(f"拼接出错: {e}")
        return False

    # 3. 叠加字幕 + 混入音频
    logger.info("叠加字幕和音频...")
    final_output = output_path

    ffmpeg_cmd = [
        get_ffmpeg_path(), "-y",
        "-i", temp_concat,
    ]

    # 音频输入（如果有）
    if audio_file and os.path.exists(audio_file):
        ffmpeg_cmd.extend(["-i", audio_file])
        audio_map = "-map 1:a"
    else:
        audio_map = "-an"

    # 字幕滤镜
    filter_parts = []
    if subtitle_file and os.path.exists(subtitle_file):
        # ASS 字幕叠加
        ass_path = Path(subtitle_file).as_posix()
        filter_parts.append(f"ass='{ass_path}'")

    if filter_parts:
        vf = ",".join(filter_parts)
        ffmpeg_cmd.extend(["-vf", vf])

    # 输出参数
    resolution_str = f"{resolution[0]}:{resolution[1]}"
    out_cfg = config.get("output", {})
    ffmpeg_cmd.extend([
        "-c:v", "libx264",
        "-preset", "medium",
        "-b:v", out_cfg.get("bitrate", "8M"),
        "-r", str(fps),
        "-pix_fmt", "yuv420p",
        "-s", resolution_str,
    ])

    if audio_file and os.path.exists(audio_file):
        ffmpeg_cmd.extend([
            "-c:a", "aac",
            "-b:a", out_cfg.get("audio_bitrate", "192k"),
            "-ar", "44100",
            "-ac", "2",
        ])
        # 确保音视频同步
        ffmpeg_cmd.extend(["-shortest"])

    ffmpeg_cmd.append(final_output)

    try:
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            logger.error(f"最终合成失败: {result.stderr[:300]}")
            return False
        logger.info(f"视频合成完成: {final_output}")
        return True
    except subprocess.TimeoutExpired:
        logger.error("视频合成超时")
        return False
    except Exception as e:
        logger.error(f"视频合成出错: {e}")
        return False


def _render_video_segment(video_path: str, duration: float,
                          resolution: tuple[int, int],
                          output_path: str, fps: int) -> bool:
    """
    渲染视频片段：裁剪分辨率 + 裁剪时长
    """
    cmd = [
        get_ffmpeg_path(), "-y",
        "-i", video_path,
        "-vf", f"scale={resolution[0]}:{resolution[1]}:force_original_aspect_ratio=decrease,"
               f"pad={resolution[0]}:{resolution[1]}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-t", str(duration),
        "-an",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return result.returncode == 0
    except Exception:
        return False


# ============================================================
# 阶段主入口
# ============================================================

def process(project_dir: str, audio_result: dict | None = None,
            subtitle_file: str | None = None) -> str:
    """
    阶段主入口：执行完整的视频组装流程

    返回: 合成视频文件路径，失败返回空字符串
    """
    logger.info("=" * 40)
    logger.info("阶段4: 视频组装")
    logger.info("=" * 40)

    # 加载配置
    import yaml
    config_path = Path(__file__).parent.parent / "config" / "pipeline.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    working_dir = Path(project_dir) / "working"
    input_dir = Path(project_dir) / "input"
    output_dir = Path(project_dir) / "output" / "draft"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 加载素材索引
    index_path = working_dir / "material_index.json"
    if not index_path.exists():
        logger.error("素材索引不存在，请先运行 s01")
        return ""

    with open(index_path, "r", encoding="utf-8") as f:
        material_index = json.load(f)

    # 2. 获取 TTS 分段信息
    if audio_result and "tts_segments" in audio_result:
        tts_segments = audio_result["tts_segments"]
    else:
        # 尝试从文件加载
        tts_info_path = working_dir / "audio" / "tts_info.json"
        if tts_info_path.exists():
            with open(tts_info_path, "r", encoding="utf-8") as f:
                tts_info = json.load(f)
            tts_segments = tts_info.get("segments", [])
        else:
            logger.error("TTS 分段信息不存在，请先运行 s02")
            return ""

    # 3. 构建时间线
    timeline = build_timeline(material_index, tts_segments, config)
    if not timeline:
        return ""

    # 4. 确定音频文件
    audio_file = ""
    if audio_result and "mix_file" in audio_result:
        audio_file = audio_result["mix_file"]
    else:
        mix_path = working_dir / "mix_final.wav"
        if mix_path.exists():
            audio_file = str(mix_path)

    # 5. 确定字幕文件
    if subtitle_file and os.path.exists(subtitle_file):
        sub_path = subtitle_file
    else:
        default_sub = working_dir / "subtitles" / "subtitle.ass"
        if default_sub.exists():
            sub_path = str(default_sub)
        else:
            sub_path = ""

    # 6. 合成视频
    output_path = str(output_dir / f"{Path(project_dir).name}_draft.mp4")
    success = assemble_video(timeline, audio_file, sub_path,
                             output_path, config, project_dir)

    if success:
        logger.info(f"阶段4 完成: {output_path}")
        return output_path
    else:
        logger.error("阶段4 失败")
        return ""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                       format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    import sys
    project = sys.argv[1] if len(sys.argv) > 1 else "demo"
    process(f"projects/{project}")
