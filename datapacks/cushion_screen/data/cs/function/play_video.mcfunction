# cs:play_video
# 【旧路径】依赖 cache.<name>_fN.pixels 列表。
# 新格式请用处理脚本自动生成的:
#   /function cs:baked/<video_name>/play
#   storage: cache.<video_name>[t].light_block / cushion_color
#
# 宏参数: video_name, max_time, postpone
# 用法（旧）:
#   /function cs:play_video {video_name:"demo", max_time:120, postpone:"1t"}
#
# 注意: schedule 不保留坐标，会在执行点召唤 marker 作为画面原点。

scoreboard objectives add cs.video dummy

# 运行时状态（schedule 无法携带宏参数）
$data modify storage cs:temp video.name set value "$(video_name)"
$data modify storage cs:temp video.postpone set value "$(postpone)"
$scoreboard players set #max cs.video $(max_time)

# 先置 -1，首轮 +1 后从 0 帧播到 max_time（含）
scoreboard players set #time cs.video -1
scoreboard players set #playing cs.video 1

# 固定播放原点：align 到方块角后，沿 +X/+Y/+Z 各走 0.5 到方块中心
kill @e[type=marker,tag=cs_video_origin]
execute align xyz positioned ~0.5 ~0.5 ~0.5 run summon marker ~ ~ ~ {Tags:["cs_video_origin"]}

# 打断上一次播放，避免多重 schedule
schedule clear cs:video/tick
function cs:video/schedule_next with storage cs:temp video

tellraw @s [{"text":"[cs:play_video] 开始播放 ","color":"green"},{"nbt":"video.name","storage":"cs:temp","color":"yellow"},{"text":"  帧 0..","color":"gray"},{"score":{"name":"#max","objective":"cs.video"},"color":"aqua"},{"text":"  postpone=","color":"gray"},{"nbt":"video.postpone","storage":"cs:temp","color":"aqua"}]
