# -*- coding: utf-8 -*-
"""核心模块：配置、Qwen 翻译、词典查词、OCR、翻译历史数据库、朗读"""
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

# HTTP：模块级共享 Session 复用连接（keep-alive），连续翻译不再重复 TCP/TLS 握手；
# 连接阶段超时设短：某个翻译源不可达时快速失败，尽快降级到下一个引擎
HTTP_TIMEOUT = (4, 10)   # (连接秒, 读取秒)
QWEN_TIMEOUT = (5, 60)   # 大模型生成较慢，读取时限放宽
_SESSION = requests.Session()


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


def translate_qwen(text, cfg, to_lang=None):
    """阿里云百炼 Qwen 大模型翻译（OpenAI 兼容接口，需用户自己的 API Key，
    也可通过环境变量 DASHSCOPE_API_KEY 提供）"""
    api_key = (cfg or {}).get("qwen_api_key", "").strip() \
        or os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise RuntimeError("请先在设置里填写阿里云百炼 API Key（sk-开头）")
    model = ((cfg or {}).get("qwen_model") or "qwen3.7-flash").strip()
    if to_lang == "en":
        sys_prompt = ("你是专业翻译引擎。把用户内容翻译成地道的英文，"
                      "只输出译文本身，不要任何解释或引号，保留原有换行格式。")
    else:
        sys_prompt = ("你是专业翻译引擎。把用户内容翻译成简体中文，"
                      "只输出译文本身，不要任何解释或引号，保留原有换行格式。")
    r = _SESSION.post(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        headers={"Authorization": "Bearer " + api_key, **UA},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": text[:4000]},
            ],
            "stream": False,
            "enable_thinking": False,  # 翻译无需思考模式，响应更快
        },
        timeout=QWEN_TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") or (data.get("message") and not data.get("choices")):
        raise RuntimeError("百炼接口错误: %s" % (data.get("message") or data.get("code")))
    try:
        translated = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("百炼接口返回格式异常: %s" % str(data)[:200])
    if not translated:
        raise RuntimeError("Qwen 没有返回译文")
    return {"translated": translated, "engine": "Qwen(%s)" % model,
            "detected": "zh-CN" if to_lang == "en" else "en"}


def translate(text, cfg):
    """Qwen 大模型翻译（阿里云百炼，需在设置里填 API Key）。
    智能方向：划中的是中文时自动改为中译英（方便写英文）"""
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


# ---------------- 有道词典查词（音标+释义） ----------------
_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z' \-\.]{0,40}$")


def is_single_word(text):
    """判断是否单词查询模式"""
    t = text.strip()
    if not t or "\n" in t:
        return False
    return bool(_WORD_RE.match(t)) and len(t.split()) <= 3


def _extract_strings(obj, out):
    """递归提取嵌套结构里的字符串（有道jsonapi结构多变）"""
    if isinstance(obj, str):
        s = obj.strip()
        if s and not s.startswith("http") and len(s) < 500:
            out.append(s)
    elif isinstance(obj, list):
        for x in obj:
            _extract_strings(x, out)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("return-phrase", "word", "phone", "ukphone", "usphone"):
                continue
            _extract_strings(v, out)
    return out


def lookup_word(word):
    """有道词典查询，返回 (音标, 释义列表)；失败返回 (None, [])"""
    word = word.strip()
    try:
        r = _SESSION.get(
            "https://dict.youdao.com/jsonapi",
            params={"q": word, "dicts": json.dumps({"count": 1, "dicts": [["ec"]]}, separators=(",", ":"))},
            headers=UA,
            timeout=HTTP_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json().get("ec", {}).get("word", [])
        if not data:
            return None, []
        item = data[0]
        phonetic = item.get("usphone") or item.get("ukphone") or None
        raw = []
        for tr in item.get("trs", []):
            _extract_strings(tr.get("tr", {}), raw)
        # 去重、去掉词条本身
        meanings = []
        for s in raw:
            if s != word and s not in meanings and not s.isascii() or (s != word and re.search(r"[\u4e00-\u9fff]", s)):
                if s not in meanings:
                    meanings.append(s)
        # 只保留含中文的释义，最多8条
        meanings = [m for m in meanings if re.search(r"[\u4e00-\u9fff]", m)][:8]
        return phonetic, meanings
    except Exception:
        return None, []


# ---------------- OCR（RapidOCR，离线识别） ----------------
_ocr = None
_ocr_lock = threading.Lock()


def get_ocr():
    global _ocr
    with _ocr_lock:
        if _ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            _ocr = RapidOCR()
        return _ocr


def ocr_image(arr):
    """识别图片(RGB numpy数组)中的文字，按阅读顺序拼接成多行文本"""
    result, _ = get_ocr()(arr)
    if not result:
        return ""
    items = []
    for box, text, score in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        items.append((min(ys), (min(ys) + max(ys)) / 2, min(xs), str(text), max(ys) - min(ys)))
    items.sort(key=lambda t: t[1])  # 按中心y排序
    lines, cur = [], [items[0]]
    for it in items[1:]:
        if it[1] - cur[-1][1] <= max(it[4], cur[-1][4]) * 0.6:  # 同一行
            cur.append(it)
        else:
            lines.append(cur)
            cur = [it]
    lines.append(cur)
    out = []
    for ln in lines:
        ln.sort(key=lambda t: t[2])  # 行内按x排序
        out.append(" ".join(t[3] for t in ln))
    return "\n".join(out)


def warmup_ocr():
    try:
        get_ocr()
    except Exception:
        pass


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

