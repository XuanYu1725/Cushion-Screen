# 宏: i
$data modify storage cs:temp baked.p set from storage cs:temp baked.d[$(i)]
function cs:baked/dirty/apply with storage cs:temp baked.p
