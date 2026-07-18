# 宏参数: x y l c（来自 d[i]）
# setblock 必须用宏；颜色从 cs:temp baked.p.c 读，避免 value 引号问题

$execute positioned ~$(x) ~0 ~$(y) run setblock ~ ~ ~ $(l)
$execute positioned ~$(x) ~0.28 ~$(y) run data modify entity @n[type=minecraft:cushion,tag=cs_frame,distance=..0.3] color set from storage cs:temp baked.p.c
