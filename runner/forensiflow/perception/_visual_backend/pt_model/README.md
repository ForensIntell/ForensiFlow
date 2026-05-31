# ForensiFlow Visual Perception Weights

ForensiFlow visual perception model weights are excluded from the public
repository because the CLIP classifier weight is about 2.7 GB.

Download the model package:

```text
Baidu Netdisk: https://pan.baidu.com/s/1ioiguwzM_l-asrjl0P6PYQ?pwd=fbrj
Extraction code: fbrj
```

Place these files in this directory before running full visual perception:

```text
pt_model/
├── clip_mdl.pth
├── yolo_mdl.pt
├── yolo_vins_14_mdl.pt
├── clip_labels/
│   ├── icon_labels_chn.json
│   ├── icon_labels_en.json
│   └── icon_labels_final.json
└── README.md
```

Expected SHA256 checksums:

```text
02aa5f38c2839c0b6c637bfbf04f949895ed750a93b056436ef0cc099512473f  clip_mdl.pth
e13613b9c95edf45195441045c2827e67db791a337a348637fd21661d240b888  yolo_mdl.pt
fac2aff493d1bd5c23d96d499c2f5ba25a8f116b870c338b429a847a8edc15ed  yolo_vins_14_mdl.pt
```

The repository `.gitignore` excludes `*.pt` and `*.pth`; do not commit local
model weights.
