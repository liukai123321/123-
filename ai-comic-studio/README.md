# AI漫剧音乐剪辑流水线

面向 **AI漫剧 + 音乐方向** 抖音信息流剪辑师的全自动视频剪辑工具。

从素材到抖音成片，一键运行，无需打开剪辑软件。

## 功能

| 阶段 | 功能 | 技术 |
|------|------|------|
| 素材管理 | 自动扫描、分类、验证素材 | Python + ffprobe |
| 音频处理 | TTS 配音 + BGM 混音 | edge-tts + pydub |
| 字幕生成 | 智能字幕 + 抖音风格 ASS 格式 | faster-whisper / edge-tts 时间戳 |
| 视频组装 | Ken Burns 动画 + 转场 + 字幕叠加 | moviepy + ffmpeg |
| 成片导出 | 抖音格式转码 + 封面提取 | ffmpeg |

## 快速开始

### 1. 安装

```bash
# 安装 ffmpeg（必须）
# Windows: winget install ffmpeg
# macOS:   brew install ffmpeg
# Linux:   sudo apt install ffmpeg

# 安装 Python 依赖
pip install -r requirements.txt
```

或一键安装：

```bash
bash install_deps.sh
```

### 2. 准备素材

```
projects/你的项目名/input/
├── images/          # 漫画图片（01.png, 02.png...）
├── bgm/             # 背景音乐（单个 mp3/wav）
└── script/
    └── narration.txt  # 配音剧本
```

**剧本格式**：每行一句，`#` 开头的行会被忽略。

### 3. 运行

```bash
# 全自动流程
python scripts/main.py --project 你的项目名

# 分步运行
python scripts/main.py --project demo --stage material
python scripts/main.py --project demo --stage audio
python scripts/main.py --project demo --stage subtitle
python scripts/main.py --project demo --stage assemble
python scripts/main.py --project demo --stage export

# 覆盖参数（如换配音音色）
python scripts/main.py --project demo --param audio.tts.voice=zh-CN-YunxiNeural
```

### 4. 查看产出

```
projects/你的项目名/output/release/
├── 项目名_final.mp4     # 抖音格式成片
└── 项目名_final_cover.jpg  # 视频封面
```

## 配置说明

编辑 `config/pipeline.yaml` 即可调整所有参数，无需修改代码。

常用配置：

```yaml
audio:
  tts:
    voice: "zh-CN-XiaoxiaoNeural"  # 配音音色
  bgm:
    volume: 0.3                     # BGM 音量

subtitle:
  style:
    font_size: 30                   # 字号
    outline_width: 3                # 描边宽度

video:
  ken_burns:
    zoom_max: 1.15                  # 图片缩放幅度
```

## 所用技术

| 工具 | 用途 | 费用 |
|------|------|------|
| [edge-tts](https://github.com/rany2/edge-tts) | 微软 AI 配音 | 免费 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | 语音转文字 | 免费 |
| [ffmpeg](https://ffmpeg.org/) | 视频/音频编码 | 免费 |
| [moviepy](https://zulko.github.io/moviepy/) | Python 视频编排 | 免费 |
