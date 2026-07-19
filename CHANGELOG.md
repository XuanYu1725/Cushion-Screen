# Changelog

本文件记录 [Cushion-Screen](https://github.com/XuanYu1725/Cushion-Screen) 的技术向变更。  
格式大致遵循 [Keep a Changelog](https://keepachangelog.com/)，版本语义参考 [SemVer](https://semver.org/)。

仓库提交（新 → 旧）：

| Commit | 说明 |
|--------|------|
| `fa9e5c1` | 确定性 UUID 坐垫 + dirty `u` 字段 |
| `e1a425e` | 暴露 `dirty_ciede2000_threshold`（API / Web） |
| `2ac4153` | README：去掉过时 skip 采样说明 |
| `7cabed9` | 去掉方块/坐垫多余 Y `+1` 偏移 |
| `7c6781c` | **v1.0.0** 首发 |

---

## [Unreleased]

相对 `v1.0.0`（`7c6781c`）之后、尚未打 tag 的变更汇总。

### Added

#### 确定性 UUID 坐垫（`fa9e5c1`）

- **UUID 布局**（连字符五段，各段为十六进制数值，**不强制前导 0**，与 Wiki 一致）：
  ```text
  {source_hash}-0-0-{x:x}-{y:x}
  ```
  - 第 1 段：`source_name` 的 CRC32 → `format(h, "x")`（如 `test_video` → `77197c27`）
  - 第 2、3 段：固定 `0`
  - 第 4、5 段：像素坐标 `x`、`y` 的十六进制（例：`(10,20)` → `…-a-14`）
- **summon**：`{UUID:uuid("$(src)-0-0-{x:x}-{y:x}"), Tags:["cs_frame"]}`
- **改色**：`data modify entity <uuid> color set from …`（全量行模板与 dirty 路径均不再使用 `@n[type=cushion,distance=…]`）
- **清理**：bake 生成 `cs:baked/<name>/clear`，对每个像素 `kill <uuid>`；`stop` / 首帧重铺前调用，避免全图 `@e` 扫描混杀其它 source
- **Storage 脏列表扩展**：
  ```text
  d: [ { x, y, l, c, u }, ... ]
  ```
  - `u` 为完整 UUID 字符串，供 `cs:baked/dirty/apply` 中 `$data modify entity $(u) …`
- **共享分辨率模板**：`place_summon` / `place_update` 以宏参数 `$(src)`（= source hash）实例化；播放时 `data modify storage cs:temp baked.uuid.src set value "…"`

相关 API：

| 符号 | 作用 |
|------|------|
| `source_uuid_hash(name)` | CRC32 → hex 第一段 |
| `pixel_uuid(src_hash, x, y)` | 拼完整 UUID |
| `plain_to_dirty_compound(..., source_name= / src_hash=)` | 写 dirty 时填入 `u` |

#### 可配置脏判定阈值（`e1a425e`）

- `process_media(..., dirty_ciede2000_threshold=None)`
- `process_video_to_storage(..., dirty_ciede2000_threshold=None)`
- 取值：
  | 值 | 行为 |
  |----|------|
  | `None` | 使用模块全局 `DIRTY_CIEDE2000_THRESHOLD`（默认 `10.0`） |
  | `0` / `False` | 严格字符串相等（旧行为，Bayer 下脏率偏高） |
  | `"auto"` | 色板最近邻 ΔE 中位数 ×1.25，夹在 `[5, 14]` |
  | `float` | 固定 CIEDE2000 阈值：ΔE ≥ thr 才记脏 |
- 脏判定相对 **屏上累积显示状态**（仅真正写出的脏像素更新 displayed），避免跨帧漂移
- Web：`/api/defaults` 返回当前默认；表单字段 `dirty_ciede2000_threshold`（`auto` / 数字 / `0`）
- README 参数表同步

### Changed

#### 放置高度（`7cabed9`）

相对播放原点（`align xyz` + `~0.5 ~0.5 ~0.5` marker）：

| 对象 | 旧 | 新 |
|------|----|----|
| 光照方块 | `~x ~1 ~z` | `~x ~0 ~z` |
| 坐垫 | `~x ~1.28 ~z` | `~x ~0.28 ~z` |

坐垫仍相对方块抬高 **0.28**，仅去掉多余的整格 `+1`。涉及：

- `bake_test_video_play.py` 生成的行模板 / dirty apply
- `internal/place_pixel`、`place_pixel_update`

#### 文档（`2ac4153`）

- README 采样说明去掉过时措辞「而不是旧的 `skip=2 → 15fps`」（实现早已改为时间轴采样，见 v1.0.0）

### Breaking / 兼容性注意（Unreleased）

1. **旧 dirty 帧无 `u` 字段**：UUID 改色路径会失效 → 需 **重新 `process_media` 视频**。
2. **旧坐垫无确定性 UUID**：应用 `clear` 或重播首帧前需清场；仅 reload 数据包不够。
3. **Y 偏移变更**：与 v1.0.0 生成的世界坐标差 1 格垂直；旧画面需按新原点重放。
4. 仓库 **不提交** 按分辨率 bake 的 `p{W}x{H}` 与超大 `clear.mcfunction`（本地处理时自动生成）。

---

## [1.0.0] — 2026-07-19

**Tag:** `v1.0.0` · **Commit:** `7c6781c`

首发：Python 管线 + command_storage 脏帧 + 烘焙数据包 + Web UI。

### 架构总览

```text
媒体 (图/视频)
  → 等比缩放 (target_height) + Bayer 抖动
  → CIEDE2000 映射到 cushion color × light_block 色板
  → 视频: 时间轴采样 + 脏像素压缩
  → gzip NBT: data/cs/command_storage.dat  (storage cs:cache)
  → bake: cs:baked/p{W}x{H} + cs:baked/<name>/play + dirty/*
游戏内:
  play → tick(postpone) → draw → full 按行放置 | dirty 泵送更新
```

### Python（`cushion_screen.py`）

#### 配色

- 色板：cushion 颜色 × 一组 `base_blocks`（光照方块）
- 距离：CIEDE2000（Lab）；多进程 `ProcessPoolExecutor` 加速帧批
- Bayer 有序抖动：矩阵 `"auto" | 2 | 4 | 8 | 16`，强度可配

#### 视频采样（非整除帧率）

- **时间轴均匀取样**（非固定 `skip = round(src/target)`）：
  ```text
  duration = total_src / origin_fps
  n_out    = round(duration × use_fps)
  src[i]   = round(i × origin_fps / use_fps)   # 末帧对齐片尾
  use_fps  = min(target_fps, origin_fps)
  ```
- 保证 `n_out / use_fps ≈ duration`（例：30 fps 源 × 目标 20 fps → 约 `round(T×20)` 帧，播放 `1t` 间隔）
- `postpone_ticks`：由 `use_fps` 映射到整数 tick（20 fps → `1t`）

#### Storage 布局（`cs:cache`）

```text
cache.<source_name> = [
  { full: 1b, rows: [
      { light_block: { "0": block, "1": ... }, cushion_color: { "0": color, ... } },  # y=0
      ...
    ] },
  { full: 0b, d: [ { x, y, l, c }, ... ] },   # t>0 脏帧（相对屏上显示）
  ...
]
```

- 图片：仅 `[0]` 全量
- 视频：`[0]` full+rows；`[t>0]` dirty 列表
- 行内列键为十进制字符串 `"0"…"W-1"`（与宏 `$(0)` 等对应）
- 写入：`command_storage.dat`（gzip NBT）；成功后覆盖 `command_storage.last.dat` 单备份
- 大文件加载策略：超阈值可跳过全量 reload，避免 init 假死；写盘前 `ensure_parent_dir`；`os.replace` 失败时重试/保留 `.tmp`

#### 脏像素

- 相对 **displayed** 状态比较，非简单与上一编码帧比
- 默认阈值 `DIRTY_CIEDE2000_THRESHOLD`（v1.0.0 为模块常量；后在 Unreleased 暴露为参数）
- 色板对距离矩阵预计算，判定为查表

#### 分段与并发

- 按 `w×h` 与 `MP_VIDEO_PIXEL_BUDGET` 动态 `batch_size`
- 批次边界响应 `request_cancel`（Web 停止）
- 进度回调：`phase / current / total / percent / elapsed / eta_seconds / message`

#### 入口

- `process_media(...)`：自动识别图/视频
- `process_video_to_storage(...)` / 图片 rebuild 路径
- 成功后调用 `bake_for_media` 生成数据包侧模板

### 烘焙（`bake_test_video_play.py`）

| 产物 | 作用 |
|------|------|
| `cs:baked/p{W}x{H}/row/{y}/place_block` | 宏：`$setblock` with 行内 `light_block` map |
| `…/place_summon` / `place_update` | 首帧召唤 / 全量关键帧改色 |
| `…/apply_summon` / `apply_update` | 按行装载 `rows[y]` 并调用上述函数 |
| `cs:baked/dirty/{start,loop,pump,once,step,apply}` | 脏列表泵送（每批最多 4096，防递归爆栈） |
| `cs:baked/<video>/play\|tick\|draw\|stop` | 固定 postpone 调度；draw 分支 full / dirty |
| `cs:baked/src/<image>` | 单图展示入口 |

设计取舍（相对早期实验）：

- **不**把整帧像素写进数千个 `frame/N.mcfunction`（数据在 storage）
- **不**在播放端做调色板展开（映射在 Python 完成）
- setblock 保留宏（方块 id 运行时才知）；颜色尽量 `data modify from storage`
- 分辨率模板一份共享；source 专用控制流与（后续）UUID hash

### 数据包运行时

- 原点：`marker` + `cs_video_origin`；`align xyz positioned ~0.5 ~0.5 ~0.5`
- `gamerule max_command_sequence_length` 在 draw 中抬高，支撑大屏命令链
- 通用路径遗留：`play_video` / `get_frame` / `internal/*`（宏较重）；推荐 bake 入口
- pack 元数据：见 `datapacks/cushion_screen/pack.mcmeta`（面向新 Java 快照）

### Web UI（`web_app.py` + `web/`）

- 本地 `ThreadingHTTPServer`（默认 `8765`）
- 上传媒体 → 后台线程 `process_media`
- 进度轮询、ETA、停止（`request_cancel`）、从 `.last.dat` 恢复
- 可选 `--reload`
- 表单：高度、fps、dither 矩阵、pixel_budget 等（阈值字段见 Unreleased）

### 依赖与示例

- `numpy`、`Pillow`、`nbtlib`、`opencv-python-headless`
- `examples/test_img.png`、`examples/test_video.mp4`
- MIT `LICENSE`、README、`.gitignore`（排除 dat / 预览 / 巨型 bake）

### 已知限制（v1.0.0 时点）

- 播放性能 ∝ 脏像素量；强 Bayer + 细色板时脏率仍可偏高（靠提高 ΔE 阈值）
- 无帧间矩形合并 / `fill` 批处理（与部分社区实现差异）
- 处理时需退出世界，避免 `command_storage.dat` 文件锁
- 实体定位在 v1.0.0 仍依赖距离选择器（后由 UUID 方案替代，见 Unreleased）

---

## 设计备忘（跨版本）

| 主题 | 选择 |
|------|------|
| 数据放哪 | `command_storage` 按 source 列表帧；函数只 bake 控制流与网格 |
| 全量 vs 差分 | 首帧 full rows；之后 dirty；可选 CIEDE 阈值压脏率 |
| 宏策略 | 路径/坐标尽量写死或一次大宏；避免每像素多参数宏 + 列表 `remove[0]` |
| 采样 | 时间轴对齐时长，不用固定 skip 牺牲目标 fps |
| 实体 | v1.0.0：`@n`+tag；Unreleased：确定性 UUID + clear |

---

## 链接

- 仓库：https://github.com/XuanYu1725/Cushion-Screen  
- 对比：`v1.0.0...main` → https://github.com/XuanYu1725/Cushion-Screen/compare/v1.0.0...main
