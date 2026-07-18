# 宏参数: name, time
# 非首帧：拼接 source_name 后走 get_frame_update（merge 颜色）

$function cs:get_frame_update {source_name:"$(name)_f$(time)"}
