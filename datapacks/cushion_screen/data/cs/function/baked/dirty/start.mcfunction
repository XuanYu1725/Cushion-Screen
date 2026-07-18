# 依赖: cs:temp baked.frame 已是当前脏帧（full:0b, d:[...]）
# 在屏幕原点 at 执行

data modify storage cs:temp baked.d set from storage cs:temp baked.frame.d
execute store result score #n cs.video run data get storage cs:temp baked.d
execute if score #n cs.video matches 0 run return 0
scoreboard players set #i cs.video 0
function cs:baked/dirty/loop
