# 处理 d[#i]，然后 #i++
execute store result storage cs:temp baked.idx.i int 1 run scoreboard players get #i cs.video
function cs:baked/dirty/step with storage cs:temp baked.idx
scoreboard players add #i cs.video 1
