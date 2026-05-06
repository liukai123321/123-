#!/usr/bin/env python3
"""
AI漫剧音乐剪辑流水线 — 主控脚本
==================================
全自动视频剪辑流水线，从素材到抖音成片一键完成。

用法:
    # 全自动运行（s01 → s02 → s03 → s04 → s05）
    python scripts/main.py --project demo

    # 指定运行阶段
    python scripts/main.py --project demo --stage audio subtitle

    # 使用自定义配置
    python scripts/main.py --project demo --config my_config.yaml

    # 仅检查素材
    python scripts/main.py --project demo --stage material --dry-run

    # 覆盖单个配置参数
    python scripts/main.py --project demo --param audio.tts.voice=zh-CN-YunxiNeural
"""

import os
import sys
import argparse
import logging
from pathlib import Path

# 加入项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def setup_logging(config: dict, log_file: str = None):
    """配置日志"""
    log_cfg = config.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)

    handlers = [logging.StreamHandler()]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def load_config(config_path: str, project: str, params: list[str] = None) -> dict:
    """
    加载配置（三层覆盖：全局 → 项目级 → 命令行参数）
    """
    import yaml

    # 1. 全局默认配置
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 2. 项目级配置覆盖
    project_config_path = Path(config_path).parent.parent / "projects" / project / "pipeline.yaml"
    if project_config_path.exists():
        with open(project_config_path, "r", encoding="utf-8") as f:
            project_config = yaml.safe_load(f)
        _deep_merge(config, project_config)
        logging.getLogger("pipeline").info(f"已加载项目配置: {project_config_path}")

    # 3. 命令行参数覆盖
    if params:
        for param in params:
            if "=" not in param:
                continue
            key, value = param.split("=", 1)
            _set_nested(config, key.split("."), value)

    return config


def _deep_merge(base: dict, override: dict):
    """递归合并两个字典"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _set_nested(config: dict, keys: list[str], value: str):
    """用点号路径设置嵌套值，如 audio.tts.voice = xxx"""
    current = config
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    # 尝试转换类型
    current[keys[-1]] = _auto_cast(value)


def _auto_cast(value: str):
    """自动转换字符串为合适类型"""
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.lower() == "none":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def resolve_project_dir(project_name: str, base_dir: str = None) -> str:
    """获取项目目录路径"""
    if base_dir is None:
        base_dir = str(PROJECT_ROOT / "projects")
    project_dir = os.path.join(base_dir, project_name)

    if not os.path.exists(project_dir):
        logging.getLogger("pipeline").warning(
            f"项目目录不存在，正在创建: {project_dir}")
        os.makedirs(os.path.join(project_dir, "input", "images"), exist_ok=True)
        os.makedirs(os.path.join(project_dir, "input", "videos"), exist_ok=True)
        os.makedirs(os.path.join(project_dir, "input", "bgm"), exist_ok=True)
        os.makedirs(os.path.join(project_dir, "input", "script"), exist_ok=True)
        os.makedirs(os.path.join(project_dir, "working", "audio"), exist_ok=True)
        os.makedirs(os.path.join(project_dir, "working", "subtitles"), exist_ok=True)
        os.makedirs(os.path.join(project_dir, "working", "segments"), exist_ok=True)
        os.makedirs(os.path.join(project_dir, "output", "draft"), exist_ok=True)
        os.makedirs(os.path.join(project_dir, "output", "release"), exist_ok=True)

    return project_dir


def main():
    parser = argparse.ArgumentParser(
        description="AI漫剧音乐剪辑流水线 — 全自动抖音视频生成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/main.py --project demo
  python scripts/main.py --project demo --stage audio subtitle
  python scripts/main.py --project demo --stage material --dry-run
  python scripts/main.py --project demo --param audio.tts.voice=zh-CN-YunxiNeural
        """,
    )

    parser.add_argument("--project", "-p", default="demo",
                       help="项目名，对应 projects/<name>/ 目录 (默认: demo)")
    parser.add_argument("--config", "-c", default=None,
                       help="配置文件路径 (默认: config/pipeline.yaml)")
    parser.add_argument("--stage", "-s", nargs="+",
                       choices=["material", "audio", "subtitle", "assemble", "export", "all"],
                       help="指定运行阶段 (默认: all, 全流程)")
    parser.add_argument("--dry-run", action="store_true",
                       help="仅检查素材，不执行实际处理")
    parser.add_argument("--param", nargs="*", default=[],
                       help="覆盖配置参数，格式: key=value (如 audio.tts.voice=xxx)")

    args = parser.parse_args()

    # 加载配置
    config_path = args.config or str(PROJECT_ROOT / "config" / "pipeline.yaml")
    config = load_config(config_path, args.project, args.param)

    # 设置日志
    log_file = str(PROJECT_ROOT / config.get("logging", {}).get("file", "logs/pipeline.log"))
    setup_logging(config, log_file)

    logger = logging.getLogger("pipeline.main")
    logger.info("=" * 50)
    logger.info(f"AI漫剧音乐剪辑流水线 启动")
    logger.info(f"项目: {args.project}")
    logger.info(f"配置: {config_path}")
    logger.info(f"阶段: {args.stage or 'all'}")
    logger.info("=" * 50)

    # 解析项目目录
    project_dir = resolve_project_dir(args.project)

    # 判断运行阶段
    if args.stage and "all" not in args.stage:
        stages = args.stage
    else:
        stages = ["material", "audio", "subtitle", "assemble", "export"]

    logger.info(f"运行阶段顺序: {' → '.join(stages)}")

    # 跨阶段数据传递
    audio_result = None
    subtitle_file = None
    assembled_video = None

    # 阶段映射
    stage_modules = {
        "material": "s01_material_manager",
        "audio": "s02_audio_processor",
        "subtitle": "s03_subtitle_generator",
        "assemble": "s04_video_assembler",
        "export": "s05_exporter",
    }

    # 逐个执行阶段
    for stage_name in stages:
        logger.info(f"")
        logger.info(f"▶ 执行阶段: {stage_name}")

        module_name = stage_modules.get(stage_name)
        if not module_name:
            logger.warning(f"未知阶段: {stage_name}")
            continue

        try:
            module = __import__(f"scripts.{module_name}", fromlist=["process"])
            process_func = getattr(module, "process")

            # 根据阶段传递不同参数
            if stage_name == "material":
                result = process_func(project_dir, dry_run=args.dry_run)
            elif stage_name == "audio":
                result = process_func(project_dir)
                audio_result = result
            elif stage_name == "subtitle":
                result = process_func(project_dir, audio_result)
                subtitle_file = result
            elif stage_name == "assemble":
                result = process_func(project_dir, audio_result, subtitle_file)
                assembled_video = result
            elif stage_name == "export":
                result = process_func(project_dir, assembled_video)
            else:
                result = process_func(project_dir)

            logger.info(f"✔ 阶段 {stage_name} 执行完成")

        except Exception as e:
            logger.error(f"✘ 阶段 {stage_name} 执行失败: {e}", exc_info=True)
            logger.warning("流水线终止")
            sys.exit(1)

    logger.info("")
    logger.info("=" * 50)
    logger.info("流水线全部完成！")
    logger.info("=" * 50)

    # 显示产出
    release_dir = Path(project_dir) / "output" / "release"
    if release_dir.exists():
        files = list(release_dir.glob("*"))
        if files:
            logger.info("产出文件:")
            for f in files:
                size_mb = f.stat().st_size / (1024 * 1024)
                logger.info(f"  📁 {f.name} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
