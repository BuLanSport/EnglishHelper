# -*- coding: utf-8 -*-
"""核心功能实测：Qwen 翻译 / 有道词典 / OCR"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core

print("=" * 50)
print("1) 翻译接口测试（Qwen 百炼）")
print("=" * 50)
cfg = core.load_config()
text = "The quick brown fox jumps over the lazy dog."
try:
    r = core.translate_qwen(text, cfg)
    print("OK -> %s | 检测语言: %s" % (r["translated"][:40], r.get("detected")))
except Exception as e:
    print("FAIL -> %s" % str(e)[:120])

print()
print("=" * 50)
print("2) Qwen 翻译入口测试（自动中英方向）")
print("=" * 50)
try:
    r = core.translate(text, cfg)
    print("OK ->", r["translated"][:40], "|", r["engine"])
except Exception as e:
    print("FAIL ->", e)

print()
print("=" * 50)
print("3) 有道词典查词测试")
print("=" * 50)
for w in ["hello", "apple", "transaction"]:
    ph, ms = core.lookup_word(w)
    print("[%s] 音标=%s 释义=%s" % (w, ph, ms[:3]))

print()
print("=" * 50)
print("4) OCR 测试（生成英文图片再识别）")
print("=" * 50)
try:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (760, 200), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 34)
        font2 = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 28)
    except Exception:
        font = font2 = None
    d.text((30, 40), "Machine learning is a field of", font=font, fill="black")
    d.text((30, 110), "artificial intelligence.", font=font2, fill="black")
    import numpy as np
    arr = np.array(img)
    out = core.ocr_image(arr)
    print("OCR结果 ->", repr(out))
except Exception as e:
    import traceback
    traceback.print_exc()

print()
print("is_single_word 测试:", core.is_single_word("hello"), core.is_single_word("hello world foo bar"),
      core.is_single_word("The quick brown fox jumps over the lazy dog."))
print("全部测试完成")
