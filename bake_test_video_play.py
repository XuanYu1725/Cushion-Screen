#!/usr/bin/env python3
"""
按分辨率烘焙「按行全量」放置模板 + dirty 逐像素应用 + 视频播放入口。

storage 帧格式（与 cushion_screen 一致）:
  全量帧（图片 / 视频第 0 帧）:
    { full:1b, rows: [ { light_block:{x:block}, cushion_color:{x:color} }, ... ] }
  脏帧（t>0）:
    { full:0b, d: [ {x, y, l:light_block, c:color}, ... ] }

数据包:
  full  → 取 rows，按行 place_block(宏) + place_summon/update
  dirty → 遍历 d[]，每脏像素一次宏 setblock + data modify 改色
"""

from __future__ import annotations

import argparse
import gzip
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACK_FN = ROOT / "datapacks" / "cushion_screen" / "data" / "cs" / "function"
BAKED_ROOT = PACK_FN / "baked"
DIRTY_ROOT = BAKED_ROOT / "dirty"
VIDEO_NAME = "test_video"
DAT_CANDIDATES = [
    ROOT / "data" / "cs" / "command_storage.dat",
    ROOT / "data" / "cs" / "command_storage.last.dat",
]

# 每次 pump 顺序处理的脏像素数；递归深度 ≈ ceil(n/PUMP_SIZE)
DIRTY_PUMP_SIZE = 4096


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def key_x(x: int) -> str:
    """行内列键 / 宏参数名"""
    return str(int(x))


def scaled_size_from_video(video_path: Path, target_height: int) -> tuple[int, int] | None:
    try:
        import cv2
    except ImportError:
        return None
    if not video_path.exists():
        return None
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    w = float(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = float(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    if w <= 0 or h <= 0:
        return None
    new_w = int(round(w * (target_height / h)))
    return max(1, new_w), int(target_height)


def estimate_from_video(video_path: Path, target_fps: float = 20.0) -> int | None:
    """与 cushion_screen.compute_video_sample_plan 一致：按时长对齐的采样帧数。"""
    try:
        from cushion_screen import estimate_sampled_frame_count

        return estimate_sampled_frame_count(video_path, target_fps=target_fps)
    except Exception:
        pass
    try:
        import cv2
    except ImportError:
        return None
    if not video_path.exists():
        return None
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    origin_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    if total <= 0:
        return None
    duration = total / origin_fps
    if target_fps is None or target_fps <= 0 or target_fps >= origin_fps:
        return total
    return max(1, int(round(duration * float(target_fps))))


def ensure_dirty_pack() -> Path:
    """
    脏像素应用（与分辨率无关）:
      start  — 从 baked.frame.d 拷贝，初始化下标
      loop   — 一批 pump 后若未完则自调
      pump   — 顺序最多 DIRTY_PUMP_SIZE 次 once（浅调用栈）
      once   — 按下标取 d[i] 并 apply
      apply  — 宏: setblock $(l) + 改色 from p.c
    """
    if DIRTY_ROOT.exists():
        shutil.rmtree(DIRTY_ROOT)
    DIRTY_ROOT.mkdir(parents=True, exist_ok=True)

    write_text(
        DIRTY_ROOT / "apply.mcfunction",
        """# 宏参数: x y l c（来自 d[i]）
# setblock 必须用宏；颜色从 cs:temp baked.p.c 读，避免 value 引号问题

$execute positioned ~$(x) ~0 ~$(y) run setblock ~ ~ ~ $(l)
$execute positioned ~$(x) ~0.28 ~$(y) run data modify entity @n[type=minecraft:cushion,tag=cs_frame,distance=..0.3] color set from storage cs:temp baked.p.c
""",
    )

    write_text(
        DIRTY_ROOT / "once.mcfunction",
        """# 处理 d[#i]，然后 #i++
execute store result storage cs:temp baked.idx.i int 1 run scoreboard players get #i cs.video
function cs:baked/dirty/step with storage cs:temp baked.idx
scoreboard players add #i cs.video 1
""",
    )

    write_text(
        DIRTY_ROOT / "step.mcfunction",
        """# 宏: i
$data modify storage cs:temp baked.p set from storage cs:temp baked.d[$(i)]
function cs:baked/dirty/apply with storage cs:temp baked.p
""",
    )

    pump_lines = [
        f"# 顺序处理最多 {DIRTY_PUMP_SIZE} 个脏像素（同深度，避免递归爆栈）",
        "",
    ]
    for _ in range(DIRTY_PUMP_SIZE):
        pump_lines.append(
            "execute if score #i cs.video < #n cs.video run function cs:baked/dirty/once"
        )
    write_text(DIRTY_ROOT / "pump.mcfunction", "\n".join(pump_lines) + "\n")

    write_text(
        DIRTY_ROOT / "loop.mcfunction",
        """execute if score #i cs.video >= #n cs.video run return 0
function cs:baked/dirty/pump
execute if score #i cs.video < #n cs.video run function cs:baked/dirty/loop
""",
    )

    write_text(
        DIRTY_ROOT / "start.mcfunction",
        """# 依赖: cs:temp baked.frame 已是当前脏帧（full:0b, d:[...]）
# 在屏幕原点 at 执行

data modify storage cs:temp baked.d set from storage cs:temp baked.frame.d
execute store result score #n cs.video run data get storage cs:temp baked.d
execute if score #n cs.video matches 0 run return 0
scoreboard players set #i cs.video 0
function cs:baked/dirty/loop
""",
    )
    return DIRTY_ROOT


def ensure_size_pack(width: int, height: int) -> Path:
    """
    按行生成放置文件（仅用于 full 帧）:
      row/<y>/place_block   — 宏 with 该行 light_block
      row/<y>/place_summon  — 无宏
      row/<y>/place_update  — 无宏
      apply_summon / apply_update — 顺序加载 rows[y] 并刷新每一行
    """
    width, height = int(width), int(height)
    slot = BAKED_ROOT / f"p{width}x{height}"
    if slot.exists():
        shutil.rmtree(slot)
    slot.mkdir(parents=True, exist_ok=True)

    color_root = "cs:temp baked.cushion_color"
    apply_summon: list[str] = [
        f"# 按行 summon  {width}×{height}  (full 帧)",
        f"# 依赖: cs:temp baked.frame.rows[] 已就绪",
        "",
    ]
    apply_update: list[str] = [
        f"# 按行 update  {width}×{height}  (full 帧关键帧/回退)",
        f"# 依赖: cs:temp baked.frame.rows[] 已就绪",
        "",
    ]

    for y in range(height):
        row_dir = slot / "row" / str(y)
        row_dir.mkdir(parents=True, exist_ok=True)

        block_lines = [
            f"# row {y} place_block  宽 {width}",
            f"# function …/row/{y}/place_block with storage cs:temp baked.light_block",
            f"# 宏键为列 x → $(x)",
            "",
        ]
        summon_lines = [
            f"# row {y} place_summon（无宏）",
            f"# 依赖 {color_root}.\"x\"",
            "",
        ]
        update_lines = [
            f"# row {y} place_update（无宏）",
            f"# 依赖 {color_root}.\"x\"",
            "",
        ]

        for x in range(width):
            k = key_x(x)
            block_lines.append(
                f"$execute positioned ~{x} ~0 ~{y} run setblock ~ ~ ~ $({k})"
            )
            color_path = f'{color_root}."{k}"'
            summon_lines.append(
                f'summon cushion ~{x} ~0.28 ~{y} {{Tags:["cs_frame"]}}'
            )
            summon_lines.append(
                f"execute positioned ~{x} ~0.28 ~{y} run "
                f"data modify entity @n[type=minecraft:cushion,tag=cs_frame,distance=..0.3] color "
                f"set from storage {color_path}"
            )
            update_lines.append(
                f"execute positioned ~{x} ~0.28 ~{y} run "
                f"data modify entity @n[type=minecraft:cushion,tag=cs_frame,distance=..0.3] color "
                f"set from storage {color_path}"
            )

        write_text(row_dir / "place_block.mcfunction", "\n".join(block_lines) + "\n")
        write_text(row_dir / "place_summon.mcfunction", "\n".join(summon_lines) + "\n")
        write_text(row_dir / "place_update.mcfunction", "\n".join(update_lines) + "\n")

        apply_summon.append(
            f"data modify storage cs:temp baked.light_block set from "
            f"storage cs:temp baked.frame.rows[{y}].light_block"
        )
        apply_summon.append(
            f"data modify storage cs:temp baked.cushion_color set from "
            f"storage cs:temp baked.frame.rows[{y}].cushion_color"
        )
        apply_summon.append(
            f"function cs:baked/p{width}x{height}/row/{y}/place_block "
            f"with storage cs:temp baked.light_block"
        )
        apply_summon.append(
            f"function cs:baked/p{width}x{height}/row/{y}/place_summon"
        )
        apply_summon.append("")

        apply_update.append(
            f"data modify storage cs:temp baked.light_block set from "
            f"storage cs:temp baked.frame.rows[{y}].light_block"
        )
        apply_update.append(
            f"data modify storage cs:temp baked.cushion_color set from "
            f"storage cs:temp baked.frame.rows[{y}].cushion_color"
        )
        apply_update.append(
            f"function cs:baked/p{width}x{height}/row/{y}/place_block "
            f"with storage cs:temp baked.light_block"
        )
        apply_update.append(
            f"function cs:baked/p{width}x{height}/row/{y}/place_update"
        )
        apply_update.append("")

    write_text(slot / "apply_summon.mcfunction", "\n".join(apply_summon) + "\n")
    write_text(slot / "apply_update.mcfunction", "\n".join(apply_update) + "\n")
    return slot


def bake_source_show(source_name: str, width: int, height: int, *, frame_index: int = 0) -> Path:
    flat = f"cs:baked/p{width}x{height}"
    path = BAKED_ROOT / "src" / f"{source_name}.mcfunction"
    write_text(
        path,
        f"""# 展示 cache.{source_name}[{frame_index}]  full+rows @ {width}x{height}
gamerule random_tick_speed 0
gamerule max_command_sequence_length 2147483647

execute unless data storage cs:cache {source_name}[{frame_index}].rows[0] run return run tellraw @s [{{"text":"[cs:baked/src/{source_name}] 缺少 full rows","color":"red"}}]

data modify storage cs:temp baked.frame set from storage cs:cache {source_name}[{frame_index}]

kill @e[type=minecraft:cushion,tag=cs_frame,distance=..512]
function {flat}/apply_summon
""",
    )
    return path


def bake_video_play(
    video_name: str,
    width: int,
    height: int,
    n_frames: int,
    postpone: str = "1t",
) -> Path:
    out = BAKED_ROOT / video_name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    max_time = max(0, int(n_frames) - 1)
    flat = f"cs:baked/p{width}x{height}"

    write_text(
        out / "play.mcfunction",
        f"""# cs:baked/{video_name}/play
# [0]=full+rows  [t>0]=dirty d[]  {width}×{height}  帧 0..{max_time}  postpone={postpone}

scoreboard objectives add cs.video dummy

data modify storage cs:temp baked_play.name set value "{video_name}"
scoreboard players set #max cs.video {max_time}
scoreboard players set #time cs.video -1
scoreboard players set #playing cs.video 1

kill @e[type=marker,tag=cs_video_origin]
execute align xyz positioned ~0.5 ~0.5 ~0.5 run summon marker ~ ~ ~ {{Tags:["cs_video_origin"]}}

schedule clear cs:baked/{video_name}/tick
schedule clear cs:video/tick
schedule function cs:baked/{video_name}/tick {postpone} replace

tellraw @s [{{"text":"[cs:baked/{video_name}] {width}x{height}  帧 0..{max_time}  {postpone}  dirty","color":"green"}}]
""",
    )

    write_text(
        out / "tick.mcfunction",
        f"""execute unless score #playing cs.video matches 1 run return 0
execute unless entity @e[type=marker,tag=cs_video_origin,limit=1] run return run function cs:baked/{video_name}/stop

scoreboard players add #time cs.video 1
execute if score #time cs.video > #max cs.video run return run function cs:baked/{video_name}/stop

execute store result storage cs:temp baked_play.time int 1 run scoreboard players get #time cs.video
execute as @e[type=marker,tag=cs_video_origin,limit=1] at @s run function cs:baked/{video_name}/draw with storage cs:temp baked_play

schedule function cs:baked/{video_name}/tick {postpone} replace
""",
    )

    write_text(
        out / "draw.mcfunction",
        f"""# 宏参数: name, time
# full → 按行 apply_summon / apply_update
# dirty → cs:baked/dirty/start

gamerule max_command_sequence_length 2147483647

$data modify storage cs:temp baked.frame set from storage cs:cache $(name)[$(time)]

# 脏帧
execute if data storage cs:temp baked.frame{{full:0b}} run return run function cs:baked/dirty/start

# 全量帧
execute unless data storage cs:temp baked.frame.rows[0] run return run tellraw @a [{{"text":"[cs:baked] 缺少 frame.rows（full 帧）","color":"red"}}]
execute if score #time cs.video matches 0 run kill @e[type=minecraft:cushion,tag=cs_frame,distance=..512]
execute if score #time cs.video matches 0 run return run function {flat}/apply_summon
function {flat}/apply_update
""",
    )

    write_text(
        out / "stop.mcfunction",
        f"""scoreboard players set #playing cs.video 0
schedule clear cs:baked/{video_name}/tick
tellraw @a [{{"text":"[cs:baked/{video_name}] 播放结束","color":"gray"}},{{"text":" time=","color":"dark_gray"}},{{"score":{{"name":"#time","objective":"cs.video"}},"color":"dark_gray"}},{{"text":"/","color":"dark_gray"}},{{"score":{{"name":"#max","objective":"cs.video"}},"color":"dark_gray"}}]
""",
    )
    return out


def bake_for_media(
    *,
    width: int,
    height: int,
    source_name: str,
    n_frames: int = 1,
    postpone: str = "1t",
    is_video: bool = False,
) -> dict:
    ensure_dirty_pack()
    ensure_size_pack(width, height)
    info = {"width": width, "height": height, "source_name": source_name}
    if is_video:
        bake_video_play(source_name, width, height, n_frames, postpone=postpone)
        info["play"] = f"cs:baked/{source_name}/play"
        info["n_frames"] = n_frames
    else:
        bake_source_show(source_name, width, height, frame_index=0)
        info["show"] = f"cs:baked/src/{source_name}"
    return info


def main() -> None:
    ap = argparse.ArgumentParser(description="Bake full-row + dirty place templates")
    ap.add_argument("--height", type=int, default=64)
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--frames", type=int, default=None)
    ap.add_argument("--fps", type=float, default=20.0)
    ap.add_argument("--video-name", default=VIDEO_NAME)
    ap.add_argument("--video", type=Path, default=ROOT / "test_video.mp4")
    ap.add_argument("--postpone", default="1t")
    ap.add_argument("--image-only", action="store_true")
    args = ap.parse_args()

    width = args.width
    height = args.height
    if width is None:
        sz = scaled_size_from_video(args.video, height)
        if sz:
            width, height = sz
        else:
            width = int(round(height * 16 / 9))

    n_frames = args.frames
    if n_frames is None and not args.image_only:
        n_frames = estimate_from_video(args.video, args.fps) or 1

    ensure_dirty_pack()
    ensure_size_pack(width, height)
    if args.image_only:
        bake_source_show(args.video_name, width, height)
        print(f"baked src show {width}x{height}")
    else:
        bake_video_play(args.video_name, width, height, int(n_frames), postpone=args.postpone)
        print(f"baked play {args.video_name} {width}x{height} frames={n_frames}")


if __name__ == "__main__":
    main()
