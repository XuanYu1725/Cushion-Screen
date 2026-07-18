# 按 i=0..w*h-1 遍历；x/y 同步递增（row-major）
# 不 peel idx，O(n)；依赖 score #i #x #y #w #n cs.compact

execute if score #i cs.compact >= #n cs.compact run return 0

execute store result storage cs:temp compact.i int 1 run scoreboard players get #i cs.compact
execute store result storage cs:temp compact.x int 1 run scoreboard players get #x cs.compact
execute store result storage cs:temp compact.y int 1 run scoreboard players get #y cs.compact

function cs:internal/compact/place with storage cs:temp compact

scoreboard players add #i cs.compact 1
scoreboard players add #x cs.compact 1
execute if score #x cs.compact >= #w cs.compact run function cs:internal/compact/next_row

function cs:internal/compact/loop
