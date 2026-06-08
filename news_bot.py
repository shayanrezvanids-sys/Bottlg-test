# -*- coding: utf-8 -*-
"""
ربات خبری تلگرام — رادیو بولتن (سردبیر هوش مصنوعی)
اولویت: ایران ← خاورمیانه ← جهان. زبان خنثی. برچسب «فوری» برای رویدادهای ناگهانیِ مهم.
سردبیر AI از GitHub Models (رایگان) استفاده می‌کند؛ اگر در دسترس نبود، روش پشتیبانِ قانونی فعال می‌شود.
"""

import re
import json
import time
import html
import os
import calendar
from datetime import datetime, timezone, timedelta

import requests
import feedparser
from deep_translator import GoogleTranslator


# ============================================================
#  تنظیمات
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
if not TELEGRAM_BOT_TOKEN:
    raise SystemExit("متغیر محیطی TELEGRAM_BOT_TOKEN تنظیم نشده است.")

TELEGRAM_CHANNEL = "@testbotaii"
BACKUP_CHANNEL = "@analyzeAisTrb"   # چنلِ پشتیبان/گزارش (باید ربات در آن ادمین باشد)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
AI_MODEL = "openai/gpt-4o"            # مدلِ اصلی
AI_MODEL_FALLBACK = "openai/gpt-4o-mini"  # اگر سقفِ مدلِ اصلی پر شد، موقتاً این
AI_ENDPOINT = "https://models.github.ai/inference/chat/completions"

# منابع معتبر؛ پوشش خوبِ ایران/خاورمیانه + جهان، و قابل‌اعتماد در حالت پشتیبان.
RSS_FEEDS = [
    "https://feeds.bbci.co.uk/persian/rss.xml",                 # BBC Persian (فارسی)
    "https://rss.dw.com/rdf/rss-per-all",                       # DW Persian (فارسی)
    "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",  # BBC Middle East
    "https://www.aljazeera.com/xml/rss/all.xml",                # Al Jazeera
    "https://feeds.bbci.co.uk/news/world/rss.xml",              # BBC World
    "https://rss.dw.com/rdf/rss-en-world",                      # Deutsche Welle (EN)
    "https://www.france24.com/en/rss",                          # France 24
]

SOURCE_NAMES = {
    "https://feeds.bbci.co.uk/persian/rss.xml": "BBC فارسی",
    "https://rss.dw.com/rdf/rss-per-all": "دویچه‌وله فارسی",
    "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml": "BBC خاورمیانه",
    "https://www.aljazeera.com/xml/rss/all.xml": "الجزیره",
    "https://feeds.bbci.co.uk/news/world/rss.xml": "BBC World",
    "https://rss.dw.com/rdf/rss-en-world": "دویچه‌وله",
    "https://www.france24.com/en/rss": "France 24",
}

MAX_PER_RUN = 1
CHECK_INTERVAL_MINUTES = 10
RUN_FOREVER = os.environ.get("RUN_FOREVER", "0") == "1"
MAX_CANDIDATES_FOR_AI = 12    # متنِ کاملِ این تعداد خبر خوانده و به AI داده می‌شود
IRAN_SLOTS = 7                # حداقل این تعداد از استخر به خبرهای ایران اختصاص می‌یابد
BURST_MAX = 3                 # در حالتِ جنگِ ایران، حداکثر این تعداد پست در هر اجرا

SEEN_FILE = "seen.json"
RECENT_KEEP = 40   # چند تیترِ اخیر برای جلوگیری از خبرِ تکراری نگه داشته شود

# --- کلمات برای حالت پشتیبان (بدون AI) ---
IRAN_KEYWORDS = [
    "iran", "tehran", "iranian", "irgc", "khamenei", "pezeshkian", "basij",
    "revolutionary guard", "qom", "isfahan", "mashhad", "shiraz", "tabriz", "rial",
    "ایران", "ایرانی", "تهران", "خامنه‌ای", "خامنه ای", "پزشکیان", "سپاه", "پاسداران",
    "قالیباف", "اصفهان", "مشهد", "شیراز", "تبریز", "ریال", "تومان", "مجلس ایران",
]
MIDEAST_KEYWORDS = [
    "israel", "gaza", "palestin", "hamas", "hezbollah", "lebanon", "syria",
    "iraq", "saudi", "yemen", "houthi", "qatar", "kuwait", "bahrain", "oman",
    "uae", "emirates", "jordan", "egypt", "turkey", "middle east", "gulf",
    "red sea", "persian gulf",
]
IMPORTANT_KEYWORDS = [
    "breaking", "urgent", "war", "conflict", "attack", "strike", "missile",
    "killed", "dead", "dies", "death", "casualties", "explosion", "earthquake",
    "flood", "disaster", "crisis", "emergency", "sanction", "election", "vote",
    "parliament", "president", "summit", "treaty", "ceasefire", "nuclear",
    "economy", "inflation", "recession", "protest", "coup", "military",
    "troops", "hostage", "breakthrough", "outbreak", "airstrike",
]
TRIVIA_KEYWORDS = [
    "celebrity", "celebrities", "royal", "kardashian", "viral", "tiktok",
    "instagram", "recipe", "horoscope", "zodiac", "lottery", "influencer",
    "gossip", "fashion", "makeup", "prank", "weird", "bizarre", "reality tv",
]
# نشانه‌های فوریت در تیترِ منبع
BREAKING_WORDS = ["breaking", "urgent", "just in", "developing", "live:"]
SEVERE_WORDS = [
    "missile", "strike", "attack", "airstrike", "invasion", "invades",
    "bombing", "explosion", "killed", "earthquake", "coup", "assassinat",
    "shelling", "war ", "ceasefire collapse",
]

# جایگزینیِ واژه‌های جهت‌دار با معادلِ خنثی (شبکه‌ی ایمنی برای هر دو حالت)
LOADED_REPLACEMENTS = {
    "رژیم صهیونیستی": "اسرائیل",
    "رژیم صهیونیست": "اسرائیل",
    "رژیم اشغالگر": "اسرائیل",
    "رژیم کودک‌کش": "اسرائیل",
}


# ============================================================
#  توابع کمکی
# ============================================================

def load_state():
    """وضعیت را می‌خواند: {seen: لیست شناسه‌های منتشرشده، recent: تیترهای اخیر برای ضدتکرار}.
    با فرمت قدیمی (که فقط یک لیست بود) هم سازگار است."""
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):  # فرمت قدیمی
                return {"seen": data, "recent": []}
            return {"seen": data.get("seen", []), "recent": data.get("recent", [])}
        except Exception:
            return {"seen": [], "recent": []}
    return {"seen": [], "recent": []}


def save_state(state):
    out = {"seen": state.get("seen", [])[-1000:],
           "recent": state.get("recent", [])[-RECENT_KEEP:]}
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)


_STOPWORDS = set((
    "the a an of to in on at for and or is are was were be by with from as has have "
    "had over after into amid against new say says said amid latest "
    "این آن برای تا هم یک های شد کرد گفت می را با که از در به بر هر"
).split())


def _tokens(title):
    t = re.sub(r"[^\w\u0600-\u06FF]+", " ", (title or "").lower())
    return set(w for w in t.split() if len(w) > 2 and w not in _STOPWORDS)


def is_duplicate(title, recent_titles):
    """فقط تیترهای تقریباً یکسان را تکراری می‌شمارد (نه خبرهای هم‌موضوع).
    تشخیصِ ظریفِ تکرار (مثل تحولِ جدیدِ یک رویداد) به خودِ سردبیر AI سپرده می‌شود."""
    a = _tokens(title)
    if not a:
        return False
    for rt in recent_titles:
        b = _tokens(rt)
        if not b:
            continue
        inter = len(a & b)
        union = len(a | b)
        # فقط هم‌پوشانیِ خیلی بالا = تیترِ تقریباً یکسان
        if union and inter / union >= 0.8:
            return True
    return False


def clean_html(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def short_summary(text, max_sentences=3, max_chars=400):
    text = clean_html(text)
    parts = re.split(r"(?<=[.!?؟])\s+", text)
    return " ".join(parts[:max_sentences]).strip()[:max_chars]


def translate_to_fa(text):
    if not text:
        return ""
    try:
        return GoogleTranslator(source="auto", target="fa").translate(text[:4500])
    except Exception:
        return text


def maybe_translate(text):
    """اگر متن از قبل فارسی است، ترجمه لازم نیست (برای فیدهای فارسی در حالت پشتیبان)."""
    if re.search(r"[\u0600-\u06FF]", text or ""):
        return text
    return translate_to_fa(text)


def sanitize_fa(text):
    """واژه‌های جهت‌دار را خنثی می‌کند."""
    if not text:
        return text
    for bad, good in LOADED_REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text


def get_timestamp(entry):
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            try:
                return calendar.timegm(val)
            except Exception:
                pass
    return 0.0


def region_priority(title):
    """۳ = ایران، ۲ = خاورمیانه، ۰ = جهان."""
    t = (title or "").lower()
    if any(k in t for k in IRAN_KEYWORDS):
        return 3
    if any(k in t for k in MIDEAST_KEYWORDS):
        return 2
    return 0


def is_iran_item(c):
    """آیا این خبر درباره‌ی ایران است؟ (روی تیتر و خلاصه‌ی فید بررسی می‌شود)."""
    blob = ((c.get("title") or "") + " " + clean_html(c.get("raw") or "")).lower()
    return any(k in blob for k in IRAN_KEYWORDS)


WAR_KEYWORDS = [
    "war", "airstrike", "air strike", "missile strike", "missile attack",
    "rocket attack", "drone strike", "bombing", "bombardment", "shelling",
    "invasion", "ceasefire", "truce", "armed conflict", "military strike", "warplane",
    "جنگ", "حمله موشکی", "حمله هوایی", "حمله پهپادی", "بمباران", "موشک‌باران",
    "موشکباران", "آتش‌بس", "آتش بس", "حمله نظامی", "تهاجم نظامی", "جنگنده", "شلیک موشک",
]


def is_war_item(c):
    """آیا این خبر مربوط به جنگ/درگیری است؟"""
    blob = ((c.get("title") or "") + " " + clean_html(c.get("raw") or "")).lower()
    return any(k in blob for k in WAR_KEYWORDS)


def importance_score(title):
    t = (title or "").lower()
    pos = sum(1 for kw in IMPORTANT_KEYWORDS if kw in t)
    neg = sum(1 for kw in TRIVIA_KEYWORDS if kw in t)
    return pos - 2 * neg


def source_is_urgent(title, strict=False):
    """آیا تیترِ منبع نشانه‌ی فوریت دارد؟ strict=True فقط کلمات صریح breaking را می‌پذیرد."""
    t = (title or "").lower()
    if any(w in t for w in BREAKING_WORDS):
        return True
    if not strict and any(w in t for w in SEVERE_WORDS):
        return True
    return False


def first_sentence(text, max_chars=160):
    text = (text or "").strip()
    parts = re.split(r"(?<=[.!?؟])\s+", text)
    s = parts[0].strip() if parts else text
    return s[:max_chars]


def build_message(title, summary, breaking=False):
    if breaking:
        # پیام فوری: کوتاه، فقط 🚨 + تیترِ بولد (بدون کلمه‌ی «فوری»)
        text = f"🚨 <b>{html.escape(title)}</b>\n\n"
        short = first_sentence(summary)
        if short:
            text += f"{html.escape(short)}\n\n"
        text += "@RadioBulletin | رادیو بولتن"
        return text
    text = f"🔹 <b>{html.escape(title)}</b>\n\n"
    if summary:
        text += f"<blockquote expandable>{html.escape(summary)}</blockquote>\n\n"
    text += "@RadioBulletin | رادیو بولتن"
    return text


VIDEO_EXT_RE = re.compile(r"\.(mp4|m4v|webm|mov)(\?|$)", re.I)


def _looks_like_video_file(url):
    return bool(url) and bool(VIDEO_EXT_RE.search(url))


def get_feed_video(entry):
    """ویدیوی مستقیم (فایل) را از فید پیدا می‌کند و باکیفیت‌ترین را برمی‌گرداند."""
    best_url, best_score = None, -1
    for enc in (entry.get("enclosures") or []):
        u = enc.get("href") or enc.get("url")
        typ = (enc.get("type") or "")
        if u and (typ.startswith("video") or _looks_like_video_file(u)) and best_score < 0:
            best_url, best_score = u, 0
    for m in (entry.get("media_content") or []):
        u = m.get("url")
        typ = (m.get("type") or "")
        medium = (m.get("medium") or "")
        if u and (medium == "video" or typ.startswith("video") or _looks_like_video_file(u)):
            try:
                h = int(m.get("height") or 0)
            except (ValueError, TypeError):
                h = 0
            try:
                br = int(m.get("bitrate") or 0)
            except (ValueError, TypeError):
                br = 0
            score = h * 100000 + br  # بالاترین رزولوشن/بیت‌ریت
            if score > best_score:
                best_url, best_score = u, score
    return best_url


def get_article_text(url):
    """متنِ اصلیِ خبر را از صفحه‌اش می‌خواند تا AI تمامِ جزئیاتِ مهم را داشته باشد."""
    if not url:
        return ""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"}
        r = requests.get(url, headers=headers, timeout=12)
        r.raise_for_status()
        page = r.text
    except Exception:
        return ""
    paras = re.findall(r"<p[^>]*>(.*?)</p>", page, re.S | re.I)
    text = " ".join(clean_html(p) for p in paras)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1800]


def get_og_media(article_url):
    """از صفحه‌ی خبر، عکس باکیفیت و (در صورت وجود) ویدیوی مستقیم را برمی‌گرداند."""
    if not article_url:
        return (None, None)
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"}
        r = requests.get(article_url, headers=headers, timeout=20)
        r.raise_for_status()
        page = r.text
    except Exception:
        return (None, None)

    def meta(props):
        for prop in props:
            m = re.search(r'<meta[^>]+(?:property|name)=["\']' + re.escape(prop)
                          + r'["\'][^>]*content=["\']([^"\']+)["\']', page, re.I)
            if m:
                return m.group(1)
            m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']'
                          + re.escape(prop) + r'["\']', page, re.I)
            if m:
                return m.group(1)
        return None

    image = meta(["og:image:secure_url", "og:image:url", "og:image", "twitter:image"])
    video = meta(["og:video:secure_url", "og:video:url", "og:video", "twitter:player:stream"])
    # فقط فایلِ ویدیوی مستقیم را بپذیر (نه پلیر/embed مثل یوتیوب)
    if not _looks_like_video_file(video):
        video = None
    return (image, video)


def get_image_url(entry, raw_html):
    best_url, best_w = None, -1
    for key in ("media_content", "media_thumbnail"):
        for m in (entry.get(key) or []):
            u = m.get("url")
            if not u:
                continue
            try:
                w = int(m.get("width") or 0)
            except (ValueError, TypeError):
                w = 0
            if w > best_w:
                best_w, best_url = w, u
    if best_url:
        return best_url
    for enc in (entry.get("enclosures") or []):
        u = enc.get("href") or enc.get("url")
        typ = (enc.get("type") or "")
        if u and (typ.startswith("image") or re.search(r"\.(jpe?g|png|webp)", u, re.I)):
            return u
    for link in (entry.get("links") or []):
        if (link.get("type") or "").startswith("image") and link.get("href"):
            return link["href"]
    m = re.search(r'<img[^>]+src="([^"]+)"', raw_html or "")
    if m:
        return m.group(1)
    return None


def _strip_tags(text):
    return re.sub(r"<[^>]+>", "", text or "")


def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHANNEL, "text": text,
               "parse_mode": "HTML", "disable_web_page_preview": True}
    resp = requests.post(url, json=payload, timeout=30)
    if resp.status_code == 400:
        # خطای پارس HTML → یک‌بارِ دیگر به‌صورتِ متنِ ساده بفرست تا پست گم نشود
        payload = {"chat_id": TELEGRAM_CHANNEL, "text": _strip_tags(text),
                   "disable_web_page_preview": True}
        resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def send_photo_to_telegram(photo_url, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    payload = {"chat_id": TELEGRAM_CHANNEL, "photo": photo_url,
               "caption": caption, "parse_mode": "HTML"}
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _download_capped(url, cap=50 * 1024 * 1024):
    """ویدیو را تا سقفِ مشخص دانلود می‌کند؛ اگر بزرگ‌تر بود None برمی‌گرداند."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"}
    r = requests.get(url, headers=headers, timeout=180, stream=True)
    r.raise_for_status()
    data = b""
    for chunk in r.iter_content(65536):
        data += chunk
        if len(data) > cap:
            r.close()
            return None
    return data


def send_video_to_telegram(video_url, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    payload = {"chat_id": TELEGRAM_CHANNEL, "caption": caption,
               "parse_mode": "HTML", "supports_streaming": "true"}
    # تلاش اول: دانلودِ خودِ فایل و آپلودِ مستقیم (کیفیتِ بهتر، تا ۵۰ مگابایت)
    data = None
    try:
        data = _download_capped(video_url)
    except Exception:
        data = None
    if data:
        files = {"video": ("video.mp4", data)}
        resp = requests.post(url, data=payload, files=files, timeout=300)
        resp.raise_for_status()
        return resp.json()
    # تلاش دوم: ارسال با لینک (اگر دانلود نشد یا خیلی بزرگ بود)
    p = dict(payload)
    p["video"] = video_url
    resp = requests.post(url, json=p, timeout=180)
    resp.raise_for_status()
    return resp.json()


def _msg_id(resp):
    try:
        return (resp or {}).get("result", {}).get("message_id")
    except Exception:
        return None


def post_news(chosen, fa_title, fa_summary, breaking):
    msg = build_message(fa_title, fa_summary, breaking)
    _, og_video = get_og_media(chosen["link"])
    video = chosen.get("video") or og_video
    photo = chosen.get("image")  # فقط عکسِ اختصاصیِ فیدِ همان خبر (نه بنرِ عمومیِ og)

    # ۱) اگر فایلِ ویدیوی مستقیم بود، اول ویدیو (دانلود+آپلود، بعد لینک)
    if video:
        try:
            return _msg_id(send_video_to_telegram(video, msg))
        except Exception:
            pass  # ویدیو نشد → سراغ عکس/متن

    # ۲) فقط اگر خودِ منبع برای این خبر عکس داشت
    if photo:
        try:
            return _msg_id(send_photo_to_telegram(photo, msg))
        except Exception:
            pass  # عکس نشد → فقط متن

    # ۳) در نهایت فقط متن (اجباری نیست عکس داشته باشد)
    return _msg_id(send_to_telegram(msg))


def post_to_backup(chosen, fa_title, model_label, msg_id):
    """برای هر پست، یک گزارشِ فنی در چنلِ پشتیبان ثبت می‌کند."""
    if not BACKUP_CHANNEL:
        return
    tehran = timezone(timedelta(hours=3, minutes=30))
    now = datetime.now(tehran).strftime("%Y-%m-%d  %H:%M")
    chan = TELEGRAM_CHANNEL.lstrip("@")
    post_link = f"https://t.me/{chan}/{msg_id}" if msg_id else "—"
    text = (
        "🗒 <b>گزارشِ انتشار</b>\n\n"
        f"🕒 ساعت انتشار: {now} (به وقت تهران)\n"
        f"📰 منبع: {html.escape(chosen.get('source') or '—')}\n"
        f"🔗 لینک خبر: {html.escape(chosen.get('link') or '—')}\n"
        f"🤖 مدلِ زبانی: {html.escape(str(model_label or '—'))}\n"
        f"📌 لینک پست: {post_link}\n"
        f"📝 تیتر: {html.escape(fa_title)}"
    )
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, timeout=30, json={
            "chat_id": BACKUP_CHANNEL, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": True})
    except Exception as e:
        print("  خطا در ارسالِ گزارش به چنلِ پشتیبان:", e)


# ============================================================
#  سردبیر هوش مصنوعی (GitHub Models)
# ============================================================

def ai_editor(candidates, recent_titles, max_items=1):
    """خروجی: (نتیجه، مدلِ استفاده‌شده). نتیجه = لیستِ picks یا "SKIP" یا None."""
    if not GITHUB_TOKEN:
        return None, None

    listing = []
    for i, c in enumerate(candidates):
        brief = (c.get("body") or clean_html(c["raw"]))[:1200]
        listing.append(f"{i}. {c['title']} — {brief}")
    listing = "\n".join(listing)

    system = (
        "You are the senior editor of an independent, strictly politically neutral, "
        "Persian-language news channel. Rules:\n"
        "1) Favor important hard news (politics, conflict, diplomacy, economy, disasters, "
        "major society/science). Reject ONLY clearly soft/trivial items (celebrity, "
        "lifestyle, gossip, odd/weird news). If a story is ordinary but still real news, "
        "it is fine to pick it.\n"
        "2) SELECTION PRIORITY, in this exact order:\n"
        "   (a) FIRST priority is any GENUINE breaking event — a major, sudden, high-impact "
        "story unfolding now (see rule 4). If one exists, choose it regardless of region. "
        "If several are breaking, prefer Iran, then Middle East, then world.\n"
        "   (b) If nothing is breaking, IRAN IS THE TOP EDITORIAL PRIORITY. This channel is "
        "Iran-focused: whenever there is ANY reasonable news about Iran (events inside Iran, "
        "Iranian politics/economy/society, or anything directly involving Iran), STRONGLY "
        "prefer it over Middle East or world news. Pick a world story only when there is no "
        "worthwhile Iran item, or when a world event is genuinely huge. After Iran, prefer "
        "the wider Middle East, then the rest of the world.\n"
        "3) WRITING STYLE — write like a popular Iranian Telegram news channel (e.g. the style "
        "of big channels), in CASUAL SPOKEN/COLLOQUIAL Persian (فارسیِ محاوره‌ای و شکسته), NOT "
        "formal written Persian:\n"
        "   - Use spoken verb/word forms: «می‌کنه» (نه می‌کند)، «-ه» برای «است»، «می‌خوان» (نه "
        "می‌خواهند)، «نمی‌کنن» (نه نمی‌کنند)، «می‌گه» (نه می‌گوید)، «رو» (نه را)، «تو» (نه در، "
        "هرجا طبیعیه)، «قراره»، «دیگه»، «اینا/اونا»، «یه» (نه یک)، «خیلیا». Sound like a real "
        "person talking, with energy and attitude — but accurate.\n"
        "   - Front-load the news; be concrete (names, numbers, places). Lead with the SOURCE "
        "when known, channel-style, e.g. «وال‌استریت ژورنال:» یا «رویترز:» یا «سفارت آمریکا تو "
        "عراق:».\n"
        "   - COMPLETENESS: say WHAT actually happened/was said (the real content, figures, "
        "outcome) — never just 'so-and-so issued a statement'. Use the article text provided.\n"
        "   - Use a few RELEVANT emojis tastefully — country flags (🇮🇷🇺🇸🇮🇱🇮🇶), and a topic "
        "emoji where it fits. Don't overdo it. (Do NOT add a leading bullet/🔴 — the channel "
        "adds that itself.)\n"
        "   - BANNED stiff/cliché phrases: «شایان ذکر است»، «گفتنی است»، «لازم به ذکر است»، «در "
        "همین راستا»، «بر این اساس»، «در همین حال»، «بنا بر این گزارش». No wire-copy tone.\n"
        "   - Length: as long as needed (usually 2-4 sentences). Keep NEUTRAL on naming "
        "(«اسرائیل» نه «رژیم صهیونیستی»); casual register is fine but don't take sides or invent.\n"
        "4) breaking: reserve true for VIOLENT/CONFLICT events only — war, armed-conflict "
        "escalation, military or missile/air strikes, terror attacks, bombings, "
        "assassinations. STRONGLY prefer events involving Iran or the Middle East; for such "
        "violent events elsewhere, mark breaking only if clearly major. Do NOT mark breaking "
        "for non-violent news (politics, economy, diplomacy, disasters, statements, routine "
        "or ongoing news). When in doubt, false.\n\n"
        "VOICE EXAMPLES — match this CASUAL SPOKEN tone exactly (do NOT reuse their facts):\n"
        "• title: «وال‌استریت ژورنال: ترامپ تهدید کرد اگه آمریکایی‌ها کشته بشن، آتش‌بس با ایران "
        "تمومه» — summary: «🇺🇸 ترامپ تو جمع دستیاراش گفته اگه نیروهای آمریکایی به‌دست تهران کشته "
        "بشن، آتش‌بس رو تموم می‌کنه و دوباره می‌ره سراغ جنگ. حمله‌های پشت‌سرهمِ تهران فشار رو روش "
        "بیشتر کرده و خیلیا دیگه به دوامِ آتش‌بس شک دارن.»\n"
        "• title: «سفارت آمریکا تو عراق به شهرونداش هشدار داد فعلاً به خاورمیانه سفر نکنن» — "
        "summary: «🇮🇶 با بالا‌گرفتنِ تنش‌ها تو منطقه، سفارت آمریکا از شهروندای آمریکایی خواسته "
        "فعلاً قیدِ سفر به خاورمیانه رو بزنن. به اونایی هم که تو منطقه زندگی می‌کنن گفته از الان "
        "نزدیک‌ترین پناهگاه یا جای امن رو پیدا کنن که اگه درگیری شد، غافلگیر نشن.»"
    )
    recent_block = ""
    if recent_titles:
        rt = "\n".join(f"- {t}" for t in recent_titles[-12:])
        recent_block = (
            "Recently posted headlines (to avoid EXACT repeats). Do not re-post the very "
            "same report. But a genuinely NEW development on an ongoing story IS allowed and "
            "SHOULD be posted — e.g. a ceasefire, a new strike, an escalation, a new "
            "statement are all NEW news even if the same war/topic was covered before. Only "
            "skip a near-identical repeat of the exact same event:\n" + rt + "\n\n"
        )
    if max_items > 1:
        task = (
            "Below are candidate news items. Pick the SINGLE best one — UNLESS Iran is RIGHT "
            "NOW a direct party to an ACTIVE armed conflict (Iran is attacking or being "
            "attacked — war, missile/air/drone strikes, bombing, etc.) AND several DISTINCT "
            "developments are happening at once. ONLY in that specific case may you pick up "
            f"to {max_items} distinct items (e.g. a strike, a counter-strike, a ceasefire), "
            "most important first. If Iran is merely mentioned, only commenting on someone "
            "else's war, or it's ordinary news, pick EXACTLY ONE. Skip trivia and "
            "near-identical repeats.\n\n"
        )
    else:
        task = (
            "Below are candidate news items. Pick the SINGLE best per the rules above. You "
            "should ALMOST ALWAYS pick one; return an empty list ONLY if every item is "
            "clearly trivial/soft or a near-identical repeat of an already-posted headline.\n\n"
        )
    user = (
        task
        + recent_block +
        "Respond with ONLY a JSON object, no markdown, no extra text. The 'items' array has "
        f"1 to {max_items} entries (empty only to skip):\n"
        '{\"items\": [{\"index\": <number>, '
        '\"title_fa\": \"<short COLLOQUIAL spoken-Persian lead, source-led if known>\", '
        '\"summary_fa\": \"<COLLOQUIAL spoken-Persian detail with the real content, 2-4 sentences, a few emojis ok>\", '
        '\"breaking\": <true|false>}]}\n\n'
        f"Items:\n{listing}"
    )

    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"}
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    # اول مدلِ اصلی؛ اگر به سقف خورد (429)، خودکار از مدلِ پشتیبان (mini) استفاده کن.
    content = None
    used_model = None
    for m in (AI_MODEL, AI_MODEL_FALLBACK):
        if m is None:
            continue
        try:
            r = requests.post(AI_ENDPOINT, headers=headers, timeout=60,
                              json={"model": m, "temperature": 0.7, "messages": messages})
            if r.status_code == 429:
                print(f"  سقفِ مدل {m} پر است؛ تلاش با مدلِ بعدی…")
                continue
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"].strip()
            used_model = m
            break
        except Exception as e:
            print(f"  خطا با مدل {m}: {e}")
            continue

    if content is None:
        print("  سردبیر AI در دسترس نیست (هر دو مدل ناموفق).")
        return None, None
    if used_model != AI_MODEL:
        print(f"  (با مدلِ پشتیبان نوشته شد: {used_model})")

    try:
        content = re.sub(r"^```(?:json)?|```$", "", content.strip()).strip()
        data = json.loads(content)
        items = data.get("items")
        if items is None:  # سازگاری با حالتِ تک‌خبری
            if int(data.get("index", -1)) == -1:
                return "SKIP", used_model
            items = [data]
        picks = []
        used = set()
        for it in items[:max_items]:
            try:
                idx = int(it.get("index", -1))
            except (ValueError, TypeError):
                continue
            if not (0 <= idx < len(candidates)) or idx in used:
                continue
            title_fa = (it.get("title_fa") or "").strip()
            summary_fa = (it.get("summary_fa") or "").strip()
            if not title_fa:
                continue
            picks.append((idx, title_fa, summary_fa, bool(it.get("breaking", False))))
            used.add(idx)
        return (picks if picks else "SKIP"), used_model
    except Exception as e:
        print("  خطا در پردازشِ پاسخِ AI:", e)
        return None, used_model


def rule_based_pick(candidates):
    """پشتیبان: خبر نرم را حذف؛ اولویت: فوری ← ایران ← خاورمیانه ← جهان ← اهمیت ← تازگی."""
    pool = [c for c in candidates if importance_score(c["title"]) >= 0]
    if not pool:
        return None
    pool.sort(key=lambda c: (1 if source_is_urgent(c["title"], strict=True) else 0,
                             region_priority(c["title"]),
                             importance_score(c["title"]),
                             c["ts"]), reverse=True)
    chosen = pool[0]
    fa_title = maybe_translate(chosen["title"])
    time.sleep(1)
    fa_summary = maybe_translate(short_summary(chosen["raw"]))
    return (chosen, fa_title, fa_summary)


# ============================================================
#  منطق اصلی
# ============================================================

def main():
    state = load_state()
    seen_set = set(state["seen"])
    recent = state["recent"]

    candidates = []
    for feed_url in RSS_FEEDS:
        print(f"در حال خواندن فید: {feed_url}")
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"  خطا در خواندن فید: {e}")
            continue
        for entry in feed.entries:
            uid = entry.get("id") or entry.get("link")
            if not uid or uid in seen_set:
                continue
            raw = entry.get("summary") or entry.get("description") or ""
            candidates.append({
                "uid": uid,
                "link": entry.get("link") or "",
                "title": entry.get("title", ""),
                "raw": raw,
                "image": get_image_url(entry, raw),
                "video": get_feed_video(entry),
                "ts": get_timestamp(entry),
                "source": SOURCE_NAMES.get(feed_url, feed_url),
            })

    if not candidates:
        print("خبر تازه‌ای نبود.")
        return

    # تازه‌ترین‌ها اول
    candidates.sort(key=lambda c: c["ts"], reverse=True)
    # حذفِ خبرهای تکراری نسبت به اخیراً منتشرشده‌ها (تطبیقِ هم‌زبان، پنجره‌ی کوتاه)
    candidates = [c for c in candidates if not is_duplicate(c["title"], recent[-12:])]
    if not candidates:
        print("همه‌ی خبرهای تازه تکراری بودند؛ چیزی ارسال نشد.")
        return

    # استخرِ AI: سهمِ تضمینی برای خبرهای ایران تا حتماً به دستِ سردبیر برسند
    iran_items = [c for c in candidates if is_iran_item(c)]
    other_items = [c for c in candidates if not is_iran_item(c)]
    pool = iran_items[:IRAN_SLOTS]
    for c in other_items:
        if len(pool) >= MAX_CANDIDATES_FOR_AI:
            break
        pool.append(c)
    # اگر هنوز جا مانده، خبرهای ایرانِ بیشتر را هم اضافه کن
    for c in iran_items[IRAN_SLOTS:]:
        if len(pool) >= MAX_CANDIDATES_FOR_AI:
            break
        pool.append(c)
    print(f"  استخر: {len(pool)} خبر ({len([c for c in pool if is_iran_item(c)])} مربوط به ایران)")

    # متنِ کاملِ خبرها را بخوان تا سردبیر AI همه‌ی جزئیاتِ مهم را داشته باشد
    for c in pool:
        c["body"] = get_article_text(c["link"])

    # حالتِ پرتراکم: اگر خبرِ جنگیِ مربوط به ایران در استخر بود، اجازه‌ی چند پست در این اجرا
    iran_war = any(is_iran_item(c) and is_war_item(c) for c in pool)
    max_items = BURST_MAX if iran_war else 1
    if iran_war:
        print(f"  حالتِ پرتراکم (جنگِ ایران): تا {max_items} خبر در این اجرا.")

    # سردبیر AI با آگاهی از خبرهای اخیراً منتشرشده (ضدتکرارِ هوشمند و چندزبانه)
    result, used_model = ai_editor(pool, recent, max_items)

    picks = []  # هر آیتم: (chosen, fa_title, fa_summary, breaking)
    model_label = used_model

    if result is None:
        print("  بازگشت به روش قانونی (پشتیبان).")
        rb = rule_based_pick(pool)
        if rb:
            chosen, fa_title, fa_summary = rb
            breaking = source_is_urgent(chosen["title"], strict=True)
            picks.append((chosen, fa_title, fa_summary, breaking))
            model_label = "روش پشتیبان (ترجمه‌ی گوگل)"
    elif result == "SKIP":
        print("  سردبیر AI: خبر مهم/غیرتکراری در این نوبت نبود؛ چیزی ارسال نشد.")
    else:
        for idx, fa_title, fa_summary, ai_breaking in result:
            picks.append((pool[idx], fa_title, fa_summary, bool(ai_breaking)))

    if not picks:
        save_state(state)
        return

    for n, (chosen, fa_title, fa_summary, breaking) in enumerate(picks):
        fa_title = sanitize_fa(fa_title)
        fa_summary = sanitize_fa(fa_summary)
        try:
            msg_id = post_news(chosen, fa_title, fa_summary, breaking)
            tag = "🚨 " if breaking else ""
            print(f"  منتشر شد: {tag}{fa_title}")
            state["seen"].append(chosen["uid"])
            state["recent"].append(chosen["title"])
            # گزارشِ هم‌زمان در چنلِ پشتیبان
            post_to_backup(chosen, fa_title, model_label, msg_id)
        except Exception as e:
            print(f"  خطا در ارسال خبر: {e}")
        if n < len(picks) - 1:
            time.sleep(3)  # فاصله‌ی کوتاه بین پست‌ها

    save_state(state)
    print("تمام شد.")


if __name__ == "__main__":
    if RUN_FOREVER:
        print("ربات شروع شد (حالت حلقه‌ی داخلی)...")
        while True:
            try:
                main()
            except Exception as e:
                print("خطای کلی:", e)
            print(f"خواب به مدت {CHECK_INTERVAL_MINUTES} دقیقه...")
            time.sleep(CHECK_INTERVAL_MINUTES * 60)
    else:
        main()
