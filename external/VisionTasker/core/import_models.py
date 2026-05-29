# -*- coding: utf-8 -*-
import os
import sys
import importlib.util
# gpu_id = '3'
# os.environ["CUDA_VISIBLE_DEVICES"] = gpu_id
# from detr_main import build_model_main
# import argparse
from ultralytics import YOLO
import torch
import clip
import time

torch.set_grad_enabled(False)


def _prepare_paddleocr_top_level_imports():
    """Make PaddleOCR's bundled top-level imports resolve deterministically.

    PaddleOCR 2.x imports modules such as ``tools.infer`` and ``ppocr`` as
    top-level packages from inside its own package directory. ForensiFlow also
    has a project-level ``tools/`` directory, so without this path adjustment
    Python may resolve ``tools`` to the project utilities instead of
    ``site-packages/paddleocr/tools``.
    """
    spec = importlib.util.find_spec("paddleocr")
    if not spec or not spec.submodule_search_locations:
        return
    paddleocr_dir = os.path.abspath(next(iter(spec.submodule_search_locations)))
    if paddleocr_dir in sys.path:
        sys.path.remove(paddleocr_dir)
    sys.path.insert(0, paddleocr_dir)
    tools_mod = sys.modules.get("tools")
    tools_file = os.path.abspath(getattr(tools_mod, "__file__", "") or "")
    tools_paths = [os.path.abspath(path) for path in getattr(tools_mod, "__path__", [])] if tools_mod else []
    if tools_mod and not (
        tools_file.startswith(paddleocr_dir + os.sep)
        or any(path.startswith(paddleocr_dir + os.sep) for path in tools_paths)
    ):
        for name in list(sys.modules):
            if name == "tools" or name.startswith("tools."):
                sys.modules.pop(name, None)

def import_all_models(alg, accurate_ocr=True,  # yolo / vins 目标检测选一
                      model_path_yolo='pt_model/yolo_mdl.pt',
                      model_path_vins_dir='pt_model/yolo_vins_',
                      model_ver='14',
                      model_path_vins_file='_mdl.pt',
                      model_path_cls='pt_model/clip_mdl.pth',
                      gpt4v_mode=False):

    model_path_vins = model_path_vins_dir + model_ver + model_path_vins_file

    print('🥱I\'m importing the model....')
    if accurate_ocr:
        # print('高精度版本OCR不要导入🤣')
        ocr = None
    else:
        # print('📋🤔Basic OCR being imported...')
        _prepare_paddleocr_top_level_imports()
        from paddleocr import PaddleOCR
        ocr = PaddleOCR(use_angle_cls=True)  #, lang='en'
    # print('The OCR has been imported and the detection model you selected is', alg)
    # 导入模型 - YOLO和CLIP都使用GPU加速
    device_yolo = torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")  # YOLO使用默认设备
    device_clip = torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")  # CLIP使用GPU加速
    print(f"🚀 YOLO设备: {device_yolo}")
    print(f"🧠 CLIP设备: {device_clip}")
    model_det = None
    if alg == 'yolo':
        # print('🚀importing RICO-YOLOv8, path：', model_path_yolo)
        model_det = YOLO(model_path_yolo, task='detect')  # Yolov8n
    elif alg == 'vins':
        # print('🚀importing VINS-YOLOv8, path：', model_path_vins)
        model_det = YOLO(model_path_vins, task='detect')  # Yolov8n + vins数据集
    if not gpt4v_mode:
        # print('Target detection model import is complete😉 ✓ ...... I\'m importing the CLIP. It may take a while.😅 path：', model_path_cls)
        model_cls, preprocess = clip.load("ViT-L/14", device=device_clip, jit=False)  # 分类数据集，强制CPU
        # 加载权重
        model_cls.load_state_dict(torch.load(model_path_cls, map_location=device_clip)['network'])
        model_cls.eval()  # 推理模式
        print(f'🧠 CLIP模型已在{device_clip}上加载完成 ✓ 🚀')
    else:
        model_cls, preprocess = None, None
        # print('GPT4V mode 不导入CLIP 你耗子尾汁')

    print('💯Successfully imported the model! Good luck!🍀')
    # if accurate_ocr:
    #     return model_ver, model_det, model_cls, preprocess
    # else:
    #     return model_ver, model_det, model_cls, preprocess, ocr
    return model_ver, model_det, model_cls, preprocess, ocr
