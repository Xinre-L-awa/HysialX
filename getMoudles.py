import os
import importlib

def importLibsFromFolder(target_folder):
    contents = os.listdir(target_folder)
    os.chdir(target_folder)

    for item in contents:
        item_path = os.path.join(target_folder, item)
        # 判断是否为文件夹
        if os.path.isdir(item_path):
            # 导入包
            module_name = item  # 包名就是文件夹的名称
            module = importlib.import_module(module_name)
    os.chdir("../")
