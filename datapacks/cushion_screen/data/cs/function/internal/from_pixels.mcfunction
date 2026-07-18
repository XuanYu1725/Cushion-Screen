# 旧格式: cache.<source>.pixels[] → 临时列表 → place_pixel
# 宏参数: source_name

$data modify storage cs:temp get_frame.pixels set from storage cs:cache $(source_name).pixels
data remove storage cs:temp get_frame.current
function cs:internal/loop
