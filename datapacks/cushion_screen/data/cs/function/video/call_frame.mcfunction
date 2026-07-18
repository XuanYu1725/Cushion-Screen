# 宏参数: name, time（来自 storage cs:temp video）
# 拼接 source_name = <name>_f<time> 并调用 get_frame

$function cs:get_frame {source_name:"$(name)_f$(time)"}
