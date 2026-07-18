# 递归消费 cs:temp get_frame.pixels[0]
# 每个元素交给 place_pixel（函数宏）

execute unless data storage cs:temp get_frame.pixels[0] run return 0

data modify storage cs:temp get_frame.current set from storage cs:temp get_frame.pixels[0]
function cs:internal/place_pixel with storage cs:temp get_frame.current

data remove storage cs:temp get_frame.pixels[0]
function cs:internal/loop
