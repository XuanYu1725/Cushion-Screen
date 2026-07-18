# 须在 cs_video_origin 处执行 (at @s)
# 优化：仅第 0 帧 kill+summon；之后只 setblock + data merge 改颜色

# 首帧：清掉旧画面实体，完整 get_frame（setblock + summon）
execute if score #time cs.video matches 0 run kill @e[type=minecraft:cushion,tag=cs_frame,distance=..512]
execute if score #time cs.video matches 0 run function cs:video/call_frame with storage cs:temp video

# 后续帧：保留实体，get_frame_update（setblock + data merge color）
execute unless score #time cs.video matches 0 run function cs:video/call_frame_update with storage cs:temp video
