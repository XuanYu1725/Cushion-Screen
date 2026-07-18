# 停止视频播放（tick 自动调用，或手动 /function cs:video/stop）

scoreboard players set #playing cs.video 0
schedule clear cs:video/tick
# 保留 marker / 最后一帧画面，便于定格查看；需要清屏可自行 kill

tellraw @a [{"text":"[cs:play_video] 播放结束","color":"gray"},{"text":" time=","color":"dark_gray"},{"score":{"name":"#time","objective":"cs.video"},"color":"dark_gray"},{"text":" max=","color":"dark_gray"},{"score":{"name":"#max","objective":"cs.video"},"color":"dark_gray"}]
