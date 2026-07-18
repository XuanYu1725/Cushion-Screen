import os
import sys
import shutil
import numpy as np
from pathlib import Path
from PIL import Image
from math import atan2, sqrt, pi
from concurrent.futures import ProcessPoolExecutor, as_completed
from nbtlib import File, Compound, List, String, Int, Byte, load as nbt_load

try:
    import cv2
except ImportError:  # 仅处理图片时可不装 opencv
    cv2 = None

# ---------------------------------------------------------------------------
# 多进程配置
# ---------------------------------------------------------------------------
MP_ENABLED = True
# 工作进程数：默认 CPU-1，至少 1
MP_WORKERS = max(1, (os.cpu_count() or 4) - 1)
# 像素数低于此阈值不启用像素级并行（避免进程开销）
MP_MIN_PIXELS = 8000
# 每个进程至少处理的像素数（用于计算分块数）
MP_MIN_CHUNK = 3000
# 像素级并行最多进程数（过多短任务在 Windows 上 spawn 开销大）
MP_PIXEL_WORKERS_CAP = 8
# 视频分段写入：None/0=按任务参数自动算；正整数=强制固定批大小
MP_VIDEO_BATCH = None
# 每批总像素预算（帧像素×批帧数），越大越省调度、越吃内存
# 视频落盘为 pixels[]（空间换播放速度），预算不宜过大
MP_VIDEO_PIXEL_BUDGET = 250_000
MP_VIDEO_BATCH_MIN = 1
MP_VIDEO_BATCH_MAX = 48
# 视频开工时若 dat 超过此大小，跳过 nbtlib 全量加载（否则会在 init 卡数分钟～看似死机）
# 旧文件会先复制到 command_storage.last.dat；本次只写入本视频帧
VIDEO_SKIP_LOAD_DAT_BYTES = 1_500_000

# 协作式取消（Web 停止按钮 / 外部设置）
_cancel_requested = False


def request_cancel():
    """请求取消当前 process_media / 视频处理（批次边界生效）。"""
    global _cancel_requested
    _cancel_requested = True


def clear_cancel():
    global _cancel_requested
    _cancel_requested = False


def cancel_requested():
    return bool(_cancel_requested)


class ProcessingCancelled(Exception):
    """用户取消处理。"""
    pass

# ---------------------------------------------------------------------------
# 唯一 dat 缓存（处理成功后覆盖写入；防游戏回写覆盖）
# 始终只保留这一份，路径固定在 dat 同目录
# ---------------------------------------------------------------------------
STORAGE_BACKUP_NAME = "command_storage.last.dat"
# 每次 merge 成功后自动备份
AUTO_BACKUP_AFTER_WRITE = True

# 修复：末尾添加逗号
base_blocks = [
    "waxed_copper_bulb[lit=true]",
    "furnace[lit=true]",
    "waxed_exposed_copper_bulb[lit=true]",
    "respawn_anchor[charges=3]",
    "crying_obsidian",
    "redstone_ore[lit=true]",
    "waxed_weathered_copper_bulb[lit=true]",
    "respawn_anchor[charges=2]",
    "sculk_catalyst",
    "waxed_oxidized_copper_bulb[lit=true]",
    "magma_block",
    "stone"
]

RGB_MAP = {
    (50, 50, 66): ['black', '1'],
    (18, 16, 18): ['black', '10'],
    (15, 15, 17): ['black', '11'],
    (7, 8, 10): ['black', '12'],
    (47, 43, 50): ['black', '2'],
    (44, 39, 43): ['black', '3'],
    (41, 35, 36): ['black', '4'],
    (37, 32, 31): ['black', '5'],
    (34, 29, 27): ['black', '6'],
    (31, 26, 25): ['black', '7'],
    (28, 24, 23): ['black', '8'],
    (24, 21, 21): ['black', '9'],
    (72, 102, 181): ['blue', '1'],
    (25, 32, 46): ['blue', '10'],
    (21, 27, 42): ['blue', '11'],
    (9, 13, 20): ['blue', '12'],
    (68, 90, 135): ['blue', '2'],
    (63, 81, 115): ['blue', '3'],
    (57, 72, 98): ['blue', '4'],
    (52, 64, 84): ['blue', '5'],
    (48, 59, 74): ['blue', '6'],
    (43, 53, 67): ['blue', '7'],
    (39, 47, 61): ['blue', '8'],
    (34, 42, 55): ['blue', '9'],
    (154, 98, 58): ['brown', '1'],
    (51, 31, 17): ['brown', '10'],
    (43, 26, 15): ['brown', '11'],
    (17, 12, 9): ['brown', '12'],
    (147, 87, 44): ['brown', '2'],
    (134, 78, 38): ['brown', '3'],
    (123, 70, 32): ['brown', '4'],
    (111, 62, 28): ['brown', '5'],
    (101, 57, 25): ['brown', '6'],
    (92, 51, 23): ['brown', '7'],
    (80, 46, 21): ['brown', '8'],
    (71, 40, 19): ['brown', '9'],
    (34, 159, 154): ['cyan', '1'],
    (13, 48, 40): ['cyan', '10'],
    (11, 41, 36): ['cyan', '11'],
    (6, 18, 19): ['cyan', '12'],
    (33, 140, 116): ['cyan', '2'],
    (31, 126, 98): ['cyan', '3'],
    (28, 112, 84): ['cyan', '4'],
    (25, 101, 71): ['cyan', '5'],
    (23, 91, 63): ['cyan', '6'],
    (20, 82, 57): ['cyan', '7'],
    (20, 74, 52): ['cyan', '8'],
    (16, 64, 47): ['cyan', '9'],
    (99, 114, 119): ['gray', '1'],
    (34, 35, 30): ['gray', '10'],
    (28, 30, 28): ['gray', '11'],
    (12, 13, 15): ['gray', '12'],
    (94, 100, 90): ['gray', '2'],
    (88, 91, 77): ['gray', '3'],
    (80, 80, 65): ['gray', '4'],
    (73, 72, 56): ['gray', '5'],
    (66, 66, 49): ['gray', '6'],
    (60, 59, 44): ['gray', '7'],
    (53, 53, 41): ['gray', '8'],
    (46, 46, 37): ['gray', '9'],
    (100, 127, 30): ['green', '1'],
    (34, 39, 9): ['green', '10'],
    (28, 33, 10): ['green', '11'],
    (12, 15, 7): ['green', '12'],
    (95, 112, 23): ['green', '2'],
    (88, 100, 20): ['green', '3'],
    (80, 90, 18): ['green', '4'],
    (73, 80, 15): ['green', '5'],
    (66, 73, 14): ['green', '6'],
    (60, 65, 13): ['green', '7'],
    (53, 59, 12): ['green', '8'],
    (46, 52, 11): ['green', '9'],
    (49, 162, 207): ['light_blue', '1'],
    (17, 49, 52): ['light_blue', '10'],
    (15, 42, 46): ['light_blue', '11'],
    (8, 18, 23): ['light_blue', '12'],
    (46, 143, 154): ['light_blue', '2'],
    (43, 129, 131): ['light_blue', '3'],
    (39, 114, 112): ['light_blue', '4'],
    (35, 103, 96): ['light_blue', '5'],
    (33, 93, 85): ['light_blue', '6'],
    (30, 83, 76): ['light_blue', '7'],
    (27, 75, 69): ['light_blue', '8'],
    (23, 66, 62): ['light_blue', '9'],
    (160, 158, 152): ['light_gray', '1'],
    (54, 48, 39): ['light_gray', '10'],
    (45, 41, 36): ['light_gray', '11'],
    (18, 18, 18): ['light_gray', '12'],
    (151, 140, 113): ['light_gray', '2'],
    (140, 126, 96): ['light_gray', '3'],
    (126, 112, 81): ['light_gray', '4'],
    (116, 101, 71): ['light_gray', '5'],
    (105, 91, 62): ['light_gray', '6'],
    (95, 82, 56): ['light_gray', '7'],
    (84, 74, 51): ['light_gray', '8'],
    (73, 65, 46): ['light_gray', '9'],
    (137, 188, 43): ['lime', '1'],
    (46, 57, 13): ['lime', '10'],
    (38, 48, 12): ['lime', '11'],
    (15, 21, 7): ['lime', '12'],
    (129, 165, 32): ['lime', '2'],
    (120, 149, 28): ['lime', '3'],
    (109, 132, 24): ['lime', '4'],
    (98, 119, 21): ['lime', '5'],
    (90, 108, 19): ['lime', '6'],
    (81, 96, 17): ['lime', '7'],
    (72, 87, 16): ['lime', '8'],
    (63, 76, 15): ['lime', '9'],
    (198, 77, 168): ['magenta', '1'],
    (66, 25, 43): ['magenta', '10'],
    (54, 21, 39): ['magenta', '11'],
    (22, 10, 20): ['magenta', '12'],
    (188, 67, 127): ['magenta', '2'],
    (173, 61, 107): ['magenta', '3'],
    (158, 55, 92): ['magenta', '4'],
    (144, 49, 79): ['magenta', '5'],
    (130, 45, 70): ['magenta', '6'],
    (118, 40, 63): ['magenta', '7'],
    (104, 36, 57): ['magenta', '8'],
    (91, 32, 52): ['magenta', '9'],
    (246, 143, 45): ['orange', '1'],
    (81, 44, 13): ['orange', '10'],
    (67, 37, 13): ['orange', '11'],
    (26, 16, 7): ['orange', '12'],
    (234, 126, 33): ['orange', '2'],
    (215, 114, 29): ['orange', '3'],
    (197, 101, 25): ['orange', '4'],
    (179, 91, 21): ['orange', '5'],
    (162, 82, 20): ['orange', '6'],
    (146, 74, 18): ['orange', '7'],
    (129, 66, 16): ['orange', '8'],
    (112, 58, 15): ['orange', '9'],
    (235, 130, 161): ['pink', '1'],
    (78, 40, 41): ['pink', '10'],
    (64, 34, 39): ['pink', '11'],
    (25, 16, 19): ['pink', '12'],
    (224, 115, 120): ['pink', '2'],
    (205, 103, 104): ['pink', '3'],
    (188, 92, 87): ['pink', '4'],
    (171, 82, 75): ['pink', '5'],
    (155, 75, 67): ['pink', '6'],
    (140, 67, 60): ['pink', '7'],
    (123, 61, 55): ['pink', '8'],
    (108, 53, 50): ['pink', '9'],
    (164, 70, 206): ['purple', '1'],
    (55, 23, 52): ['purple', '10'],
    (45, 19, 47): ['purple', '11'],
    (19, 9, 23): ['purple', '12'],
    (156, 62, 154): ['purple', '2'],
    (144, 56, 131): ['purple', '3'],
    (131, 50, 111): ['purple', '4'],
    (119, 45, 95): ['purple', '5'],
    (108, 41, 84): ['purple', '6'],
    (97, 37, 75): ['purple', '7'],
    (86, 34, 69): ['purple', '8'],
    (75, 29, 62): ['purple', '9'],
    (196, 60, 48): ['red', '1'],
    (65, 20, 14): ['red', '10'],
    (53, 17, 13): ['red', '11'],
    (21, 9, 7): ['red', '12'],
    (186, 53, 37): ['red', '2'],
    (170, 48, 32): ['red', '3'],
    (156, 43, 27): ['red', '4'],
    (141, 39, 24): ['red', '5'],
    (128, 35, 21): ['red', '6'],
    (116, 32, 19): ['red', '7'],
    (102, 29, 18): ['red', '8'],
    (89, 25, 16): ['red', '9'],
    (222, 222, 222): ['white', '1'],
    (73, 68, 55): ['white', '10'],
    (61, 56, 50): ['white', '11'],
    (24, 24, 25): ['white', '12'],
    (211, 195, 166): ['white', '2'],
    (193, 176, 141): ['white', '3'],
    (177, 157, 119): ['white', '4'],
    (160, 141, 101): ['white', '5'],
    (146, 128, 90): ['white', '6'],
    (131, 113, 81): ['white', '7'],
    (117, 102, 74): ['white', '8'],
    (101, 90, 67): ['white', '9'],
    (241, 206, 58): ['yellow', '1'],
    (80, 63, 15): ['yellow', '10'],
    (66, 52, 15): ['yellow', '11'],
    (26, 23, 8): ['yellow', '12'],
    (227, 182, 42): ['yellow', '2'],
    (211, 164, 38): ['yellow', '3'],
    (192, 146, 31): ['yellow', '4'],
    (175, 131, 27): ['yellow', '5'],
    (159, 119, 25): ['yellow', '6'],
    (142, 106, 22): ['yellow', '7'],
    (127, 95, 20): ['yellow', '8'],
    (110, 84, 18): ['yellow', '9'],
}

def rgb2lab(rgb):
    r, g, b = rgb
    r /= 255.0
    g /= 255.0
    b /= 255.0

    def linearize(v):
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r_lin = linearize(r)
    g_lin = linearize(g)
    b_lin = linearize(b)

    x = r_lin * 0.4124564 + g_lin * 0.3575761 + b_lin * 0.1804375
    y = r_lin * 0.2126729 + g_lin * 0.7151522 + b_lin * 0.0721750
    z = r_lin * 0.0193339 + g_lin * 0.1191920 + b_lin * 0.9503041

    xn, yn, zn = 0.95047, 1.0, 1.08883
    x /= xn
    y /= yn
    z /= zn

    def f(t):
        return t ** (1/3) if t > 0.008856 else 7.787 * t + 16/116

    fx = f(x)
    fy = f(y)
    fz = f(z)

    L = 116 * fy - 16
    a = 500 * (fx - fy)
    b = 200 * (fy - fz)
    return (L, a, b)

def ciede2000(L1, a1, b1, L2, a2, b2):
    L_mean = (L1 + L2) / 2
    C1 = sqrt(a1**2 + b1**2)
    C2 = sqrt(a2**2 + b2**2)
    C_mean = (C1 + C2) / 2

    G = 0.5 * (1 - sqrt(C_mean**7 / (C_mean**7 + 25**7)))
    a1p = a1 * (1 + G)
    a2p = a2 * (1 + G)

    C1p = sqrt(a1p**2 + b1**2)
    C2p = sqrt(a2p**2 + b2**2)
    Cmep = (C1p + C2p) / 2

    h1p = atan2(b1, a1p)
    h1p += 2 * pi if h1p < 0 else 0
    h2p = atan2(b2, a2p)
    h2p += 2 * pi if h2p < 0 else 0

    h_diff = abs(h1p - h2p)
    if h_diff > pi:
        h_diff = 2 * pi - h_diff
    h_mean = (h1p + h2p) / 2
    if abs(h1p - h2p) > pi:
        h_mean += pi

    T = (1 - 0.17 * np.cos(h_mean - pi/6)
         + 0.24 * np.cos(2 * h_mean)
         + 0.32 * np.cos(3 * h_mean + pi/30)
         - 0.20 * np.cos(4 * h_mean - 21*pi/60))

    dL = L2 - L1
    dC = C2p - C1p
    dh = 2 * sqrt(C1p * C2p) * np.sin(h_diff / 2)

    SL = 1 + (0.015 * (L_mean - 50)**2) / sqrt(20 + (L_mean - 50)**2)
    SC = 1 + 0.045 * Cmep
    SH = 1 + 0.015 * Cmep * T

    dtheta = 30 * pi / 180 * np.exp(-((h_mean - 275*pi/180) / (25*pi/180))**2)
    RC = -2 * sqrt(Cmep**7 / (Cmep**7 + 25**7))
    RT = RC * np.sin(2 * dtheta)

    dE = sqrt(
        (dL / SL)**2 + (dC / SC)**2 + (dh / SH)**2
        + RT * (dC / SC) * (dh / SH)
    )
    return dE

# 预计算库颜色
COLOR_TABLE = [
    {"rgb": rgb, "lab": rgb2lab(rgb), "name": name}
    for rgb, name in RGB_MAP.items()
]
# 便于向量化查表
_COLOR_RGBS = np.array([item["rgb"] for item in COLOR_TABLE], dtype=np.uint8)
_COLOR_LABS = np.array([item["lab"] for item in COLOR_TABLE], dtype=np.float64)


def rgb2lab_batch(pixels):
    """批量 RGB→Lab。pixels: (N,3) uint8/float → (N,3) float64 Lab。"""
    rgb = np.asarray(pixels, dtype=np.float64) / 255.0
    mask = rgb <= 0.04045
    lin = np.empty_like(rgb)
    lin[mask] = rgb[mask] / 12.92
    lin[~mask] = ((rgb[~mask] + 0.055) / 1.055) ** 2.4
    r, g, b = lin[:, 0], lin[:, 1], lin[:, 2]
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    x = x / 0.95047
    y = y / 1.0
    z = z / 1.08883
    eps = 0.008856
    kappa = 7.787

    def f(t):
        return np.where(t > eps, np.cbrt(t), kappa * t + 16.0 / 116.0)

    fx, fy, fz = f(x), f(y), f(z)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    bb = 200.0 * (fy - fz)
    return np.stack([L, a, bb], axis=1)


def closest_color(pixel_rgb):
    tL, ta, tb = rgb2lab(pixel_rgb)
    min_de = float("inf")
    best_rgb = None
    for item in COLOR_TABLE:
        L, a, b = item["lab"]
        de = ciede2000(tL, ta, tb, L, a, b)
        if de < min_de:
            min_de = de
            best_rgb = item["rgb"]
    return best_rgb


def _closest_color_vectorized_core(pixels):
    """
    单进程核心：CIEDE2000 最近色。
    返回 (best_rgb uint8[N,3], best_idx int[N])
    """
    pixels = np.asarray(pixels, dtype=np.uint8)
    total = pixels.shape[0]
    if total == 0:
        return (
            np.zeros((0, 3), dtype=np.uint8),
            np.zeros((0,), dtype=np.int64),
        )

    labs = rgb2lab_batch(pixels)
    tL, ta, tb = labs[:, 0], labs[:, 1], labs[:, 2]

    best_rgb = np.zeros_like(pixels, dtype=np.uint8)
    min_de = np.full(total, np.inf, dtype=np.float64)
    best_idx = np.zeros(total, dtype=np.int64)

    for idx, item in enumerate(COLOR_TABLE):
        L2, a2, b2 = item["lab"]
        dL = L2 - tL

        C1 = np.sqrt(ta**2 + tb**2)
        C2 = np.sqrt(a2**2 + b2**2)
        C_mean = (C1 + C2) / 2

        G = 0.5 * (1 - np.sqrt(C_mean**7 / (C_mean**7 + 25**7)))
        a1p = ta * (1 + G)
        a2p = a2 * (1 + G)

        C1p = np.sqrt(a1p**2 + tb**2)
        C2p = np.sqrt(a2p**2 + b2**2)
        Cmep = (C1p + C2p) / 2

        h1p = np.arctan2(tb, a1p)
        h1p = np.where(h1p < 0, h1p + 2 * pi, h1p)
        h2p = np.arctan2(b2, a2p)
        h2p = np.where(h2p < 0, h2p + 2 * pi, h2p)

        h_diff = np.abs(h1p - h2p)
        h_diff = np.where(h_diff > pi, 2 * pi - h_diff, h_diff)

        h_mean = (h1p + h2p) / 2
        h_mean = np.where(np.abs(h1p - h2p) > pi, h_mean + pi, h_mean)

        T = (
            1
            - 0.17 * np.cos(h_mean - pi / 6)
            + 0.24 * np.cos(2 * h_mean)
            + 0.32 * np.cos(3 * h_mean + pi / 30)
            - 0.20 * np.cos(4 * h_mean - 21 * pi / 60)
        )

        dC = C2p - C1p
        dh = 2 * np.sqrt(C1p * C2p) * np.sin(h_diff / 2)

        L_mean = (tL + L2) / 2
        SL = 1 + (0.015 * (L_mean - 50) ** 2) / np.sqrt(20 + (L_mean - 50) ** 2)
        SC = 1 + 0.045 * Cmep
        SH = 1 + 0.015 * Cmep * T

        dtheta = (
            30
            * pi
            / 180
            * np.exp(-(((h_mean - 275 * pi / 180) / (25 * pi / 180)) ** 2))
        )
        RC = -2 * np.sqrt(Cmep**7 / (Cmep**7 + 25**7))
        RT = RC * np.sin(2 * dtheta)

        dE = np.sqrt(
            (dL / SL) ** 2
            + (dC / SC) ** 2
            + (dh / SH) ** 2
            + RT * (dC / SC) * (dh / SH)
        )

        update = dE < min_de
        min_de[update] = dE[update]
        best_rgb[update] = item["rgb"]
        best_idx[update] = idx

    return best_rgb, best_idx


def _mp_closest_color_chunk(pixels_chunk):
    """进程池 worker：处理一块像素。"""
    return _closest_color_vectorized_core(pixels_chunk)


def closest_color_vectorized(pixels, use_mp=None):
    """
    同时返回映射 RGB + 每个像素对应的 name 分段列表。
    use_mp: None 跟 MP_ENABLED；帧级并行内部应传 False 避免嵌套炸进程。
    """
    pixels = np.ascontiguousarray(np.asarray(pixels, dtype=np.uint8))
    total = pixels.shape[0]
    enable = MP_ENABLED if use_mp is None else bool(use_mp)
    workers = MP_WORKERS

    if (not enable) or workers <= 1 or total < MP_MIN_PIXELS:
        best_rgb, best_idx = _closest_color_vectorized_core(pixels)
    else:
        pixel_workers = max(1, min(workers, MP_PIXEL_WORKERS_CAP))
        n_chunks = min(pixel_workers, max(1, total // MP_MIN_CHUNK))
        chunks = [c for c in np.array_split(pixels, n_chunks) if len(c) > 0]
        if len(chunks) == 1:
            best_rgb, best_idx = _closest_color_vectorized_core(chunks[0])
        else:
            print(f"  像素并行: {total} px → {len(chunks)} 块 × {len(chunks)} 进程")
            with ProcessPoolExecutor(max_workers=len(chunks)) as ex:
                parts = list(ex.map(_mp_closest_color_chunk, chunks, chunksize=1))
            best_rgb = np.vstack([p[0] for p in parts])
            best_idx = np.concatenate([p[1] for p in parts])

    pixel_parts = [COLOR_TABLE[i]["name"] for i in best_idx]
    return best_rgb, pixel_parts

def resize_to_height(img, target_height):
    w, h = img.size
    scale = target_height / h
    new_width = int(round(w * scale))
    return img.resize((new_width, target_height), Image.Resampling.LANCZOS)


# ---------------------------------------------------------------------------
# Bayer dithering（有序抖动）
# ---------------------------------------------------------------------------
# 开关与参数可在 __main__ / process_media 中覆盖
DITHER_ENABLED = True
# 矩阵边长: "auto" | 2 | 4 | 8 | 16
DITHER_MATRIX_SIZE = "auto"
# 阈值振幅（0~255 量级）。None = 按矩阵尺寸自动 (约 256/n)
DITHER_STRENGTH = None

# 脏像素：相对「当前屏上显示」的 CIEDE2000 阈值
#   None / 0 → 严格相等（旧行为，dither 会把脏率顶很高）
#   float   → ΔE₀₀ ≥ 该值才写入 dirty
#   "auto"  → 按色板最近邻 ΔE 中位数自动取阈值（滤邻档/抖动，夹在 [5, 14]）
# 当前：手动抬高，进一步压脏率（慢变色会更「粘」）
DIRTY_CIEDE2000_THRESHOLD = 10.0


def _bayer_indices(n):
    """递归构造 n×n Bayer 下标矩阵（整数 0..n²-1），n 须为 2 的幂。"""
    if n < 1 or (n & (n - 1)) != 0:
        raise ValueError(f"Bayer 尺寸须为 2 的幂，收到: {n}")
    if n == 1:
        return np.array([[0]], dtype=np.float64)
    half = _bayer_indices(n // 2)
    return np.block(
        [
            [4 * half + 0, 4 * half + 2],
            [4 * half + 3, 4 * half + 1],
        ]
    )


def _build_bayer_matrix(n):
    """n×n Bayer，归一化到 (0,1)： (M + 0.5) / n²。"""
    m = _bayer_indices(n)
    return (m + 0.5) / float(n * n)


# 预生成常用尺寸
_BAYER_CACHE = {n: _build_bayer_matrix(n) for n in (2, 4, 8, 16)}


def select_bayer_size(height, width=None, override="auto"):
    """
    按处理分辨率选择 Bayer 矩阵边长。
    规则（取 max(h,w) 作为尺度）:
      ≤32  → 2×2
      ≤64  → 4×4
      ≤128 → 8×8
      >128 → 16×16
    override 为 2/4/8/16 时强制使用；"auto"/None 走自动。
    """
    if override is not None and override != "auto":
        n = int(override)
        if n not in _BAYER_CACHE:
            raise ValueError(f"不支持的 Bayer 尺寸: {n}，可选 2/4/8/16")
        return n
    scale = max(int(height), int(width if width is not None else height))
    if scale <= 32:
        return 2
    if scale <= 64:
        return 4
    if scale <= 128:
        return 8
    return 16


def apply_bayer_dither(arr, matrix_size=None, strength=None):
    """
    对 RGB uint8 图像做 Bayer 有序抖动（在量化到色板之前调用）。
    arr: (H,W,3) uint8
    matrix_size: 2/4/8/16，None 则按分辨率 auto
    strength: 阈值振幅；None 时用 256/n
    """
    h, w, _ = arr.shape
    n = matrix_size if matrix_size is not None else select_bayer_size(h, w, "auto")
    if n not in _BAYER_CACHE:
        _BAYER_CACHE[n] = _build_bayer_matrix(n)
    bayer = _BAYER_CACHE[n]
    if strength is None:
        strength = 256.0 / n

    # 平铺到整图，阈值映射到 [-0.5, 0.5) * strength
    tiles_y = (h + n - 1) // n
    tiles_x = (w + n - 1) // n
    tiled = np.tile(bayer, (tiles_y, tiles_x))[:h, :w]
    offset = (tiled - 0.5) * float(strength)

    out = arr.astype(np.float64) + offset[:, :, np.newaxis]
    return np.clip(out, 0, 255).astype(np.uint8)


def pixel_to_light_block(color_parts):
    """color_parts = [色系, 数字字符串] -> light_block id"""
    try:
        num = int(color_parts[1])
        return base_blocks[num - 1]
    except Exception:
        return base_blocks[-1]


def map_key_x(x):
    """行内列键 / 宏参数: 列 x 的字符串（如 "0","13"），与 $(0) 对应。"""
    return str(int(x))


def build_pixel_entries(h, w, pixel_parts):
    """兼容旧接口：仍返回 list compound（尽量少用）。优先 plain_to_frame_compound。"""
    entries = []
    for y in range(h):
        for x in range(w):
            color_parts = pixel_parts[y * w + x]
            entries.append(
                Compound({
                    "x": Int(x),
                    "y": Int(y),
                    "color": String(color_parts[0]),
                    "light_block": String(pixel_to_light_block(color_parts)),
                })
            )
    return List[Compound](entries)


def plain_to_frame_compound(plain_rows):
    """
    [(x,y,color,light_block), ...] → 全量帧 Compound（首帧 / 图片）:
      {
        full: 1b,
        rows: [
          { light_block: {"0": block, ...}, cushion_color: {"0": color, ...} },  # y=0
          ...
        ]
      }
    数据包按 rows[y] 逐行全量刷新 / summon。
    """
    by_y = {}
    max_y = -1
    for x, y, color, block in plain_rows:
        y = int(y)
        x = int(x)
        if y not in by_y:
            by_y[y] = ({}, {})
        k = map_key_x(x)
        by_y[y][0][k] = String(block)
        by_y[y][1][k] = String(color)
        if y > max_y:
            max_y = y
    rows = []
    for y in range(max_y + 1):
        light, colors = by_y.get(y, ({}, {}))
        rows.append(
            Compound(
                {
                    "light_block": Compound(light),
                    "cushion_color": Compound(colors),
                }
            )
        )
    return Compound({"full": Byte(1), "rows": List[Compound](rows)})


# (cushion_color, light_block) → 色板下标；以及成对 CIEDE2000 缓存
_PALETTE_KEY_TO_IDX = None
_PALETTE_DE_MATRIX = None  # (N,N) float64
_DIRTY_THR_RESOLVED = None  # 解析后的 float 阈值


def _ensure_palette_de_tables():
    """预计算色板键→下标 与 两两 CIEDE2000 矩阵。"""
    global _PALETTE_KEY_TO_IDX, _PALETTE_DE_MATRIX
    if _PALETTE_KEY_TO_IDX is not None and _PALETTE_DE_MATRIX is not None:
        return
    key_to_idx = {}
    labs = []
    for i, item in enumerate(COLOR_TABLE):
        parts = item["name"]
        c = str(parts[0])
        l = str(pixel_to_light_block(parts))
        key_to_idx[(c, l)] = i
        labs.append(item["lab"])
    n = len(labs)
    de = np.zeros((n, n), dtype=np.float64)
    for i in range(n):
        L1, a1, b1 = labs[i]
        for j in range(i + 1, n):
            L2, a2, b2 = labs[j]
            d = float(ciede2000(L1, a1, b1, L2, a2, b2))
            de[i, j] = d
            de[j, i] = d
    _PALETTE_KEY_TO_IDX = key_to_idx
    _PALETTE_DE_MATRIX = de


def resolve_dirty_ciede_threshold(override=None):
    """
    解析脏像素 ΔE 阈值。
    override / DIRTY_CIEDE2000_THRESHOLD:
      None/0/False → 0（严格匹配）
      "auto" → 色板最近邻 ΔE 中位数 × 1.25，夹在 [5, 14]
               （邻档抖动常见 < 该值；明显色变通常更大）
      float → 原样使用
    """
    global _DIRTY_THR_RESOLVED
    raw = DIRTY_CIEDE2000_THRESHOLD if override is None else override
    if raw is None or raw is False or raw == 0 or raw == 0.0:
        _DIRTY_THR_RESOLVED = 0.0
        return 0.0
    if isinstance(raw, str) and raw.lower() == "auto":
        _ensure_palette_de_tables()
        de = _PALETTE_DE_MATRIX
        # 每个色的最近邻（不含自身）
        nn = []
        n = de.shape[0]
        for i in range(n):
            row = de[i].copy()
            row[i] = np.inf
            nn.append(float(np.min(row)))
        med = float(np.median(nn)) if nn else 6.0
        # 中位最近邻往往就是「同色系相邻亮度/相邻色」——乘 1.25 压掉 dither 邻档跳变
        thr = max(5.0, min(14.0, med * 1.25))
        _DIRTY_THR_RESOLVED = thr
        return thr
    thr = float(raw)
    _DIRTY_THR_RESOLVED = thr
    return thr


def palette_delta_e(c1, l1, c2, l2):
    """两色板项 (color, light_block) 的 CIEDE2000；未知键返回 +inf。"""
    _ensure_palette_de_tables()
    i = _PALETTE_KEY_TO_IDX.get((str(c1), str(l1)))
    j = _PALETTE_KEY_TO_IDX.get((str(c2), str(l2)))
    if i is None or j is None:
        return float("inf")
    if i == j:
        return 0.0
    return float(_PALETTE_DE_MATRIX[i, j])


def plain_to_dirty_compound(plain_rows, displayed_plain_rows, threshold=None):
    """
    相对「屏上当前显示」的脏像素列表（非简单与上一编码帧比）:
      {
        full: 0b,
        d: [ {x, y, l: light_block, c: color}, ... ]
      }
    判定:
      - threshold<=0: color 或 light 字符串任一不同 → 脏
      - threshold>0: 两色板 CIEDE2000 ≥ threshold → 脏（小抖动/邻档不算）
    返回 (compound, new_displayed_plain)。
    new_displayed 仅在脏像素处更新为当前值，保证误差不跨帧漂移。
    """
    thr = resolve_dirty_ciede_threshold(threshold)
    disp = {
        (int(x), int(y)): (str(c), str(b)) for x, y, c, b in displayed_plain_rows
    }
    changes = []
    new_displayed = []
    for x, y, color, block in plain_rows:
        x, y = int(x), int(y)
        c, b = str(color), str(block)
        old = disp.get((x, y))
        dirty = False
        if old is None:
            dirty = True
        elif old[0] == c and old[1] == b:
            dirty = False
        elif thr <= 0:
            dirty = True
        else:
            de = palette_delta_e(old[0], old[1], c, b)
            dirty = de >= thr
        if dirty:
            changes.append(
                Compound(
                    {
                        "x": Int(x),
                        "y": Int(y),
                        "l": String(b),
                        "c": String(c),
                    }
                )
            )
            new_displayed.append((x, y, c, b))
        else:
            # 保持屏上已显示值
            oc, ob = old if old is not None else (c, b)
            new_displayed.append((x, y, oc, ob))
    return (
        Compound({"full": Byte(0), "d": List[Compound](changes)}),
        new_displayed,
    )


def frames_to_cache_list(frame_compounds):
    """[frame0, frame1, ...] → nbtlib List[Compound]"""
    return List[Compound](list(frame_compounds))


def ensure_parent_dir(path):
    """创建 path 的上游目录（含多级）；path 可为文件或目录目标。"""
    path = Path(path)
    # 若调用方传入的是目录语义且尚不存在，仍只建 parent 不够——
    # 约定：传入的是「将要写入的文件路径」，建 parent 即可。
    parent = path.parent
    if parent and str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    return path


def load_or_create_storage(dat_path, data_version=5003):
    """加载已有 command_storage.dat，或创建空结构（用于 merge）。"""
    dat_path = ensure_parent_dir(dat_path)

    if dat_path.is_file():
        nbt = nbt_load(str(dat_path))
        data = nbt.get("data", Compound())
        contents = data.get("contents", Compound())
        cache = contents.get("cache", Compound())
    else:
        nbt = File()
        data = Compound()
        contents = Compound()
        cache = Compound()

    return nbt, data, contents, cache


def storage_backup_path(dat_path=None):
    """
    唯一缓存路径（始终只有这一份文件）。
    默认: <dat 同目录>/command_storage.last.dat
    """
    if dat_path is None:
        base = Path(__file__).resolve().parent / "data" / "cs"
    else:
        base = Path(dat_path).resolve().parent
    return base / STORAGE_BACKUP_NAME


def atomic_replace_file(src, dst, retries=12, delay_sec=0.5):
    """
    将 src 原子替换为 dst（os.replace）。
    Windows 上若 Minecraft 打开了 command_storage.dat，会 PermissionError [WinError 5]；
    自动重试；仍失败则抛出带中文说明的 PermissionError，并保留 src 不删。
    """
    import time as _time

    src = Path(src)
    dst = ensure_parent_dir(dst)
    last_err = None
    for attempt in range(1, max(1, int(retries)) + 1):
        try:
            os.replace(str(src), str(dst))
            return dst
        except PermissionError as e:
            last_err = e
            print(
                f"写入被占用（第 {attempt}/{retries} 次）: {dst.name} — "
                f"请退出世界或关闭游戏后重试…"
            )
            _time.sleep(float(delay_sec) * attempt)
        except OSError as e:
            # 偶发 Sharing violation 等也重试
            win = getattr(e, "winerror", None)
            if win in (5, 32) or isinstance(e, PermissionError):
                last_err = e
                print(
                    f"写入被占用（第 {attempt}/{retries} 次）: {dst.name} ({e})"
                )
                _time.sleep(float(delay_sec) * attempt)
            else:
                raise
    raise PermissionError(
        f"无法覆盖 {dst}（文件被占用）。\n"
        f"常见原因：Minecraft 正在使用该存档的 command_storage.dat。\n"
        f"请先「退出世界」或关闭游戏，再重新处理 / 点恢复。\n"
        f"未覆盖的新文件仍在: {src}\n"
        f"原始错误: {last_err}"
    ) from last_err


def save_nbt_atomic(nbt_file, dat_path, data_version=None):
    """nbt File → 先写 .tmp，再 atomic replace 到 dat_path。"""
    dat_path = ensure_parent_dir(dat_path)
    if data_version is not None:
        nbt_file["DataVersion"] = Int(data_version)
    tmp = Path(str(dat_path) + ".tmp")
    ensure_parent_dir(tmp)
    nbt_file.save(str(tmp), gzipped=True)
    atomic_replace_file(tmp, dat_path)
    return dat_path


def save_storage_backup(dat_path, backup_path=None):
    """
    将当前 command_storage.dat 覆盖写入唯一缓存。
    使用临时文件 + replace，尽量避免写一半损坏。
    """
    dat_path = Path(dat_path)
    backup_path = Path(backup_path) if backup_path else storage_backup_path(dat_path)
    if not dat_path.is_file():
        raise FileNotFoundError(f"无法备份，dat 不存在: {dat_path}")

    ensure_parent_dir(backup_path)
    tmp_path = backup_path.with_name(backup_path.name + ".tmp")
    try:
        ensure_parent_dir(tmp_path)
        shutil.copy2(dat_path, tmp_path)
        atomic_replace_file(tmp_path, backup_path, retries=6, delay_sec=0.3)
    finally:
        if tmp_path.is_file():
            try:
                tmp_path.unlink()
            except OSError:
                pass

    size = backup_path.stat().st_size
    print(f"已更新唯一缓存（覆盖）: {backup_path}  ({size:,} bytes)")
    return backup_path


def restore_storage_from_backup(dat_path=None, backup_path=None):
    """
    从唯一缓存快速恢复 command_storage.dat（覆盖 dat）。
    用法:
      python cushion_screen.py restore
      或 restore_storage_from_backup()
    """
    if dat_path is None:
        dat_path = Path(__file__).resolve().parent / "data" / "cs" / "command_storage.dat"
    dat_path = Path(dat_path)
    backup_path = Path(backup_path) if backup_path else storage_backup_path(dat_path)

    if not backup_path.is_file():
        raise FileNotFoundError(
            f"没有可用缓存: {backup_path}\n"
            f"请先成功跑完一轮处理（会自动生成）。"
        )

    # 校验缓存能被 nbtlib 读开
    try:
        nbt = nbt_load(str(backup_path))
        n_keys = len(nbt.get("data", {}).get("contents", {}).get("cache", {}))
    except Exception as e:
        raise RuntimeError(f"缓存损坏，无法恢复: {backup_path} ({e})") from e

    ensure_parent_dir(dat_path)
    tmp_path = dat_path.with_name(dat_path.name + ".restore_tmp")
    try:
        ensure_parent_dir(tmp_path)
        shutil.copy2(backup_path, tmp_path)
        atomic_replace_file(tmp_path, dat_path, retries=10, delay_sec=0.5)
    finally:
        if tmp_path.is_file():
            try:
                tmp_path.unlink()
            except OSError:
                pass

    print(
        f"已从缓存恢复 dat:\n"
        f"  缓存: {backup_path} ({backup_path.stat().st_size:,} bytes, {n_keys} sources)\n"
        f"  写入: {dat_path} ({dat_path.stat().st_size:,} bytes)\n"
        f"提示: 请在游戏关闭或退出世界后再恢复，否则可能再次被覆盖。"
    )
    return dat_path


def merge_cache_entries(dat_path, entries, data_version=5003, backup=None):
    """
    将多组 cache 条目 merge 进 command_storage.dat（不删除其它 source）。
    entries: { source_name: List[Compound] 帧列表 }
    结构:
      cache.<source_name> = [
        # 全量帧（图片 / 视频第 0 帧）
        { full:1b, rows:[ {light_block:{x:block}, cushion_color:{x:color}}, ... ] },
        # 后续脏帧
        { full:0b, d:[ {x,y,l,c}, ... ] },
        ...
      ]
    """
    nbt, data, contents, cache = load_or_create_storage(dat_path, data_version)
    for source_name, frame_list in entries.items():
        cache[source_name] = frame_list
    contents["cache"] = cache
    data["contents"] = contents
    nbt["data"] = data
    nbt["DataVersion"] = Int(data_version)
    save_nbt_atomic(nbt, dat_path, data_version=data_version)

    do_backup = AUTO_BACKUP_AFTER_WRITE if backup is None else bool(backup)
    if do_backup:
        try:
            save_storage_backup(dat_path)
        except Exception as e:
            print(f"警告: 写入成功但缓存备份失败: {e}")

    return nbt


def write_command_storage(dat_path, source_name, frame_list, data_version=5003, backup=None):
    """写入/合并 cache.<source_name> = [帧, ...]。"""
    return merge_cache_entries(
        dat_path,
        {source_name: frame_list},
        data_version=data_version,
        backup=backup,
    )


def image_to_pixel_list(
    img,
    dither=None,
    dither_matrix_size=None,
    dither_strength=None,
    use_mp=None,
):
    """
    配色映射 → (mapped_rgb, pixel_list, h, w)。
    dither: None 用全局 DITHER_ENABLED；True/False 覆盖。
    dither_matrix_size: None 用全局 DITHER_MATRIX_SIZE（"auto"|2|4|8|16）。
    dither_strength: None 用全局 DITHER_STRENGTH。
    use_mp: 是否像素级多进程；帧并行时请传 False。
    """
    arr = np.asarray(img, dtype=np.uint8)
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    h, w, _ = arr.shape

    use_dither = DITHER_ENABLED if dither is None else bool(dither)
    size_opt = DITHER_MATRIX_SIZE if dither_matrix_size is None else dither_matrix_size
    strength = DITHER_STRENGTH if dither_strength is None else dither_strength

    if use_dither:
        n = select_bayer_size(h, w, override=size_opt)
        arr = apply_bayer_dither(arr, matrix_size=n, strength=strength)
        amp = (256.0 / n) if strength is None else float(strength)
        print(f"  Bayer dither: {n}×{n}  strength={amp:.1f}  (res {w}×{h})")

    mapped_rgb, pixel_parts = closest_color_vectorized(
        arr.reshape(-1, 3), use_mp=use_mp
    )
    pixel_list = build_pixel_entries(h, w, pixel_parts)
    return mapped_rgb.reshape(h, w, 3), pixel_list, h, w


def plain_pixels_to_nbt(plain_rows):
    """兼容旧名：现返回单帧 map compound（不是 list of pixels）。"""
    return plain_to_frame_compound(plain_rows)


def pixel_parts_to_plain(h, w, pixel_parts):
    """配色结果 → [(x,y,color,light_block), ...]（轻量，尚未建 NBT Compound）。"""
    rows = []
    for y in range(int(h)):
        for x in range(int(w)):
            cp = pixel_parts[y * w + x]
            rows.append(
                (x, y, str(cp[0]), pixel_to_light_block(cp))
            )
    return rows


def _image_to_plain_rows(
    img,
    dither=None,
    dither_matrix_size=None,
    dither_strength=None,
    use_mp=None,
):
    """配色 → (mapped_rgb, plain_rows, h, w)，不建 NBT。"""
    arr = np.asarray(img, dtype=np.uint8)
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    h, w, _ = arr.shape

    use_dither = DITHER_ENABLED if dither is None else bool(dither)
    size_opt = DITHER_MATRIX_SIZE if dither_matrix_size is None else dither_matrix_size
    strength = DITHER_STRENGTH if dither_strength is None else dither_strength

    if use_dither:
        n = select_bayer_size(h, w, override=size_opt)
        arr = apply_bayer_dither(arr, matrix_size=n, strength=strength)
        amp = (256.0 / n) if strength is None else float(strength)
        print(f"  Bayer dither: {n}×{n}  strength={amp:.1f}  (res {w}×{h})")

    mapped_rgb, pixel_parts = closest_color_vectorized(
        arr.reshape(-1, 3), use_mp=use_mp
    )
    plain = pixel_parts_to_plain(h, w, pixel_parts)
    return mapped_rgb.reshape(h, w, 3), plain, h, w


def _mp_process_frame_job(job):
    """
    视频帧 worker（模块级，供 Windows spawn 序列化）。
    job: (frame_idx, rgb_uint8_hwc, dither, matrix_size, strength)
    返回: (frame_idx, mapped_rgb, plain_rows, h, w)
    映射/展开在 Python 完成；落盘为 pixels[]，数据包只负责放置。
    """
    frame_idx, rgb, dither, matrix_size, strength = job
    mapped_rgb, plain, h, w = _image_to_plain_rows(
        rgb,
        dither=dither,
        dither_matrix_size=matrix_size,
        dither_strength=strength,
        use_mp=False,
    )
    return frame_idx, mapped_rgb, plain, h, w


def rebuild_palette_image(
    img,
    source_name,
    output_img_path="./palette_out.png",
    dat_path="./data/cs/command_storage.dat",
    data_version=5003,
    dither=None,
    dither_matrix_size=None,
    dither_strength=None,
    progress_callback=None,
):
    """
    单帧/图片 → merge 进 storage：
      cache.<source_name> = [ { rows: [ {light_block, cushion_color}, ... ] } ]
    并生成 cs:baked/p{W}x{H}（按行）+ cs:baked/src/<source_name>
    """
    import time as _time

    t0 = _time.perf_counter()

    def report(phase, current, total, message=""):
        if progress_callback is None:
            return
        elapsed = _time.perf_counter() - t0
        percent = 100.0 * float(current) / float(total) if total else None
        eta = None
        if total and current > 0 and current < total:
            eta = elapsed / float(current) * float(total - current)
        elif total and current >= total:
            eta = 0.0
        try:
            progress_callback(
                {
                    "phase": phase,
                    "current": int(current),
                    "total": int(total) if total else None,
                    "percent": percent,
                    "elapsed": elapsed,
                    "eta_seconds": eta,
                    "message": message,
                }
            )
        except Exception:
            pass

    print(f"正在处理图片 source={source_name} ...")
    report("color", 1, 4, "配色映射中…")
    mapped_rgb, plain, h, w = _image_to_plain_rows(
        img,
        dither=dither,
        dither_matrix_size=dither_matrix_size,
        dither_strength=dither_strength,
    )
    frame = plain_to_frame_compound(plain)
    print(f"  尺寸 {w} × {h}，像素 {len(plain)}")

    report("preview", 2, 4, "保存预览…")
    if output_img_path:
        ensure_parent_dir(output_img_path)
        Image.fromarray(mapped_rgb).save(output_img_path)
        print(f"配色贴图已保存：{output_img_path}")

    report("write", 3, 4, "写入 storage…")
    nbt = write_command_storage(
        dat_path,
        source_name,
        frames_to_cache_list([frame]),
        data_version=data_version,
    )
    print(
        f"command_storage 已 merge：{dat_path}\n"
        f"  storage: cs:cache  路径: {source_name}[0]  full+rows（图片全量）"
    )

    report("bake", 3, 4, "生成数据包扁平模板…")
    try:
        from bake_test_video_play import bake_for_media

        info = bake_for_media(
            width=w, height=h, source_name=source_name, n_frames=1, is_video=False
        )
        print(f"  数据包: /function {info['show']}")
    except Exception as e:
        print(f"警告: 自动 bake 数据包失败: {e}")

    report("done", 4, 4, "处理完成")
    return nbt


# ---------------------------------------------------------------------------
# 媒体类型检测 + 视频处理（帧命名与 play API 一致: <video_name>_f<timestamp>）
# ---------------------------------------------------------------------------

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
_VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".wmv", ".m4v"}


def detect_media_kind(path):
    """
    根据文件头（魔数）判断 image / video；魔数不明时回退扩展名。
    返回: "image" | "video"
    """
    path = Path(path)
    head = b""
    with open(path, "rb") as f:
        head = f.read(32)

    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    if head.startswith(b"\xff\xd8\xff"):
        return "image"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image"
    if head.startswith(b"BM"):
        return "image"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image"

    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "video"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "video"

    ext = path.suffix.lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _VIDEO_EXTS:
        return "video"
    raise ValueError(f"无法识别媒体类型: {path} (header={head[:16]!r})")


def video_frame_source_name(video_name, frame_index):
    """与数据包 API 一致: <video_name>_f<timestamp>"""
    return f"{video_name}_f{frame_index}"


def compute_video_sample_plan(origin_fps, total_frames, target_fps=None):
    """
    计算时间轴均匀采样计划，使「按 use_fps 播放」时长 ≈ 原片时长。

    旧逻辑: skip = round(origin/target)，30→20 变成 skip=2、use_fps=15，
    帧数 ≈ N/2，若仍按 20fps 播会偏短。

    新逻辑:
      duration = total_frames / origin_fps
      use_fps  = min(target_fps, origin_fps)（不过采样）
      n_out   = round(duration * use_fps)   → n_out/use_fps ≈ duration
      src[i]  = round(i * origin_fps / use_fps) 夹到 [0, total-1]
      末帧强制对齐片尾。

    返回 dict:
      origin_fps, total_frames, duration_src, use_fps, n_out,
      src_indices (len=n_out), postpone_ticks, duration_play,
      ratio (origin/use，仅日志), mode ("all"|"timed")
    """
    origin_fps = float(origin_fps) if origin_fps and origin_fps > 0 else 30.0
    total_frames = max(0, int(total_frames))
    duration_src = (total_frames / origin_fps) if total_frames > 0 else 0.0

    if total_frames <= 0:
        return {
            "origin_fps": origin_fps,
            "total_frames": 0,
            "duration_src": 0.0,
            "use_fps": origin_fps,
            "n_out": 0,
            "src_indices": [],
            "postpone_ticks": max(1, int(round(20.0 / origin_fps))),
            "duration_play": 0.0,
            "ratio": 1.0,
            "mode": "all",
        }

    # 目标帧率无效或 ≥ 源帧率 → 全帧，播放 fps = 源 fps
    if target_fps is None or float(target_fps) <= 0 or float(target_fps) >= origin_fps - 1e-9:
        use_fps = origin_fps
        src_indices = list(range(total_frames))
        n_out = total_frames
        mode = "all"
        ratio = 1.0
    else:
        use_fps = float(target_fps)
        # 保证 n_out / use_fps ≈ duration_src
        n_out = max(1, int(round(duration_src * use_fps)))
        src_indices = []
        for i in range(n_out):
            # 第 i 个采样点对应源时间 i/use_fps
            src = int(round(i * origin_fps / use_fps))
            if src < 0:
                src = 0
            if src >= total_frames:
                src = total_frames - 1
            src_indices.append(src)
        # 片尾对齐，避免 round 落不到最后一帧
        src_indices[-1] = total_frames - 1
        mode = "timed"
        ratio = origin_fps / use_fps

    postpone_ticks = max(1, int(round(20.0 / use_fps)))
    duration_play = n_out / use_fps if use_fps > 0 else 0.0
    # 游戏内按 tick 调度时的实际时长（postpone 取整后）
    duration_play_ticks = n_out * postpone_ticks / 20.0

    return {
        "origin_fps": origin_fps,
        "total_frames": total_frames,
        "duration_src": duration_src,
        "use_fps": use_fps,
        "n_out": n_out,
        "src_indices": src_indices,
        "postpone_ticks": postpone_ticks,
        "duration_play": duration_play,
        "duration_play_ticks": duration_play_ticks,
        "ratio": ratio,
        "mode": mode,
    }


def iter_sampled_video_frames(video_path, target_height, target_fps=None):
    """
    按时间轴均匀采样（非整除比也能对齐原片时长）。
    yield (frame_index, pil_rgb_scaled, use_fps, sample_ratio, origin_fps, total_frames, read_idx)
    sample_ratio = origin_fps/use_fps（日志用；不再是固定 skip 整数）
    """
    if cv2 is None:
        raise ImportError("处理视频需要 opencv-python，请先 pip install opencv-python-headless")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {video_path}")

    origin_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    plan = compute_video_sample_plan(origin_fps, total_frames, target_fps=target_fps)
    use_fps = plan["use_fps"]
    src_indices = plan["src_indices"]
    n_out = plan["n_out"]
    ratio = plan["ratio"]

    print(
        f"原始:{origin_fps:.3f}fps × {total_frames}帧  时长{plan['duration_src']:.3f}s\n"
        f"采样:{use_fps:.3f}fps × {n_out}帧  播放时长{plan['duration_play']:.3f}s"
        f"  (Δ={plan['duration_play'] - plan['duration_src']:+.4f}s)  "
        f"mode={plan['mode']}  ratio≈{ratio:.4f}\n"
        f"postpone:{plan['postpone_ticks']}t  "
        f"tick时长≈{plan['duration_play_ticks']:.3f}s"
    )

    if n_out <= 0:
        cap.release()
        return

    # 顺序解码：src_indices 单调不减；相同源帧复用，不重复解码
    read_idx = 0
    current_scaled = None
    last_decoded_src = -1
    try:
        for out_i, need_src in enumerate(src_indices):
            need_src = int(need_src)
            if need_src != last_decoded_src:
                while read_idx <= need_src:
                    ret, raw_bgr = cap.read()
                    if not ret:
                        break
                    if read_idx == need_src:
                        raw_rgb = cv2.cvtColor(raw_bgr, cv2.COLOR_BGR2RGB)
                        pil_img = Image.fromarray(raw_rgb)
                        current_scaled = resize_to_height(pil_img, target_height)
                        last_decoded_src = need_src
                    read_idx += 1
                # 元数据偏大读不到目标帧时，沿用最近一帧
                if last_decoded_src != need_src and current_scaled is None:
                    break
            if current_scaled is None:
                break
            yield (
                out_i,
                current_scaled,
                use_fps,
                ratio,
                origin_fps,
                total_frames,
                last_decoded_src if last_decoded_src >= 0 else need_src,
            )
    finally:
        cap.release()


def compute_video_batch_size(
    frame_w,
    frame_h,
    workers=None,
    pixel_budget=None,
    batch_override=None,
):
    """
    按任务参数动态分段大小：
      batch ≈ pixel_budget / (w*h)
    再夹在 [MP_VIDEO_BATCH_MIN, MP_VIDEO_BATCH_MAX]，并与 workers 协调。
    batch_override / MP_VIDEO_BATCH 为正整数时强制固定批大小。
    """
    override = batch_override if batch_override is not None else MP_VIDEO_BATCH
    if override is not None and int(override) > 0:
        return max(1, int(override))

    workers = max(1, int(workers if workers is not None else (MP_WORKERS if MP_ENABLED else 1)))
    budget = int(pixel_budget if pixel_budget is not None else MP_VIDEO_PIXEL_BUDGET)
    budget = max(1, budget)
    frame_pixels = max(1, int(frame_w) * int(frame_h))

    by_budget = max(1, budget // frame_pixels)
    # 批大小不必远超 worker 数（多了只是排队），但可略大于 worker 以填满管道
    by_workers = max(workers, min(by_budget, workers * 2))
    batch = min(by_budget, by_workers, MP_VIDEO_BATCH_MAX)
    batch = max(MP_VIDEO_BATCH_MIN, batch)
    return int(batch)


def estimate_sampled_frame_count(video_path, target_fps=None, max_frames=None):
    """预估采样后输出帧数（与 compute_video_sample_plan / iter 一致）。"""
    if cv2 is None:
        return None
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    origin_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    if total_frames <= 0:
        return None
    plan = compute_video_sample_plan(origin_fps, total_frames, target_fps=target_fps)
    est = int(plan["n_out"])
    if max_frames is not None:
        est = min(est, int(max_frames))
    return max(0, int(est))


def process_video_to_storage(
    video_path,
    video_name,
    target_height,
    dat_path,
    target_fps=None,
    preview_dir=None,
    data_version=5003,
    max_frames=None,
    dither=None,
    dither_matrix_size=None,
    dither_strength=None,
    progress_callback=None,
):
    """
    将视频帧写入 cs:cache.<video_name> = [帧0, 帧1, ...]
    帧0（全量）: { full:1b, rows:[...] }
    帧t>0（脏）: { full:0b, d:[ {x,y,l,c}, ... ] }  相对上一帧变化的像素
    并自动 bake: cs:baked/p{W}x{H} + dirty 应用 + cs:baked/<video_name>/play

    流式解码；按分辨率/像素预算动态分段。
    progress_callback(dict): phase/current/total/percent/elapsed/eta_seconds/message
    """
    import time as _time

    video_path = Path(video_path)
    dat_path = ensure_parent_dir(dat_path)
    if preview_dir is not None:
        preview_dir = Path(preview_dir)
        preview_dir.mkdir(parents=True, exist_ok=True)

    use_dither = DITHER_ENABLED if dither is None else bool(dither)
    size_opt = DITHER_MATRIX_SIZE if dither_matrix_size is None else dither_matrix_size
    strength = DITHER_STRENGTH if dither_strength is None else dither_strength

    workers = MP_WORKERS if MP_ENABLED else 1
    # 首帧解码后再按真实 w×h 定 batch；此前用 target_height 粗估
    est_w = max(1, int(round(target_height * 16 / 9)))
    batch_size = compute_video_batch_size(est_w, target_height, workers=workers)
    batch_locked = MP_VIDEO_BATCH is not None and int(MP_VIDEO_BATCH) > 0
    print(
        f"视频分段写入: workers≤{workers}, "
        f"batch≈{batch_size}（{'固定' if batch_locked else '待首帧校准'}）, "
        f"pixel_budget={MP_VIDEO_PIXEL_BUDGET}"
    )

    total_est = estimate_sampled_frame_count(
        video_path, target_fps=target_fps, max_frames=max_frames
    )
    t0 = _time.perf_counter()

    def report(phase, current, total, message=""):
        if progress_callback is None:
            return
        elapsed = _time.perf_counter() - t0
        total = total if total and total > 0 else None
        percent = None
        eta = None
        if total:
            percent = max(0.0, min(100.0, 100.0 * float(current) / float(total)))
            if current > 0 and current < total:
                eta = elapsed / float(current) * float(total - current)
            elif current >= total:
                eta = 0.0
        try:
            progress_callback(
                {
                    "phase": phase,
                    "current": int(current),
                    "total": int(total) if total is not None else None,
                    "percent": percent,
                    "elapsed": elapsed,
                    "eta_seconds": eta,
                    "message": message,
                }
            )
        except Exception:
            pass

    report("init", 0, total_est or 0, "准备处理视频…")

    last_idx = -1
    use_fps = None
    origin_fps = None
    total_frames = None
    total_done = 0
    batch_jobs = []
    cancelled = False

    # 全程内存维护 NBT；帧写入 cache.<video_name> 列表。
    # 旧 dat 若很大，nbtlib 全量 load 会极慢 → 超阈值则跳过加载。
    prefix_legacy = f"{video_name}_f"
    nbt_live = File()
    data_live = Compound()
    contents_live = Compound()
    cache_live = Compound()
    frame_compounds = {}  # frame_idx -> Compound
    frame_w = None
    frame_h = None
    dat_size = dat_path.stat().st_size if dat_path.is_file() else 0

    if dat_path.is_file() and dat_size > 0:
        size_mb = dat_size / (1024 * 1024)
        if dat_size > VIDEO_SKIP_LOAD_DAT_BYTES:
            report(
                "init",
                0,
                total_est or 0,
                f"旧 dat 较大（{size_mb:.1f}MB），备份后跳过加载以免卡死…",
            )
            print(
                f"旧 dat {dat_path} 约 {size_mb:.1f}MB，"
                f"超过 {VIDEO_SKIP_LOAD_DAT_BYTES // 1000}KB 阈值，跳过 nbtlib 全量加载"
            )
            try:
                save_storage_backup(dat_path)
                print("已把旧 dat 备份到 command_storage.last.dat（可用网页恢复）")
            except Exception as e:
                print(f"警告: 备份旧 dat 失败: {e}")
            report(
                "init",
                0,
                total_est or 0,
                f"已跳过加载旧 dat（{size_mb:.1f}MB）。本次只写本视频；其它 source 需重处理或从缓存恢复",
            )
        else:
            report(
                "init",
                0,
                total_est or 0,
                f"正在加载 storage（{size_mb:.2f}MB）…",
            )
            t_load = _time.perf_counter()
            try:
                nbt_live, data_live, contents_live, cache_live = load_or_create_storage(
                    dat_path, data_version
                )
                print(f"storage 加载完成  ({_time.perf_counter() - t_load:.1f}s)")
            except Exception as e:
                print(f"原 dat 无法加载({e})，使用空 storage")
                nbt_live = File()
                data_live = Compound()
                contents_live = Compound()
                cache_live = Compound()
            removed = [
                k
                for k in list(cache_live.keys())
                if str(k) == video_name or str(k).startswith(prefix_legacy)
            ]
            for k in removed:
                del cache_live[k]
            if removed:
                print(f"已清除旧条目 {len(removed)} 条 ({video_name} / {prefix_legacy}*)")
            report(
                "init",
                0,
                total_est or 0,
                f"storage 就绪（已清 {len(removed)} 条旧条目）",
            )
    else:
        report("init", 0, total_est or 0, "无旧 dat，使用空 storage")

    dirty_thr = resolve_dirty_ciede_threshold()
    print(
        "视频帧存储: [0]=full+rows；[t>0]=dirty d[{x,y,l,c}]  "
        f"相对屏上显示  CIEDE2000≥{dirty_thr:.2f}"
        + (" (auto)" if str(DIRTY_CIEDE2000_THRESHOLD).lower() == "auto" else "")
    )

    # 进程池延迟到首批配色再创建（避免 init 阶段就 spawn 一堆进程）
    pool = None
    dirty = False
    frames_since_save = 0
    displayed_plain = None  # 屏上当前状态（脏更新后的累积显示）
    dirty_px_total = 0
    full_px_total = 0
    # 大任务才中途落盘；小任务攒到结束一次写完
    checkpoint_every = 80

    def save_live(do_backup=False):
        nonlocal dirty, frames_since_save
        if not dirty and not do_backup:
            return
        t_save = _time.perf_counter()
        report("write", total_done, total_est or total_done, "正在写入 dat…")
        if frame_compounds:
            n = max(frame_compounds.keys()) + 1
            ordered = []
            empty = Compound({"full": Byte(0), "d": List[Compound]([])})
            for i in range(n):
                ordered.append(frame_compounds.get(i, empty))
            cache_live[video_name] = frames_to_cache_list(ordered)
        contents_live["cache"] = cache_live
        data_live["contents"] = contents_live
        nbt_live["data"] = data_live
        nbt_live["DataVersion"] = Int(data_version)
        tmp = Path(str(dat_path) + ".tmp")
        try:
            ensure_parent_dir(dat_path)
            ensure_parent_dir(tmp)
            nbt_live.save(str(tmp), gzipped=True)
            atomic_replace_file(tmp, dat_path, retries=12, delay_sec=0.5)
        except PermissionError as e:
            # 结果已在 .tmp；尽量再拷一份到 last.dat，避免白跑
            try:
                if tmp.is_file():
                    bp = storage_backup_path(dat_path)
                    ensure_parent_dir(bp)
                    shutil.copy2(tmp, bp)
                    print(f"主 dat 被占用，已把结果另存到缓存: {bp}")
            except Exception as e2:
                print(f"另存缓存也失败: {e2}")
            report(
                "error",
                total_done,
                total_est or total_done,
                "写入 dat 被拒绝（文件被占用）。请退出世界后重试；结果可能在 .tmp / .last.dat",
            )
            raise
        dirty = False
        frames_since_save = 0
        print(f"落盘完成 → {dat_path}  ({_time.perf_counter() - t_save:.1f}s)")
        if do_backup:
            try:
                save_storage_backup(dat_path)
            except Exception as e:
                print(f"警告: 缓存备份失败: {e}")

    def flush_batch(jobs):
        nonlocal last_idx, total_done, dirty, frames_since_save, pool, frame_w, frame_h
        nonlocal displayed_plain, dirty_px_total, full_px_total
        if not jobs:
            return
        if cancel_requested():
            jobs.clear()
            return

        report(
            "color",
            total_done,
            total_est or max(total_done, 1),
            f"配色中（本批 {len(jobs)} 帧）…",
        )
        if workers > 1 and pool is None:
            report(
                "color",
                total_done,
                total_est or max(total_done, 1),
                f"启动 {workers} 个配色进程…",
            )
            pool = ProcessPoolExecutor(max_workers=workers)
        if pool is None:
            results = [_mp_process_frame_job(j) for j in jobs]
        else:
            results = list(pool.map(_mp_process_frame_job, jobs, chunksize=1))
        if cancel_requested():
            jobs.clear()
            return
        results.sort(key=lambda r: r[0])

        for frame_idx, mapped_rgb, plain, h, ww in results:
            frame_w, frame_h = int(ww), int(h)
            n_px = len(plain)
            if displayed_plain is None or frame_idx == 0:
                frame_compounds[frame_idx] = plain_to_frame_compound(plain)
                displayed_plain = list(plain)
                full_px_total += n_px
                kind = "full"
                n_dirty = n_px
            else:
                compound, displayed_plain = plain_to_dirty_compound(
                    plain, displayed_plain, threshold=dirty_thr
                )
                frame_compounds[frame_idx] = compound
                n_dirty = len(compound["d"])
                dirty_px_total += n_dirty
                kind = "dirty"
            last_idx = max(last_idx, frame_idx)
            total_done += 1
            frames_since_save += 1
            dirty = True
            if preview_dir is not None:
                Image.fromarray(mapped_rgb).save(
                    preview_dir / f"preview_{frame_idx:04d}.png"
                )
            ratio = (100.0 * n_dirty / n_px) if n_px else 0.0
            print(
                f"完成帧 {frame_idx} → cache.{video_name}[{frame_idx}] "
                f"{kind} {n_dirty}/{n_px} px ({ratio:.1f}%)  {ww}x{h}"
            )

        report(
            "color",
            total_done,
            total_est or total_done,
            f"已配色 {total_done}"
            + (f"/{total_est}" if total_est else "")
            + " 帧",
        )
        # 仅大任务中途检查点；小任务留给最终一次 write
        if frames_since_save >= checkpoint_every:
            save_live(do_backup=False)
        results.clear()
        jobs.clear()

    try:
        report("decode", 0, total_est or 0, "打开视频并开始解码…")
        for frame_idx, scaled, use_fps, sample_ratio, origin_fps, total_frames, read_idx in iter_sampled_video_frames(
            video_path, target_height, target_fps=target_fps
        ):
            if cancel_requested():
                cancelled = True
                break
            if max_frames is not None and frame_idx >= max_frames:
                break
            rgb = np.ascontiguousarray(np.array(scaled, dtype=np.uint8))
            if frame_idx == 0 and not batch_locked:
                fh, fw = int(rgb.shape[0]), int(rgb.shape[1])
                batch_size = compute_video_batch_size(fw, fh, workers=workers)
                print(
                    f"动态分段: {fw}×{fh} = {fw * fh} px/帧 → batch={batch_size} "
                    f"(budget={MP_VIDEO_PIXEL_BUDGET}, workers={workers})"
                )
            batch_jobs.append((frame_idx, rgb, use_dither, size_opt, strength))
            print(
                f"解码帧 {frame_idx} | 源帧 {read_idx}/{total_frames} | "
                f"{rgb.shape[1]}x{rgb.shape[0]}  ({len(batch_jobs)}/{batch_size})"
            )
            report(
                "decode",
                frame_idx + 1,
                total_est or (frame_idx + 1),
                f"解码帧 {frame_idx}",
            )
            if len(batch_jobs) >= batch_size:
                flush_batch(batch_jobs)
                batch_jobs = []
                if cancel_requested():
                    cancelled = True
                    break

        if not cancelled:
            flush_batch(batch_jobs)
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=False)

    if cancelled:
        batch_jobs.clear()
        try:
            if dirty:
                save_live(do_backup=total_done > 0)
        except Exception as e:
            print(f"警告: 取消后落盘失败: {e}")
        report(
            "cancelled",
            total_done,
            total_est or total_done,
            f"已取消（已完成 {total_done} 帧）",
        )
        print(f"处理已取消，已完成 {total_done} 帧")
        raise ProcessingCancelled(f"用户取消（已完成 {total_done} 帧）")

    if last_idx < 0:
        raise RuntimeError(f"视频未采样到任何帧: {video_path}")

    print(f"全部 {total_done} 帧已处理，最终落盘并更新缓存 ...")
    try:
        save_live(do_backup=True)
    except Exception as e:
        print(f"警告: 最终落盘/缓存失败: {e}")
        raise

    postpone_ticks = max(1, int(round((1.0 / use_fps) * 20)))
    duration_play = (last_idx + 1) / use_fps if use_fps else 0.0
    # 与采样计划对照（用已处理帧数）
    duration_src = None
    try:
        if origin_fps and total_frames:
            duration_src = float(total_frames) / float(origin_fps)
    except Exception:
        duration_src = None
    result = {
        "frame_count": last_idx + 1,
        "max_time": last_idx,
        "use_fps": use_fps,
        "postpone_ticks": postpone_ticks,
        "dat_path": str(dat_path),
        "video_name": video_name,
        "width": frame_w,
        "height": frame_h,
        "duration_play": duration_play,
        "duration_src": duration_src,
        "origin_fps": origin_fps,
    }

    # 按真实分辨率 bake 两宏模板 + 播放入口
    if frame_w and frame_h:
        report("bake", total_done, total_done, "生成数据包两宏模板…")
        try:
            from bake_test_video_play import bake_for_media

            info = bake_for_media(
                width=frame_w,
                height=frame_h,
                source_name=video_name,
                n_frames=result["frame_count"],
                postpone=f"{postpone_ticks}t",
                is_video=True,
            )
            result["play_function"] = info.get("play")
            print(f"  数据包: /function {info['play']}")
        except Exception as e:
            print(f"警告: 自动 bake 数据包失败: {e}")

    report("done", total_done, total_done, "处理完成")
    play_hint = result.get("play_function") or f"cs:baked/{video_name}/play"
    delta_frames = max(0, total_done - 1)
    avg_dirty = (dirty_px_total / delta_frames) if delta_frames else 0.0
    px_frame = (frame_w * frame_h) if frame_w and frame_h else 0
    avg_ratio = (100.0 * avg_dirty / px_frame) if px_frame else 0.0
    result["dirty_px_total"] = dirty_px_total
    result["avg_dirty_px"] = avg_dirty
    dur_line = f"  播放时长: {duration_play:.3f}s @ {use_fps:.3f}fps"
    if duration_src is not None:
        dur_line += (
            f"  | 原片 {duration_src:.3f}s"
            f"  Δ={duration_play - duration_src:+.4f}s"
        )
    tick_dur = result["frame_count"] * postpone_ticks / 20.0
    print(
        f"\n视频写入完成\n"
        f"  帧数: {result['frame_count']}  (max_time={result['max_time']})\n"
        f"  尺寸: {frame_w}×{frame_h}\n"
        f"  输出帧率: {use_fps:.3f} fps  postpone: \"{postpone_ticks}t\""
        f"  (tick时长≈{tick_dur:.3f}s)\n"
        f"{dur_line}\n"
        f"  dirty: 后续帧共 {dirty_px_total:,} 脏像素"
        f"  均值 {avg_dirty:.0f}/{px_frame} ({avg_ratio:.1f}%)"
        f"  ΔE₀₀≥{dirty_thr:.2f}\n"
        f"  storage: [0]=full+rows  [t>0]=d[{{x,y,l,c}}]\n"
        f"  播放: /function {play_hint}"
    )
    return result



def process_media(
    input_path,
    *,
    source_name=None,
    target_height=128,
    target_fps=5,
    dat_path=None,
    preview_path_or_dir=None,
    data_version=5003,
    max_frames=None,
    dither=None,
    dither_matrix_size=None,
    dither_strength=None,
    progress_callback=None,
):
    """
    自动识别图片/视频并处理。
    - 图片 → cache.<source_name> = [ {full:1b, rows:[...]} ]
    - 视频 → [0]={full+rows}，[t>0]={full:0b, d:[脏像素]}
    并生成 cs:baked（全量按行 + dirty 逐像素宏）
    """
    input_path = Path(input_path)
    if dat_path is None:
        dat_path = Path(__file__).resolve().parent / "data" / "cs" / "command_storage.dat"
    dat_path = Path(dat_path)
    name = source_name or input_path.stem
    kind = detect_media_kind(input_path)
    print(f"输入: {input_path}  检测类型: {kind}")
    clear_cancel()

    if kind == "image":
        if cancel_requested():
            raise ProcessingCancelled("用户取消")
        raw = Image.open(input_path).convert("RGB")
        scaled = resize_to_height(raw, target_height)
        return rebuild_palette_image(
            scaled,
            source_name=name,
            output_img_path=preview_path_or_dir or f"{name}_preview.png",
            dat_path=dat_path,
            data_version=data_version,
            dither=dither,
            dither_matrix_size=dither_matrix_size,
            dither_strength=dither_strength,
            progress_callback=progress_callback,
        )

    preview_dir = preview_path_or_dir
    if preview_dir is None:
        preview_dir = Path(__file__).resolve().parent / f"{name}_previews"
    return process_video_to_storage(
        video_path=input_path,
        video_name=name,
        target_height=target_height,
        dat_path=dat_path,
        target_fps=target_fps,
        preview_dir=preview_dir,
        data_version=data_version,
        max_frames=max_frames,
        dither=dither,
        dither_matrix_size=dither_matrix_size,
        dither_strength=dither_strength,
        progress_callback=progress_callback,
    )


if __name__ == "__main__":
    # Windows 多进程需要此 guard
    DAT_PATH = Path(__file__).resolve().parent / "data" / "cs" / "command_storage.dat"

    # 快速修复：python cushion_screen.py restore
    if len(sys.argv) > 1 and sys.argv[1].lower() in ("restore", "--restore", "-r"):
        restore_storage_from_backup(DAT_PATH)
        sys.exit(0)

    # 图片或视频均可；按文件头自动分流
    INPUT_PATH = "test_video.mp4"
    SOURCE_NAME = Path(INPUT_PATH).stem  # test_video → test_video_f0, test_video_f1, ...
    TARGET_H = 64          # 与 video_version 默认一致；图片可改 128
    TARGET_FPS = 5         # 视频采样帧率；图片忽略
    DATA_VERSION = 5003
    # MAX_FRAMES = None    # 调试可设如 10，限制最多处理帧数
    MAX_FRAMES = None

    # ----- Bayer dither 开关 -----
    DITHER_ENABLED = True          # False 关闭抖动
    DITHER_MATRIX_SIZE = "auto"    # "auto" | 2 | 4 | 8 | 16
    DITHER_STRENGTH = None         # None=256/n；或手动如 32.0

    # ----- 脏像素 CIEDE2000 阈值（视频）-----
    # "auto" | float(ΔE₀₀) | 0=严格相等
    DIRTY_CIEDE2000_THRESHOLD = 10.0

    # ----- 多进程（见文件顶部 MP_ENABLED / MP_WORKERS）-----
    # import cushion_screen as cs; cs.MP_WORKERS = 8

    process_media(
        INPUT_PATH,
        source_name=SOURCE_NAME,
        target_height=TARGET_H,
        target_fps=TARGET_FPS,
        dat_path=DAT_PATH,
        data_version=DATA_VERSION,
        max_frames=MAX_FRAMES,
        dither=DITHER_ENABLED,
        dither_matrix_size=DITHER_MATRIX_SIZE,
        dither_strength=DITHER_STRENGTH,
    )