"""
s01 — 素材管理模块
===================
功能：扫描项目输入目录，按类型分类素材，建立索引 JSON
提供素材清单给后续阶段使用
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from PIL import Image

from scripts.utils import get_media_duration

logger = logging.getLogger("pipeline.material")


def discover_materials(project_dir: str) -> dict:
    """
    扫描项目 input/ 目录下的所有素材，返回分类清单

    返回格式:
    {
        "project": <项目名>,
        "timestamp": <扫描时间>,
        "materials": {
            "images": [{"file": ..., "width": ..., "height": ..., "valid": bool}, ...],
            "videos": [{"file": ..., "duration": ..., "valid": bool}, ...],
            "bgm":    [{"file": ..., "duration": ..., "valid": bool}, ...],
            "scripts": [{"file": ..., "lines": [...]}, ...]
        }
    }
    """
    input_dir = Path(project_dir) / "input"

    # 确保各子目录存在
    for sub in ["images", "videos", "bgm", "script"]:
        (input_dir / sub).mkdir(parents=True, exist_ok=True)

    materials = {
        "images":  _scan_images(input_dir / "images"),
        "videos":  _scan_videos(input_dir / "videos"),
        "bgm":     _scan_audio(input_dir / "bgm"),
        "scripts": _scan_scripts(input_dir / "script"),
    }

    index = {
        "project": Path(project_dir).name,
        "timestamp": datetime.now().isoformat(),
        "materials": materials,
    }

    # 写入工作目录
    working_dir = Path(project_dir) / "working"
    working_dir.mkdir(parents=True, exist_ok=True)
    index_path = working_dir / "material_index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    logger.info(f"素材扫描完成: 图片={len(materials['images'])}, "
                f"视频={len(materials['videos'])}, "
                f"BGM={len(materials['bgm'])}, "
                f"剧本={len(materials['scripts'])}")
    logger.info(f"素材索引已保存: {index_path}")

    return index


def _scan_images(image_dir: Path) -> list[dict]:
    """扫描图片目录，支持 jpg/png/webp/bmp"""
    results = []
    exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    for f in sorted(image_dir.iterdir()):
        if f.suffix.lower() in exts and f.is_file():
            info = {"file": str(f.relative_to(image_dir.parent.parent)),
                    "name": f.name, "valid": False, "width": 0, "height": 0}
            try:
                with Image.open(f) as img:
                    info["width"], info["height"] = img.size
                    info["valid"] = True
            except Exception as e:
                logger.warning(f"图片无效: {f.name} - {e}")
            results.append(info)
    return results


def _scan_videos(video_dir: Path) -> list[dict]:
    """扫描视频目录，用 ffprobe 验证"""
    results = []
    exts = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    for f in sorted(video_dir.iterdir()):
        if f.suffix.lower() in exts and f.is_file():
            info = {"file": str(f.relative_to(video_dir.parent.parent)),
                    "name": f.name, "valid": True, "duration": 0.0}
            # 用 ffprobe 获取时长
            duration = get_media_duration(str(f))
            if duration > 0:
                info["duration"] = round(duration, 2)
                info["valid"] = True
            else:
                logger.warning(f"视频无效: {f.name}")
                info["valid"] = False
            results.append(info)
    return results


def _scan_audio(audio_dir: Path) -> list[dict]:
    """扫描音频目录"""
    results = []
    exts = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"}
    for f in sorted(audio_dir.iterdir()):
        if f.suffix.lower() in exts and f.is_file():
            info = {"file": str(f.relative_to(audio_dir.parent.parent)),
                    "name": f.name, "valid": True, "duration": 0.0}
            duration = get_media_duration(str(f))
            if duration > 0:
                info["duration"] = round(duration, 2)
            else:
                logger.warning(f"音频无效: {f.name}")
                info["valid"] = False
            results.append(info)
    return results


def _scan_scripts(script_dir: Path) -> list[dict]:
    """扫描剧本文件 (.txt)"""
    results = []
    for f in sorted(script_dir.iterdir()):
        if f.suffix.lower() == ".txt" and f.is_file():
            lines = []
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        lines.append(line)
            results.append({
                "file": str(f.relative_to(script_dir.parent.parent)),
                "name": f.name,
                "lines": lines,
                "line_count": len(lines),
            })
    return results


def process(project_dir: str, dry_run: bool = False) -> dict:
    """
    阶段主入口
    返回素材索引字典
    """
    logger.info("=" * 40)
    logger.info("阶段1: 素材管理")
    logger.info("=" * 40)

    if dry_run:
        logger.info("[DRY RUN] 模拟扫描...")
        return {}

    index = discover_materials(project_dir)
    return index


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                       format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    # 测试运行
    import sys
    project = sys.argv[1] if len(sys.argv) > 1 else "demo"
    process(f"projects/{project}")
