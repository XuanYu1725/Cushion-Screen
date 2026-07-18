# 宏参数: i, x, y, source
# 从 cache.<source>.idx[i] 取调色板下标，再 apply

$data modify storage cs:temp compact.cur.x set value $(x)
$data modify storage cs:temp compact.cur.y set value $(y)
$data modify storage cs:temp compact.pi set from storage cs:cache $(source).idx[$(i)]
function cs:internal/compact/apply with storage cs:temp compact
