# 宏参数: x y l c u（来自 d[i]）
# setblock 必须用宏；坐垫用确定性 UUID 直达（无 @n 查询）
# u = {src_hash}-0-0-{x:x}-{y:x}

$execute positioned ~$(x) ~0 ~$(y) run setblock ~ ~ ~ $(l)
$data modify entity $(u) color set from storage cs:temp baked.p.c
