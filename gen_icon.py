# -*- coding: utf-8 -*-
"""生成应用图标 assets/icon.ico（蓝底白色“译”字）"""
import os
from PIL import Image, ImageDraw, ImageFont

os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets"), exist_ok=True)
img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([6, 6, 250, 250], radius=58, fill=(37, 99, 235, 255))
try:
    f = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 150, index=0)
except Exception:
    f = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 150)
bbox = d.textbbox((0, 0), "译", font=f)
w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
d.text(((256 - w) / 2 - bbox[0], (256 - h) / 2 - bbox[1]), "译", font=f, fill=(255, 255, 255, 255))
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon saved:", out)
