"""
工具模块
=========
提供 ffmpeg 路径、文件操作等通用功能
"""

import os
import subprocess
from pathlib import Path


def get_ffmpeg_path() -> str:
    """
    获取 ffmpeg 可执行文件路径
    优先使用 imageio_ffmpeg 内置的 ffmpeg，其次查找系统 PATH
    """
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.exists(ffmpeg_path):
            return ffmpeg_path
    except (ImportError, RuntimeError):
        pass

    # 查找系统 PATH
    which_cmd = "where" if os.name == "nt" else "which"
    try:
        result = subprocess.run(
            [which_cmd, "ffmpeg"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip().split("\n")[0]
    except Exception:
        pass

    return "ffmpeg"  # 最后兜底


def get_ffprobe_path() -> str:
    """获取 ffprobe 路径"""
    ffmpeg_path = get_ffmpeg_path()
    if ffmpeg_path and ffmpeg_path != "ffmpeg":
        # 同一目录下的 ffprobe
        ffprobe = str(Path(ffmpeg_path).parent / "ffprobe")
        if os.name == "nt":
            ffprobe += ".exe"
        if os.path.exists(ffprobe):
            return ffprobe
    return "ffprobe"


def get_media_duration(filepath: str) -> float:
    """获取音视频文件时长（秒）"""
    ffprobe = get_ffprobe_path()
    try:
        cmd = [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            filepath
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return 0.0
