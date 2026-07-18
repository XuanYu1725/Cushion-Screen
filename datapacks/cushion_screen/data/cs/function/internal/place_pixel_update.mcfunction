# 更新单像素（宏参数: x y color light_block）
# 方块 Y=~0，坐垫 Y=~0.28

$setblock ~$(x) ~0 ~$(y) $(light_block)
$execute positioned ~$(x) ~0.28 ~$(y) run data merge entity @n[type=minecraft:cushion,distance=..0.3] {color:$(color)}
