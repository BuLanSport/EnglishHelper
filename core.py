# -*- coding: utf-8 -*-
"""核心模块：配置、Qwen 文本/视觉翻译、翻译历史数据库、朗读"""
import base64
import json
import os
import re
import sqlite3
import sys
import threading
import time

import requests

# 打包成exe后，程序相关文件放在 exe 所在目录；源码运行时放在本文件目录
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 用户数据（翻译历史/配置）放在系统数据目录：
# 程序目录会随重装/更新被替换，放这里以后更新版本也不会丢数据
DATA_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA") or BASE_DIR, "EnglishHelper")
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = BASE_DIR


def _migrate_old_data():
    """旧版本把 data.db/config.json 放在程序目录，首次升级自动搬到新位置"""
    import shutil
    for name in ("data.db", "config.json"):
        old = os.path.join(BASE_DIR, name)
        new = os.path.join(DATA_DIR, name)
        if os.path.exists(old) and not os.path.exists(new):
            try:
                shutil.copy2(old, new)
            except Exception:
                pass


_migrate_old_data()

CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
DB_PATH = os.path.join(DATA_DIR, "data.db")

DEFAULT_CONFIG = {
    "hotkey_select": "alt+q",       # 划词翻译快捷键
    "hotkey_capture": "alt+w",      # 截图翻译快捷键
    "qwen_api_key": "",             # 阿里云百炼 API Key（Qwen 大模型翻译，必需）
    "qwen_model": "qwen3.7-flash",  # Qwen 模型名，可在设置里换
    "autostart": False,             # 开机自启
    "restore_clipboard": True,      # 划词后恢复原剪贴板
    "auto_speak": False,            # 翻译后自动朗读
    "select_enabled": True,         # 启用划词翻译
    "show_popup_seconds": 12,       # 弹窗自动关闭秒数(0=不自动关)
}

APP_NAME = "英译通 EnglishHelper"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

# HTTP：模块级共享 Session 复用连接（keep-alive），连续翻译不再重复 TCP/TLS 握手
QWEN_TIMEOUT = (5, 60)   # (连接秒, 读取秒)：大模型生成较慢，读取时限放宽
_SESSION = requests.Session()

# 大模型接口公共参数
QWEN_CHAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
QWEN_MAX_TOKENS = 8192    # 显式声明输出上限：不设时部分模型默认上限很小，译文会被无声截断
MAX_INPUT_CHARS = 20000   # 单次翻译的原文长度上限（超出会截断并在译文里明确提示）


# ---------------- 配置 ----------------
def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ---------------- 翻译引擎 ----------------
def is_mostly_chinese(text):
    """判断文本是否以中文为主（中文字符占比>30%）——是则自动中译英"""
    if not text:
        return False
    total = len(text)
    han = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return han / total > 0.3


def _qwen_chat(api_key, payload):
    """POST 百炼 OpenAI 兼容接口，返回 Response。

    请求显式带 max_tokens：不设的话部分模型的默认输出上限很小，
    译文/识别结果会被无声截断（表现就是"翻译到一半突然没了"）；
    个别模型不认这个上限值（HTTP 400 且报错提到 max_tokens）时，
    自动去掉该参数重试一次，保证兼容。"""
    for attempt in (0, 1):
        r = _SESSION.post(
            QWEN_CHAT_URL,
            headers={"Authorization": "Bearer " + api_key, **UA},
            json=payload,
            timeout=QWEN_TIMEOUT,
        )
        if (r.status_code == 400 and attempt == 0
                and payload.get("max_tokens") and "max_tokens" in r.text):
            payload.pop("max_tokens")
            continue
        return r


def translate_qwen(text, cfg, to_lang=None):
    """阿里云百炼 Qwen 大模型翻译（OpenAI 兼容接口，需用户自己的 API Key，
    也可通过环境变量 DASHSCOPE_API_KEY 提供）"""
    api_key = (cfg or {}).get("qwen_api_key", "").strip() \
        or os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise RuntimeError("请先在设置里填写阿里云百炼 API Key（sk-开头）")
    model = ((cfg or {}).get("qwen_model") or "qwen3.7-flash").strip()
    src, cap_note = text, ""
    if len(src) > MAX_INPUT_CHARS:  # 原文超长：截断但明确提示，不再无声截断
        src = src[:MAX_INPUT_CHARS]
        cap_note = "\n\n（注意：原文过长，仅翻译了前 %d 字）" % MAX_INPUT_CHARS
    if to_lang == "en":
        sys_prompt = ("你是专业翻译引擎。把用户内容翻译成地道的英文，"
                      "只输出译文本身，不要任何解释或引号，保留原有换行格式。")
    else:
        sys_prompt = ("你是专业翻译引擎。把用户内容翻译成简体中文，"
                      "只输出译文本身，不要任何解释或引号，保留原有换行格式。")
    r = _qwen_chat(api_key, {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": src},
        ],
        "stream": False,
        "max_tokens": QWEN_MAX_TOKENS,
        "enable_thinking": False,  # 翻译无需思考模式，响应更快
    })
    r.raise_for_status()
    data = r.json()
    if data.get("code") or (data.get("message") and not data.get("choices")):
        raise RuntimeError("百炼接口错误: %s" % (data.get("message") or data.get("code")))
    try:
        choice = data["choices"][0]
        translated = (choice["message"]["content"] or "").strip()
        finish = str(choice.get("finish_reason") or "").lower()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("百炼接口返回格式异常: %s" % str(data)[:200])
    if not translated:
        raise RuntimeError("Qwen 没有返回译文")
    if finish == "length":
        # 译文被模型输出上限切断：明确提示，而不是当成完整译文展示
        translated += "\n\n（注意：内容较长，译文被模型输出上限截断，以上内容不完整）"
    if cap_note:
        translated += cap_note
    return {"translated": translated, "engine": "Qwen(%s)" % model,
            "detected": "zh-CN" if to_lang == "en" else "en"}


def translate(text, cfg, direction="auto"):
    """Qwen 大模型翻译（阿里云百炼，需在设置里填 API Key）。

    direction：auto=按原文语言自动判定方向（划中文自动中译英，方便写英文）；
    en=强制中译英；zh=强制英译中——自动判定失误时由用户在浮窗手动指定。"""
    if direction == "en":
        reverse = True
    elif direction == "zh":
        reverse = False
    else:
        reverse = is_mostly_chinese(text)
    to_lang = "en" if reverse else "zh-CN"
    try:
        res = translate_qwen(text, cfg, to_lang=to_lang)
        res["reverse"] = reverse
        return res
    except RuntimeError:
        raise  # 未配Key/百炼接口错误等：保留原始中文提示
    except Exception as e:
        raise RuntimeError("翻译失败，请检查网络后重试：%s" % e)


# ---------------- 截图翻译（Qwen 视觉模型：识别+翻译一步完成，无本地 OCR） ----------------
def _recover_json_string(tail):
    """从可能被截断的 JSON 字符串值里抢救内容：收集到闭合引号或串尾为止；
    若恰好截断在转义序列中间（如 "\\u4e2d\\" 悬空的反斜杠），丢弃残缺转义。"""
    out, i = [], 0
    while i < len(tail):
        c = tail[i]
        if c == '"':
            break
        if c == "\\":
            if i + 1 >= len(tail):
                break
            out.append(tail[i:i + 2])
            i += 2
            continue
        out.append(c)
        i += 1
    try:
        return json.loads('"' + "".join(out) + '"')
    except Exception:
        return "".join(out)


def _parse_vision_result(content, finish=""):
    """解析视觉模型返回内容 → (text, translated, lang)。

    正常情况按完整 JSON 解析（模型偶尔加说明文字，取第一个 { 到最后一个 }）；
    当输出被 max_tokens 截断导致 JSON 不完整时，完整解析会失败——
    这时用正则从残片里逐字段抢救已识别的原文和已生成的译文，
    并在译文末尾附上截断提示，而不是把整段半成品 JSON 当译文展示。"""
    text, translated, lang = "", "", ""
    m = re.search(r"\{.*\}", content, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                text = str(obj.get("text") or "").strip()
                translated = str(obj.get("translated") or "").strip()
                lang = str(obj.get("lang") or "").strip().lower()
        except Exception:
            pass
    if not text and not translated:
        # JSON 没解析出来（多半是被截断）：从残片里逐字段抢救
        m = re.search(r'"text"\s*:\s*"', content)
        if m:
            text = _recover_json_string(content[m.end():]).strip()
        m = re.search(r'"translated"\s*:\s*"', content)
        if m:
            translated = _recover_json_string(content[m.end():]).strip()
        m = re.search(r'"lang"\s*:\s*"([a-zA-Z\-]*)"', content)
        if m:
            lang = m.group(1).strip().lower()
    if not translated:
        translated = content  # 模型没按 JSON 格式返回：当作纯译文处理
    if finish == "length":
        translated += "\n\n（注意：截图里文字太多，结果被模型输出上限截断，以上内容不完整）"
    return text, translated, lang


def translate_image_qwen(png_bytes, cfg):
    """把截图图片直接发给 Qwen 视觉模型（如 qwen3.7-flash），
    一次调用同时完成“识别图中文字 + 翻译”，不需要本地 OCR 引擎。

    返回 {"text": 识别出的原文, "translated": 译文, "lang": "en"/"zh", "engine": ...}
    lang 是原文语种：zh 表示原文是中文（即中译英方向），en 反之。
    """
    api_key = (cfg or {}).get("qwen_api_key", "").strip() \
        or os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise RuntimeError("请先在设置里填写阿里云百炼 API Key（sk-开头）")
    model = ((cfg or {}).get("qwen_model") or "qwen3.7-flash").strip()
    data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    sys_prompt = ("你是专业翻译引擎，具备图片识别能力。请识别图片中的主体文字内容并翻译：\n"
                  "1. 图片文字以英文为主 → 翻译成简体中文；以中文为主 → 翻译成英文；"
                  "中英混合时按占比更多的语言决定方向。\n"
                  "2. 忽略图片中的窗口标题栏、按钮、边框、水印等界面元素，"
                  "只识别用户真正想翻译的主体内容。\n"
                  "3. 原样保留原文与译文的换行结构。\n"
                  '4. 只输出一个 JSON 对象，不要输出任何其它内容（不要 markdown 代码块）：\n'
                  '   {"text": "识别出的全部原文", "translated": "翻译结果", "lang": "原文语种，只写en或zh"}\n'
                  '5. 如果图片里没有任何文字，返回 {"text": "", '
                  '"translated": "图片中没有识别到文字", "lang": ""}')
    try:
        r = _qwen_chat(api_key, {
            "model": model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": "识别并翻译这张截图："},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]},
            ],
            "stream": False,
            "max_tokens": QWEN_MAX_TOKENS,
            "enable_thinking": False,  # 无需思考模式，响应更快
        })
        r.raise_for_status()
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError("截图翻译请求失败，请检查网络后重试：%s" % e)
    data = r.json()
    if data.get("code") or (data.get("message") and not data.get("choices")):
        msg = data.get("message") or data.get("code")
        if re.search(r"image|visual|multimodal|not support|不支持的", str(msg), re.I):
            msg = ("%s（当前 Qwen 模型不支持图片输入时，请在设置里把模型名换成"
                   "支持视觉的型号，如 qwen3.7-flash 或 qwen-vl-max）" % msg)
        raise RuntimeError("百炼接口错误: %s" % msg)
    try:
        choice = data["choices"][0]
        content = (choice["message"]["content"] or "").strip()
        finish = str(choice.get("finish_reason") or "").lower()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("百炼接口返回格式异常: %s" % str(data)[:200])
    if not content:
        raise RuntimeError("Qwen 没有返回结果")
    text, translated, lang = _parse_vision_result(content, finish)
    return {"text": text, "translated": translated,
            "lang": "zh" if lang.startswith("zh") else "en",
            "engine": "Qwen视觉(%s)" % model}


# ---------------- 数据库（翻译历史） ----------------
class DB:
    """SQLite 数据层。

    性能设计：
    - 常驻单连接（check_same_thread=False + 内部锁串行化），避免每次操作都新建/销毁连接；
    - WAL 日志 + synchronous=NORMAL，降低写延迟；
    - 历史裁剪攒批执行：每新增 HISTORY_CLEAN_EVERY 条才清理一次，
      而不是每次插入都附带一次全表 DELETE。
    """

    HISTORY_KEEP = 1000         # 历史最多保留条数
    HISTORY_CLEAN_EVERY = 128   # 每新增这么多条才做一次裁剪

    def __init__(self, path=DB_PATH):
        self.path = path
        self.lock = threading.Lock()
        self._conn = None
        self._hist_pending = 0
        self._init()

    def _connection(self):
        if self._conn is None:
            c = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
            c.row_factory = sqlite3.Row
            try:
                c.execute("PRAGMA journal_mode=WAL")
                c.execute("PRAGMA synchronous=NORMAL")
            except Exception:
                pass
            self._conn = c
        return self._conn

    def _init(self):
        with self.lock:
            c = self._connection()
            c.execute("""CREATE TABLE IF NOT EXISTS history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT, translated TEXT, way TEXT, created REAL)""")
            c.commit()

    # --- 历史 ---
    def history_add(self, source, translated, way):
        with self.lock:
            c = self._connection()
            try:
                c.execute("INSERT INTO history(source, translated, way, created) VALUES(?,?,?,?)",
                          (source[:2000], translated[:3000], way, time.time()))
                self._hist_pending += 1
                if self._hist_pending >= self.HISTORY_CLEAN_EVERY:
                    self._hist_pending = 0
                    c.execute("""DELETE FROM history WHERE id NOT IN
                                 (SELECT id FROM history ORDER BY id DESC LIMIT ?)""",
                              (self.HISTORY_KEEP,))
                c.commit()
            except Exception:
                c.rollback()
                raise

    def history_list(self, limit=300):
        with self.lock:
            return self._connection().execute(
                "SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def history_clear(self):
        with self.lock:
            c = self._connection()
            c.execute("DELETE FROM history")
            c.commit()
            self._hist_pending = 0

    def history_delete(self, hid):
        self.history_delete_many([hid])

    def history_delete_many(self, ids):
        """批量删除：一次事务删多条，避免多选时逐条连接/提交"""
        if not ids:
            return
        with self.lock:
            c = self._connection()
            try:
                c.executemany("DELETE FROM history WHERE id=?", [(i,) for i in ids])
                c.commit()
            except Exception:
                c.rollback()
                raise


# ---------------- 朗读（Windows 自带 TTS，零依赖） ----------------
def speak(text, lang="en"):
    text = (text or "").strip()[:220].replace("'", "''")
    if not text:
        return
    voice = "409" if lang.startswith("en") else "804"  # 英文/中文 locale id
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$v=$s.GetInstalledVoices()|Where-Object{$_.VoiceInfo.Id -like '*%s*' -or $_.VoiceInfo.Culture.Name -like '%s*'}|Select-Object -First 1;"
        "if($v){$s.SelectVoice($v.VoiceInfo.Name)};"
        "$s.Rate=-2;$s.Speak('%s')" % (voice, voice, text)
    )
    try:
        import subprocess
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except Exception:
        pass


# ---------------- 开机自启 ----------------
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _autostart_cmd():
    if getattr(sys, "frozen", False):
        return '"%s"' % sys.executable
    pythonw = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "pythonw.exe")
    return '"%s" "%s"' % (pythonw, os.path.join(BASE_DIR, "main.py"))

def set_autostart(enable):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enable:
                winreg.SetValueEx(k, "EnglishHelper", 0, winreg.REG_SZ, _autostart_cmd())
            else:
                try:
                    winreg.DeleteValue(k, "EnglishHelper")
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False

