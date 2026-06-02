# -*- coding: utf-8 -*-
"""
ربات خبری تلگرام (نسخه‌ی رایگان) — رادیو بولتن
هر ۵ دقیقه یک خبر منتشر می‌کند، با اولویت اخبار مهم.
منابع خارجی به فارسی ترجمه می‌شوند؛ منابع ایرانی با برچسب «به گفته منابع داخلی».
"""

import re
import json
import time
import html
import os

import requests
import feedparser
from deep_translator import GoogleTranslator


# ============================================================
#  تنظیمات
# ============================================================

# توکن از متغیر محیطی خوانده می‌شود (دیگر داخل کد نیست تا لو نرود).
# روی GitHub در بخش Secrets با نام TELEGRAM_BOT_TOKEN ذخیره‌اش کن.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
if not TELEGRAM_BOT_TOKEN:
    raise SystemExit("متغیر محیطی TELEGRAM_BOT_TOKEN تنظیم نشده است.")

TELEGRAM_CHANNEL = "@testbotaii"

# منابع خبری. "iranian": True یعنی منبع داخلیِ فارسی‌زبان (ترجمه نمی‌شود).
RSS_FEEDS = [
    # ---- منابع خارجی معتبر (ترجمه می‌شوند) ----
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml",                 "iranian": False},  # BBC
    {"url": "https://www.theguardian.com/world/rss",                       "iranian": False},  # Guardian
    {"url": "https://www.aljazeera.com/xml/rss/all.xml",                   "iranian": False},  # Al Jazeera
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",      "iranian": False},  # New York Times
    {"url": "https://feeds.npr.org/1004/rss.xml",                          "iranian": False},  # NPR World
    {"url": "https://rss.dw.com/rdf/rss-en-world",                         "iranian": False},  # Deutsche Welle
    {"url": "https://www.france24.com/en/rss",                             "iranian": False},  # France 24
    {"url": "http://rss.cnn.com/rss/edition_world.rss",                    "iranian": False},  # CNN World
    # ---- منابع ایرانی معتبر (بدون ترجمه) ----
    {"url": "https://www.irna.ir/rss",      "iranian": True},   # ایرنا
    {"url": "https://www.isna.ir/rss",      "iranian": True},   # ایسنا
    {"url": "https://www.mehrnews.com/rss", "iranian": True},   # مهر
]

# هر اجرا چند خبر منتشر شود
MAX_PER_RUN = 1
# هر چند دقیقه یک‌بار اجرا شود (فقط در حالت حلقه‌ی داخلی استفاده می‌شود)
CHECK_INTERVAL_MINUTES = 5
# روی GitHub Actions این را تنظیم نکن (یک‌بار اجرا می‌شود و خود Actions زمان‌بندی را انجام می‌دهد).
# روی سرور شخصی/VPS مقدار محیطی RUN_FOREVER=1 بده تا خودش حلقه بزند.
RUN_FOREVER = os.environ.get("RUN_FOREVER", "0") == "1"

# کلمات کلیدی برای تشخیص اخبار مهم (در تیتر)
IMPORTANT_KEYWORDS = [
    "breaking", "urgent", "dead", "dies", "killed", "death", "war",
    "attack", "explosion", "earthquake", "crisis", "emergency",
    "exclusive", "alert", "strike", "missile", "evacuat", "ceasefire",
    "فوری", "مهم", "کشته", "حمله", "زلزله", "بحران", "جنگ", "انفجار",
    "اضطراری", "هشدار", "موشک", "تحریم", "درگذشت", "فوت", "آتش‌بس",
]

SEEN_FILE = "seen.json"


# ============================================================
#  توابع کمکی
# ============================================================

def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_seen(seen):
    seen = seen[-1000:]
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False)


def clean_html(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def short_summary(text, max_sentences=3, max_chars=500):
    text = clean_html(text)
    parts = re.split(r"(?<=[.!?؟])\s+", text)
    summary = " ".join(parts[:max_sentences]).strip()
    return summary[:max_chars]


def translate_to_fa(text):
    if not text:
        return ""
    text = text[:4500]
    return GoogleTranslator(source="auto", target="fa").translate(text)


def importance_score(title):
    """هرچه کلمات مهم بیشتری در تیتر باشد، امتیاز بالاتر."""
    t = (title or "").lower()
    return sum(1 for kw in IMPORTANT_KEYWORDS if kw in t)


def get_timestamp(entry):
    """زمان انتشار خبر برای مرتب‌سازی بر اساس تازگی."""
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            try:
                return time.mktime(val)
            except Exception:
                pass
    return 0.0


def build_message(title, summary, iranian):
    text = f"🔹 <b>{html.escape(title)}</b>\n\n"
    if summary:
        text += f"<blockquote expandable>{html.escape(summary)}</blockquote>\n\n"
    text += "@RadioBulletin | رادیو بولتن"
    return text


def get_og_image(article_url):
    """عکس باکیفیت را از صفحه‌ی اصلی خبر می‌گیرد (og:image / twitter:image)."""
    if not article_url:
        return None
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"}
        r = requests.get(article_url, headers=headers, timeout=20)
        r.raise_for_status()
        page = r.text
    except Exception:
        return None
    for prop in ("og:image:secure_url", "og:image:url", "og:image", "twitter:image"):
        # تگ متا ممکن است content را قبل یا بعد از property بنویسد
        m = re.search(
            r'<meta[^>]+(?:property|name)=["\']' + re.escape(prop)
            + r'["\'][^>]*content=["\']([^"\']+)["\']', page, re.I)
        if m:
            return m.group(1)
        m = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']'
            + re.escape(prop) + r'["\']', page, re.I)
        if m:
            return m.group(1)
    return None


def get_image_url(entry, raw_html):
    """عکس بنر خبر را از جاهای مختلف فید پیدا می‌کند (بزرگ‌ترین را ترجیح می‌دهد)."""
    # ۱) media:content و media:thumbnail — بزرگ‌ترین (بیشترین عرض) را انتخاب کن
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
    # ۲) enclosure
    for enc in (entry.get("enclosures") or []):
        u = enc.get("href") or enc.get("url")
        typ = (enc.get("type") or "")
        if u and (typ.startswith("image") or
                  re.search(r"\.(jpe?g|png|webp)", u, re.I)):
            return u
    # ۳) لینک‌های نوع تصویر
    for link in (entry.get("links") or []):
        if (link.get("type") or "").startswith("image") and link.get("href"):
            return link["href"]
    # ۴) تگ <img> داخل متن خبر
    m = re.search(r'<img[^>]+src="([^"]+)"', raw_html or "")
    if m:
        return m.group(1)
    return None


def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def send_photo_to_telegram(photo_url, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    payload = {
        "chat_id": TELEGRAM_CHANNEL,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": "HTML",
    }
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


# ============================================================
#  منطق اصلی
# ============================================================

def main():
    seen = load_seen()
    seen_set = set(seen)

    # ۱) جمع‌آوری همه‌ی خبرهای جدید از همه‌ی منابع
    candidates = []
    for feed_cfg in RSS_FEEDS:
        feed_url = feed_cfg["url"]
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
            title = entry.get("title", "")
            raw = entry.get("summary") or entry.get("description") or ""
            candidates.append({
                "uid": uid,
                "link": entry.get("link") or "",
                "title": title,
                "raw": raw,
                "image": get_image_url(entry, raw),
                "iranian": feed_cfg["iranian"],
                "score": importance_score(title),
                "ts": get_timestamp(entry),
            })

    # ۲) اولویت با اخبار مهم، سپس تازه‌ترین‌ها
    candidates.sort(key=lambda c: (c["score"], c["ts"]), reverse=True)

    # ۳) انتشار
    posted = 0
    for c in candidates:
        if posted >= MAX_PER_RUN:
            break
        try:
            if c["iranian"]:
                fa_title = c["title"]
                fa_summary = short_summary(c["raw"])
            else:
                fa_title = translate_to_fa(c["title"])
                time.sleep(1)
                fa_summary = translate_to_fa(short_summary(c["raw"]))

            msg = build_message(fa_title, fa_summary, c["iranian"])

            # عکس باکیفیت را اول از صفحه‌ی خبر امتحان کن، بعد عکس فید
            photo = get_og_image(c["link"]) or c["image"]
            if photo:
                try:
                    send_photo_to_telegram(photo, msg)
                except Exception:
                    # اگر این عکس ارسال نشد، عکس فید را امتحان کن، بعد متن خالی
                    try:
                        if c["image"] and c["image"] != photo:
                            send_photo_to_telegram(c["image"], msg)
                        else:
                            send_to_telegram(msg)
                    except Exception:
                        send_to_telegram(msg)
            else:
                send_to_telegram(msg)
            print(f"  منتشر شد: {fa_title}")
            posted += 1
            seen.append(c["uid"])
            seen_set.add(c["uid"])
        except Exception as e:
            print(f"  خطا در پردازش/ارسال خبر: {e}")
            continue

    save_seen(seen)
    print(f"تمام شد. خبرهای منتشرشده در این اجرا: {posted}")


if __name__ == "__main__":
    if RUN_FOREVER:
        print("ربات شروع شد (هر ۵ دقیقه یک خبر)...")
        while True:
            try:
                main()
            except Exception as e:
                print("خطای کلی:", e)
            print(f"خواب به مدت {CHECK_INTERVAL_MINUTES} دقیقه...")
            time.sleep(CHECK_INTERVAL_MINUTES * 60)
    else:
        main()
