# 放置单像素（函数宏）
# 宏参数来自 pixels[] 元素: x, y, color, light_block
# 坐标约定与原脚本一致: 图 X → 世界 ~X，图 Y → 世界 ~Z，高度固定 ~1 / ~1.28

$setblock ~$(x) ~1 ~$(y) $(light_block)
$summon cushion ~$(x) ~1.28 ~$(y) {color:$(color),Tags:["cs_frame"]}
