# 更新单像素（非首帧）：只改 light_block 与 cushion 颜色，不重新 summon
# 宏参数: x, y, color, light_block
# 选择器用 type + distance + limit 收窄范围（先 positioned 到像素点再查）

$setblock ~$(x) ~1 ~$(y) $(light_block)
$execute positioned ~$(x) ~1.28 ~$(y) run data merge entity @n[type=minecraft:cushion,distance=..0.3] {color:$(color)}
