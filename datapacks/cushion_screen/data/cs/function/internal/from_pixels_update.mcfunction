# 旧格式非首帧: pixels[] → place_pixel_update
# 宏参数: source_name

$data modify storage cs:temp get_frame.pixels set from storage cs:cache $(source_name).pixels
data remove storage cs:temp get_frame.current
function cs:internal/loop_update
