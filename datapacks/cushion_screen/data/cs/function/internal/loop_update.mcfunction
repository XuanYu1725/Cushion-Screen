# 递归消费 pixels[]，对每个像素执行 place_pixel_update（data merge 颜色）

execute unless data storage cs:temp get_frame.pixels[0] run return 0

data modify storage cs:temp get_frame.current set from storage cs:temp get_frame.pixels[0]
function cs:internal/place_pixel_update with storage cs:temp get_frame.current

data remove storage cs:temp get_frame.pixels[0]
function cs:internal/loop_update
