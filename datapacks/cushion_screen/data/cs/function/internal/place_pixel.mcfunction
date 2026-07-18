# 放置单像素（宏参数: x y color light_block）
# 图 X → 世界 ~X，图 Y → 世界 ~Z；方块 Y=~0，坐垫 Y=~0.28（贴在方块上）

$setblock ~$(x) ~0 ~$(y) $(light_block)
$summon cushion ~$(x) ~0.28 ~$(y) {color:$(color),Tags:["cs_frame"]}
