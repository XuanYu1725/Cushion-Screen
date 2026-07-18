# 紧凑格式 compact_v1 放置入口（首帧 summon）
# 宏参数: source_name
# 结构: format,w,h,palette_color[],palette_light[],idx(IntArray)
# 只复制小 palette；idx 按下标从原 cache 读，避免 temp 再拷一份大数组

scoreboard objectives add cs.compact dummy

$data modify storage cs:temp compact.source set value "$(source_name)"
$data modify storage cs:temp compact.palette_color set from storage cs:cache $(source_name).palette_color
$data modify storage cs:temp compact.palette_light set from storage cs:cache $(source_name).palette_light

$execute store result score #w cs.compact run data get storage cs:cache $(source_name).w
$execute store result score #h cs.compact run data get storage cs:cache $(source_name).h
scoreboard players set #x cs.compact 0
scoreboard players set #y cs.compact 0
scoreboard players set #i cs.compact 0
scoreboard players operation #n cs.compact = #w cs.compact
scoreboard players operation #n cs.compact *= #h cs.compact

data modify storage cs:temp compact.mode set value "summon"

function cs:internal/compact/loop
