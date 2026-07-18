# cs:get_frame
# 宏参数: source_name
# 新格式: cache.<source> = [ { rows: [ {light_block, cushion_color}, ... ] }, ... ]
# 图片由处理脚本生成 cs:baked/src/<source>（按行 apply_summon）
# 兼容旧 .pixels 列表格式

gamerule random_tick_speed 0
gamerule max_command_sequence_length 2147483647

$execute if data storage cs:cache $(source_name)[0].rows[0] run return run function cs:baked/src/$(source_name)

$execute if data storage cs:cache $(source_name).pixels run return run function cs:internal/from_pixels {source_name:"$(source_name)"}
$execute if data storage cs:cache $(source_name).format run return run function cs:internal/compact/start {source_name:"$(source_name)"}

$tellraw @s [{"text":"[cs:get_frame] 未找到 ","color":"red"},{"text":"$(source_name)","color":"yellow"},{"text":" （需 [0].rows；请重新处理以生成 baked/src）","color":"red"}]
