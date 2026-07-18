# 宏参数: pi（调色板下标）
# 查 palette → place_pixel / place_pixel_update

$data modify storage cs:temp compact.cur.color set from storage cs:temp compact.palette_color[$(pi)]
$data modify storage cs:temp compact.cur.light_block set from storage cs:temp compact.palette_light[$(pi)]

execute if data storage cs:temp compact{mode:"summon"} run function cs:internal/place_pixel with storage cs:temp compact.cur
execute if data storage cs:temp compact{mode:"update"} run function cs:internal/place_pixel_update with storage cs:temp compact.cur
