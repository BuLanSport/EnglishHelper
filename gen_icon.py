# -*- coding: utf-8 -*-
"""生成应用图标 assets/icon.ico（纯蓝底白色“译”字圆角方块）
1024px 超采样绘制后缩到各尺寸（抗锯齿）；16/24/32 小尺寸用加大字号版保证清晰。
依赖 Pillow：pip install pillow
"""
import os

from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
os.makedirs(ASSETS, exist_ok=True)

S = 1024          # 超采样画布，最后缩小抗锯齿
BLUE = (37, 99, 235, 255)   # #2563eb
WHITE = (255, 255, 255, 255)


def _font(px, bold=True):
    for name in (("msyhbd.ttc", "msyh.ttc") if bold else ("msyh.ttc",)):
        try:
            return ImageFont.truetype("C:/Windows/Fonts/" + name, int(px), index=0)
        except Exception:
            pass
    try:
        return ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", int(px))
    except Exception:
        return ImageFont.load_default()


def draw_icon(size=S, small=False):
    """纯蓝圆角方块 + 白色“译”字（视觉与初版一致，仅更清晰）"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    inset = int(size * 0.023)  # 与旧版 6/256 边距一致
    d.rounded_rectangle([inset, inset, size - 1 - inset, size - 1 - inset],
                        radius=int(size * 0.227), fill=BLUE)
    f = _font(size * (0.66 if small else 0.60))
    bbox = d.textbbox((0, 0), "译", font=f)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1]),
           "译", font=f, fill=WHITE)
    return img


def main():
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48),
             (64, 64), (128, 128), (256, 256)]
    base = draw_icon(S, small=False)
    imgs = []
    for w, h in sizes:
        src = draw_icon(S, small=(w <= 32)) if w <= 32 else base
        imgs.append(src.resize((w, h), Image.LANCZOS))
    out = os.path.join(ASSETS, "icon.ico")
    try:
        imgs[-1].save(out, format="ICO", sizes=sizes, append_images=imgs[:-1])
    except TypeError:  # 旧版 Pillow 不支持 per-size 图，退化为单图缩放
        base.resize((256, 256), Image.LANCZOS).save(out, sizes=sizes)
    imgs[-1].save(os.path.join(ASSETS, "icon_preview.png"))
    print("icon saved:", out)


if __name__ == "__main__":
    main()
