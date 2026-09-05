# -*- coding: utf-8 -*-
"""核心模块：配置、翻译引擎、词典查词、OCR、数据库、朗读"""
import hashlib
import json
import os
import random
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

# 用户数据（翻译历史/生词本/配置）放在系统数据目录：
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
    "engine": "auto",               # 翻译引擎: auto/google/google_chrome/mymemory/baidu
    "baidu_appid": "",
    "baidu_secret": "",
    "qwen_api_key": "",             # 阿里云百炼 API Key（Qwen 大模型翻译）
    "qwen_model": "qwen3.7-flash",  # Qwen 模型名，可在设置里换
    "autostart": False,             # 开机自启
    "restore_clipboard": True,      # 划词后恢复原剪贴板
    "auto_speak": False,            # 翻译后自动朗读
    "select_enabled": True,         # 启用划词翻译
    "show_popup_seconds": 12,       # 弹窗自动关闭秒数(0=不自动关)
}

APP_NAME = "英译通 EnglishHelper"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


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


def translate_google(text, cfg=None, to_lang=None):
    """谷歌 gtx 免费接口（需能访问谷歌）"""
    url = "https://translate.googleapis.com/translate_a/single"
    r = requests.get(
        url,
        params={"client": "gtx", "sl": "auto", "tl": to_lang or "zh-CN", "dt": "t", "q": text[:4500]},
        headers=UA,
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    translated = "".join(seg[0] for seg in data[0] if seg and seg[0])
    return {"translated": translated, "engine": "谷歌", "detected": data[2] if len(data) > 2 else "en"}


def translate_google_chrome(text, cfg=None, to_lang=None):
    """谷歌 Chrome 内置翻译接口"""
    r = requests.get(
        "https://clients5.google.com/translate_a/t",
        params={"client": "dict-chrome-ex", "sl": "auto", "tl": to_lang or "zh-CN", "q": text[:4500]},
        headers=UA,
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    translated, detected = "", "en"
    if isinstance(data, list):
        for item in data:
            if isinstance(item, list) and item:
                translated += item[0] if isinstance(item[0], str) else ""
                if len(item) > 1 and isinstance(item[-1], str):
                    detected = item[-1]
    return {"translated": translated, "engine": "谷歌", "detected": detected}


def translate_baidu(text, cfg, to_lang=None):
    """百度翻译开放平台（需用户自己的 appid/secret，每月免费5万字符）"""
    appid = (cfg or {}).get("baidu_appid", "")
    secret = (cfg or {}).get("baidu_secret", "")
    if not appid or not secret:
        raise RuntimeError("请先在设置里填写百度翻译的 appid 和密钥")
    salt = random.randint(32768, 65536)
    sign = hashlib.md5((appid + text + str(salt) + secret).encode("utf-8")).hexdigest()
    r = requests.post(
        "https://fanyi-api.baidu.com/api/trans/vip/translate",
        data={"q": text[:5500], "from": "auto", "to": ("en" if to_lang == "en" else "zh"),
              "appid": appid, "salt": salt, "sign": sign},
        headers=UA,
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    if "error_code" in data:
        raise RuntimeError("百度接口错误: %s" % data.get("error_msg", data["error_code"]))
    translated = "\n".join(item["dst"] for item in data.get("trans_result", []))
    return {"translated": translated, "engine": "百度", "detected": data.get("from", "en")}


def translate_mymemory(text, cfg=None, to_lang=None):
    """MyMemory 免费接口（单次最长500字符，作为兜底）"""
    pair = ("zh-CN|en" if to_lang == "en" else "en|zh-CN")
    chunks = [text[i:i + 480] for i in range(0, min(len(text), 4800), 480)]
    parts = []
    for c in chunks:
        r = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": c, "langpair": pair},
            headers=UA,
            timeout=10,
        )
        r.raise_for_status()
        parts.append(r.json()["responseData"]["translatedText"])
    return {"translated": "".join(parts), "engine": "MyMemory",
            "detected": "zh-CN" if to_lang == "en" else "en"}


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
    r = requests.post(
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
        timeout=60,
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


ENGINES = {
    "google": translate_google,
    "google_chrome": translate_google_chrome,
    "mymemory": translate_mymemory,
    "baidu": translate_baidu,
    "qwen": translate_qwen,
}
ENGINE_NAMES = {
    "auto": "自动（推荐，依次尝试多个源）",
    "qwen": "通义千问 Qwen（需API Key，AI翻译）",
    "google": "谷歌翻译",
    "google_chrome": "谷歌翻译（Chrome接口）",
    "mymemory": "MyMemory",
    "baidu": "百度翻译（需密钥）",
}
# 自动模式降级链：配了 Key 优先用 Qwen；没配 Key 时本地校验快速跳过、无网络开销
AUTO_ORDER = ["qwen", "google", "google_chrome", "mymemory", "baidu"]


def translate(text, cfg):
    """按所选引擎翻译，失败自动切换下一个引擎。
    智能方向：划中的是中文时自动改为中译英（方便写英文）"""
    chosen = cfg.get("engine", "auto")
    order = AUTO_ORDER if chosen == "auto" else [chosen] + AUTO_ORDER
    reverse = is_mostly_chinese(text)
    to_lang = "en" if reverse else "zh-CN"
    seen, errors = set(), []
    for name in order:
        if name in seen:
            continue
        seen.add(name)
        fn = ENGINES.get(name)
        if not fn:
            continue
        try:
            res = fn(text, cfg, to_lang=to_lang)
            if res and res["translated"].strip():
                res["reverse"] = reverse
                return res
        except Exception as e:
            errors.append("%s: %s" % (name, e))
    raise RuntimeError("所有翻译源都失败了（请检查网络） " + "; ".join(errors[:2]))


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
        r = requests.get(
            "https://dict.youdao.com/jsonapi",
            params={"q": word, "dicts": json.dumps({"count": 1, "dicts": [["ec"]]}, separators=(",", ":"))},
            headers=UA,
            timeout=6,
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


# ---------------- 数据库（历史 + 生词本） ----------------
class DB:
    def __init__(self, path=DB_PATH):
        self.path = path
        self.lock = threading.Lock()
        self._init()

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=5)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        with self.lock, self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT, translated TEXT, way TEXT, created REAL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS words(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT UNIQUE, meaning TEXT, created REAL, known INTEGER DEFAULT 0)""")

    # --- 历史 ---
    def history_add(self, source, translated, way):
        with self.lock, self._conn() as c:
            c.execute("INSERT INTO history(source, translated, way, created) VALUES(?,?,?,?)",
                      (source[:2000], translated[:3000], way, time.time()))
            # 最多保留1000条
            c.execute("""DELETE FROM history WHERE id NOT IN
                         (SELECT id FROM history ORDER BY id DESC LIMIT 1000)""")

    def history_list(self, limit=300):
        with self.lock, self._conn() as c:
            return c.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def history_clear(self):
        with self.lock, self._conn() as c:
            c.execute("DELETE FROM history")

    def history_delete(self, hid):
        with self.lock, self._conn() as c:
            c.execute("DELETE FROM history WHERE id=?", (hid,))

    # --- 生词本 ---
    def word_add(self, word, meaning):
        with self.lock, self._conn() as c:
            c.execute("""INSERT INTO words(word, meaning, created) VALUES(?,?,?)
                         ON CONFLICT(word) DO UPDATE SET meaning=excluded.meaning, created=excluded.created""",
                      (word.strip()[:100], meaning[:2000], time.time()))

    def word_exists(self, word):
        with self.lock, self._conn() as c:
            return c.execute("SELECT 1 FROM words WHERE word=?", (word.strip()[:100],)).fetchone() is not None

    def word_list(self):
        with self.lock, self._conn() as c:
            return c.execute("SELECT * FROM words ORDER BY id DESC").fetchall()

    def word_delete(self, wid):
        with self.lock, self._conn() as c:
            c.execute("DELETE FROM words WHERE id=?", (wid,))

    def word_known_mark(self, wid):
        """复习时标记为已认识"""
        with self.lock, self._conn() as c:
            c.execute("UPDATE words SET known=1 WHERE id=?", (wid,))

    def word_count(self):
        with self.lock, self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM words").fetchone()[0]

    def export_csv(self, path):
        import csv
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["英文", "中文释义", "收藏时间"])
            for r in self.word_list():
                w.writerow([r["word"], r["meaning"],
                            time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created"]))])


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


# ---------------- 桌面快捷方式 ----------------
def create_desktop_shortcut():
    """在桌面创建"英译通 EnglishHelper.lnk"。用 PowerShell COM 实现，
    参数经 subprocess 列表传递（Unicode安全），程序由用户双击运行时无沙箱限制。"""
    import subprocess
    if getattr(sys, "frozen", False):
        target = os.path.abspath(sys.executable)
    else:
        target = os.path.join(BASE_DIR, "run.bat")
    workdir = os.path.dirname(target)
    lnk = r"'英译通 EnglishHelper.lnk'"
    ps = (
        "$ErrorActionPreference='Stop';"
        "$ws = New-Object -ComObject WScript.Shell;"
        "$desktop = [Environment]::GetFolderPath('Desktop');"
        "$path = ($desktop + '\\' + %s);"
        "$s = $ws.CreateShortcut($path);"
        "$s.TargetPath = '%s';"
        "$s.WorkingDirectory = '%s';"
        "$s.IconLocation = '%s,0';"
        "$s.WindowStyle = 1;"
        "$s.Save();"
        "if (Test-Path $path) { Write-Output 'SHORTCUT_OK' }"
        "else { Write-Output 'SHORTCUT_FAIL' }" % (lnk, target, workdir, target)
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return b"SHORTCUT_OK" in (r.stdout or b"")
    except Exception:
        return False
