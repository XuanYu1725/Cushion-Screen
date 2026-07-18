# cs:get
# 宏参数: source_name
# 用法:
#   /function cs:get {source_name:"test_img"}
#
# 显式对齐执行点后再拉帧：
#   1. align xyz  → 当前所在方块角
#   2. +0.5/+0.5/+0.5 → 方块中心（与 play_video 原点一致）
#   3. function cs:get_frame

$execute align xyz positioned ~0.5 ~0.5 ~0.5 run function cs:get_frame {source_name:"$(source_name)"}
