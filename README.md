# Cushion Screen

把图片 / 视频映射到 Minecraft **cushion（坐垫）+ 光照方块** 显示屏。

- **Python**：CIEDE2000 配色、Bayer 抖动、时间轴采样、**脏像素（CIEDE ΔE）** 写入 `command_storage`
- **数据包**：全量首帧按行放置；后续帧只更新 dirty 列表
- **Web UI**：浏览器上传处理、进度 / ETA / 停止

面向较新的 Java 快照（`pack_format` 见 `datapacks/cushion_screen/pack.mcmeta`）。坐垫实体与颜色字段依赖对应版本。

## 功能概览

| 模块 | 说明 |
|------|------|
| `cushion_screen.py` | 核心：配色、视频采样、storage 写入、脏判定 |
| `bake_test_video_play.py` | 按分辨率烘焙 `place_*` + 视频 `play` 入口 |
| `web_app.py` + `web/` | 本地 Web 处理前端 |
| `datapacks/cushion_screen` | 播放 / 展示数据包 |

### Storage 结构（`cs:cache`）

```text
cache.<name>[0]  = { full:1b, rows:[ { light_block:{ "x": block }, cushion_color:{ "x": color } }, ... ] }
cache.<name>[t]  = { full:0b, d:[ { x, y, l, c }, ... ] }   # t>0 脏像素
```

图片只有 `[0]` 全量帧。视频第 0 帧全量，之后为相对**屏上显示状态**的 CIEDE2000 脏列表。

### 采样（非整除帧率）

按时间轴均匀取样，使：

```text
输出帧数 / 采样帧率 ≈ 原片时长
```

例如 30 fps 片源、`target_fps=20` 会得到约 `round(T×20)` 帧，并以 20 fps（`postpone 1t`）播放。

## 安装

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
```

依赖：`numpy`、`Pillow`、`nbtlib`、`opencv-python-headless`。

## 快速开始

### 1. 放入存档

将 `datapacks/cushion_screen` 复制到存档的 `datapacks/`。

处理脚本默认把 NBT 写到**当前工作目录**下：

```text
./data/cs/command_storage.dat
```

请在**存档根目录**运行工具，或把生成的 `data/cs/command_storage.dat` 拷进存档的 `data/cs/`。

处理前请**退出世界**，避免游戏占用 dat 导致写入失败。

### 2. 命令行处理

```bash
# 修改 cushion_screen.py 底部 __main__，或：
python -c "from pathlib import Path; from cushion_screen import process_media; process_media(Path('examples/test_video.mp4'), target_height=64, target_fps=20)"
```

常用参数（`process_media`）：

| 参数 | 含义 |
|------|------|
| `target_height` | 等比缩放高度（宽按片源比例） |
| `target_fps` | 采样 / 播放目标帧率 |
| `source_name` | storage 键名（默认文件名） |
| `dither` | Bayer 抖动 |
| `dirty_ciede2000_threshold` | 脏像素 CIEDE2000 阈值（仅视频）：`"auto"` / `float` / `0` 严格相等；`None` 用模块默认 |

模块全局默认：`DIRTY_CIEDE2000_THRESHOLD`（当前 `10.0`）。Web 表单同名字段可覆盖。

处理成功后会自动 bake：

- `cs:baked/p{W}x{H}/…` 行模板  
- `cs:baked/<name>/play` 视频入口  
- `cs:baked/dirty/*` 脏像素应用  

### 3. Web UI

```bash
python web_app.py
# 可选热重载
python web_app.py --reload
```

浏览器打开 http://127.0.0.1:8765 。

### 4. 游戏内播放

```mcfunction
/reload
# 站在画面原点（脚下方块中心对齐）
/function cs:baked/<video_name>/play
/function cs:baked/<video_name>/stop
```

单图（处理后）：

```mcfunction
/function cs:get {source_name:"test_img"}
# 或
/function cs:baked/src/test_img
```

## 目录说明

```text
Cushion-Screen/
  cushion_screen.py       # 核心管线
  bake_test_video_play.py # 烘焙数据包
  web_app.py              # Web 服务
  web/index.html
  requirements.txt
  examples/               # 示例媒体
  data/cs/                # 运行时生成 command_storage.dat
  datapacks/cushion_screen/
```

## 许可

按仓库 LICENSE 文件（若未附带则保留作者权利，仅供学习与自用）。

## 致谢

坐垫屏玩法与差分播放思路可参考社区同类项目（如 CusionBadApple）。本项目侧重 CIEDE 配色、storage 脏更新与工具链。
