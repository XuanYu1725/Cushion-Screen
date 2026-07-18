# cs:get_frame_update — 视频非首帧改色
# 新格式请用 cs:baked/<video>/play（内置 place_update）
# 此处仅兼容旧 .pixels

gamerule max_command_sequence_length 2147483647

$execute if data storage cs:cache $(source_name).pixels run return run function cs:internal/from_pixels_update {source_name:"$(source_name)"}
$execute if data storage cs:cache $(source_name).format run return run function cs:internal/compact/start_update {source_name:"$(source_name)"}

$tellraw @s [{"text":"[cs:get_frame_update] 旧格式未找到 ","color":"red"},{"text":"$(source_name)","color":"yellow"},{"text":" ；新格式请 /function cs:baked/<name>/play","color":"red"}]
