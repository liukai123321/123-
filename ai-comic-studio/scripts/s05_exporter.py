"""
s05 — 成片导出模块
===================
功能：
1. 抖音格式转码（1080×1920, H.264, 8Mbps）
2. 提取视频封面
3. 批量导出多版本
"""

import os
import subprocess
import logging
from pathlib import Path

from scripts.utils import get_ffmpeg_path

logger = logging.getLogger("pipeline.export")


# ============================================================
# 参数校验与构建
# ============================================================

def _build_encoder_params(config: dict) -> list[str]:
    """
    根据配置构建 ffmpeg 编码参数

    抖音推荐参数：
    - 分辨率: 1080×1920 (9:16 竖屏)
    - 编码: H.264
    - 帧率: 24/30 fps
    - 码率: 8-12 Mbps
    - 音频: AAC, 192kbps, 44100Hz
    - 关键帧间隔: 2s (GOP = fps * 2)
    - 色彩空间: yuv420p
    """
    out_cfg = config.get("output", {})
    proj_cfg = config.get("project", {})

    fps = proj_cfg.get("fps", 24)
    bitrate = out_cfg.get("bitrate", "8M")
    audio_bitrate = out_cfg.get("audio_bitrate", "192k")

    params = [
        "-c:v", "libx264",
        "-preset", "medium",
        "-b:v", bitrate,
        "-maxrate", f"{int(bitrate[:-1]) * 1.2}M" if bitrate.endswith("M") else bitrate,
        "-bufsize", f"{int(bitrate[:-1]) * 2}M" if bitrate.endswith("M") else bitrate,
        "-r", str(fps),
        "-g", str(fps * 2),  # 关键帧间隔 2s
        "-keyint_min", str(fps),
        "-pix_fmt", "yuv420p",
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-movflags", "+faststart",  # 支持流式播放
        # 音频
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-ar", "44100",
        "-ac", "2",
    ]

    return params


# ============================================================
# 单视频导出
# ============================================================

def export_video(input_video: str, output_path: str,
                 config: dict) -> bool:
    """
    单视频导出为抖音格式

    参数:
        input_video: 输入视频路径（draft 阶段的输出）
        output_path: 输出视频路径（release 目录）
        config: 配置字典
    """
    resolution = tuple(config.get("output", {}).get("resolution", [1080, 1920]))
    resolution_str = f"{resolution[0]}:{resolution[1]}"

    logger.info(f"导出视频: {input_video} -> {output_path}")

    cmd = [
        get_ffmpeg_path(), "-y",
        "-i", input_video,
        "-vf", f"scale={resolution_str}:force_original_aspect_ratio=decrease,"
               f"pad={resolution_str}:(ow-iw)/2:(oh-ih)/2",
        *_build_encoder_params(config),
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            logger.error(f"导出失败: {result.stderr[:300]}")
            return False
        logger.info(f"导出完成: {output_path}")
        return True
    except subprocess.TimeoutExpired:
        logger.error("导出超时")
        return False
    except FileNotFoundError:
        logger.error("ffmpeg 未安装")
        return False
    except Exception as e:
        logger.error(f"导出出错: {e}")
        return False


# ============================================================
# 提取封面
# ============================================================

def extract_cover(video_path: str, output_image: str) -> bool:
    """
    提取视频第一帧作为封面

    抖音上传需要封面图，默认取第一帧
    """
    cmd = [
        get_ffmpeg_path(), "-y",
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        output_image,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            logger.info(f"封面已提取: {output_image}")
            return True
        else:
            logger.error(f"封面提取失败: {result.stderr[:200]}")
            return False
    except Exception as e:
        logger.error(f"封面提取出错: {e}")
        return False


# ============================================================
# 批量导出
# ============================================================

def export_batch(project_dir: str, config: dict) -> list[str]:
    """
    批量导出项目下所有草稿视频

    返回导出的文件路径列表
    """
    draft_dir = Path(project_dir) / "output" / "draft"
    release_dir = Path(project_dir) / "output" / "release"
    release_dir.mkdir(parents=True, exist_ok=True)

    exported = []

    # 查找所有草稿视频
    for video_file in sorted(draft_dir.glob("*.mp4")):
        output_name = video_file.stem.replace("_draft", "_final")
        output_path = str(release_dir / f"{output_name}.mp4")

        success = export_video(str(video_file), output_path, config)
        if success:
            exported.append(output_path)

            # 提取封面
            cover_path = str(release_dir / f"{output_name}_cover.jpg")
            extract_cover(output_path, cover_path)

    if not exported:
        logger.warning("没有找到草稿视频（检查 output/draft/ 目录）")

    return exported


# ============================================================
# 阶段主入口
# ============================================================

def process(project_dir: str,
            assembled_video: str | None = None) -> list[str]:
    """
    阶段主入口：成片导出

    参数:
        project_dir: 项目目录
        assembled_video: s04 输出的合成视频路径（可选）

    返回: 导出文件路径列表
    """
    logger.info("=" * 40)
    logger.info("阶段5: 成片导出")
    logger.info("=" * 40)

    # 加载配置
    import yaml
    config_path = Path(__file__).parent.parent / "config" / "pipeline.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    release_dir = Path(project_dir) / "output" / "release"
    release_dir.mkdir(parents=True, exist_ok=True)

    exported = []

    if assembled_video and os.path.exists(assembled_video):
        # 单个视频导出
        output_name = Path(assembled_video).stem.replace("_draft", "_final")
        output_path = str(release_dir / f"{output_name}.mp4")

        success = export_video(assembled_video, output_path, config)
        if success:
            exported.append(output_path)
            # 提取封面
            cover_path = str(release_dir / f"{output_name}_cover.jpg")
            extract_cover(output_path, cover_path)
    else:
        # 批量导出草稿目录
        exported = export_batch(str(project_dir), config)

    if exported:
        logger.info(f"阶段5 完成: {'; '.join(exported)}")
    else:
        logger.warning("阶段5: 无文件导出")

    return exported


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                       format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    import sys
    project = sys.argv[1] if len(sys.argv) > 1 else "demo"
    process(f"projects/{project}")
