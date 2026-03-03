# 配置文件

# 选项
high_conf_flag = False  # 是否使用高支持度阈值 对于系统应用可以提升加快速度
clean_save = False  # 是否只按照路径要求输出layout的json
plot_show = False  # 是否显示图片
if clean_save:
    plot_show = False
ocr_save_flag = 'save'  # ocr省钱模式 用于反复调整时 直接使用已保存的ocr结果 部分文件支持
ocr_output_only = False  # 新增：只输出ocr结果 不要所有ip
alg = 'yolo'  # yolo / detr / vins 三种算法
accurate_ocr = False  # 是否使用高精度版OCR
lang = 'zh'  # en / zh  # 输出语言选择
workflow_only = False     # 只输出json和整体流程图
ocr = None

# 路径
label_path_dir = 'pt_model/clip_labels/'  # 176类分类注释文件存放地址
save_path_old = 'data/screenshot/screenshot_old.png'
save_path_new = 'data/screenshot/screenshot_new.png'
save_path_default = 'data/screenshot/screenshot_default.png'
output_root = 'data/outputs/'  # 如果不是clean输出模式 完整版的输出文件存放的文件夹
layout_json_dir = 'clean_json'  # clean模式下 最终识别结果json输出的文件夹
