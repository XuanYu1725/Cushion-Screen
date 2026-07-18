execute if score #i cs.video >= #n cs.video run return 0
function cs:baked/dirty/pump
execute if score #i cs.video < #n cs.video run function cs:baked/dirty/loop
