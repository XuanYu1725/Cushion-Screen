# 视频播放循环体：按 storage cs:temp video.postpone 自调度
# 依赖记分板 cs.video: #playing #time #max
# 依赖 storage cs:temp video.name / video.postpone
# 依赖 marker cs_video_origin 作为相对坐标原点

execute unless score #playing cs.video matches 1 run return 0
execute unless entity @e[type=marker,tag=cs_video_origin,limit=1] run return run function cs:video/stop

# 时间指针 +1
scoreboard players add #time cs.video 1

# 超过 max_time 则停止（不再 schedule）
execute if score #time cs.video > #max cs.video run return run function cs:video/stop

# 将当前时间写入 storage，供宏拼接 source_name = <name>_f<time>
execute store result storage cs:temp video.time int 1 run scoreboard players get #time cs.video

# 在原点处拉新帧（首帧 summon，之后 data merge 改色）
execute as @e[type=marker,tag=cs_video_origin,limit=1] at @s run function cs:video/draw_frame

# 按 postpone 延时继续下一帧
function cs:video/schedule_next with storage cs:temp video
