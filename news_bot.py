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

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
AI_MODEL = "openai/gpt-4o-mini"
AI_ENDPOINT = "https://models.github.ai/inference/chat/completions"

# منابع معتبر؛ پوشش خوبِ ایران/خاورمیانه + جهان، و قابل‌اعتماد در حالت پشتیبان.
RSS_FEEDS = [
    "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",  # BBC Middle East
    "https://www.aljazeera.com/xml/rss/all.xml",                # Al Jazeera
    "https://feeds.bbci.co.uk/news/world/rss.xml",              # BBC World
    "https://rss.dw.com/rdf/rss-en-world",                      # Deutsche Welle
    "https://www.france24.com/en/rss",                          # France 24
]

MAX_PER_RUN = 1
CHECK_INTERVAL_MINUTES = 10
RUN_FOREVER = os.environ.get("RUN_FOREVER", "0") == "1"
MAX_CANDIDATES_FOR_AI = 18

SEEN_FILE = "seen.json"

# خبر فقط وقتی «فوری» تگ می‌خورد که حداکثر این مدت پیش منتشر شده باشد (۳۰ دقیقه).
RECENT_SECONDS = 30 * 60

# --- کلمات برای حالت پشتیبان (بدون AI) ---
IRAN_KEYWORDS = [
    "iran", "tehran", "iranian", "irgc", "khamenei", "pezeshkian",
    "ایران", "تهران",
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


def is_recent(ts):
    """آیا خبر حداکثر ۳۰ دقیقه پیش منتشر شده؟ (اگر زمان نامعلوم بود، خیر)."""
    return ts > 0 and (time.time() - ts) <= RECENT_SECONDS


def first_sentence(text, max_chars=160):
    text = (text or "").strip()
    parts = re.split(r"(?<=[.!?؟])\s+", text)
    s = parts[0].strip() if parts else text
    return s[:max_chars]


def build_message(title, summary, breaking=False):
    if breaking:
        # پیام فوری: کوتاه، بدون 🔹، با پیشوند 🚨فوری/
        text = f"🚨فوری/ <b>{html.escape(title)}</b>\n\n"
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


def get_og_image(article_url):
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
        m = re.search(r'<meta[^>]+(?:property|name)=["\']' + re.escape(prop)
                      + r'["\'][^>]*content=["\']([^"\']+)["\']', page, re.I)
        if m:
            return m.group(1)
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']'
                      + re.escape(prop) + r'["\']', page, re.I)
        if m:
            return m.group(1)
    return None


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


def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHANNEL, "text": text,
               "parse_mode": "HTML", "disable_web_page_preview": True}
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


def post_news(chosen, fa_title, fa_summary, breaking):
    msg = build_message(fa_title, fa_summary, breaking)
    photo = get_og_image(chosen["link"]) or chosen["image"]
    if photo:
        try:
            send_photo_to_telegram(photo, msg)
        except Exception:
            try:
                if chosen["image"] and chosen["image"] != photo:
                    send_photo_to_telegram(chosen["image"], msg)
                else:
                    send_to_telegram(msg)
            except Exception:
                send_to_telegram(msg)
    else:
        send_to_telegram(msg)


# ============================================================
#  سردبیر هوش مصنوعی (GitHub Models)
# ============================================================

def ai_editor(candidates):
    """خروجی: (index, title_fa, summary_fa, breaking) یا "SKIP" یا None (AI در دسترس نیست)."""
    if not GITHUB_TOKEN:
        return None

    listing = []
    for i, c in enumerate(candidates):
        brief = clean_html(c["raw"])[:280]
        listing.append(f"{i}. {c['title']} — {brief}")
    listing = "\n".join(listing)

    system = (
        "You are the senior editor of an independent, strictly politically neutral, "
        "Persian-language news channel. Rules:\n"
        "1) Only genuinely important HARD news (politics, conflict, diplomacy, economy, "
        "disasters, major society/science). Reject soft/trivial/odd/celebrity/lifestyle/gossip.\n"
        "2) PRIORITY ORDER for selection: first important news about IRAN, then the wider "
        "MIDDLE EAST, then the rest of the WORLD. Prefer Iran/Middle East items even if a "
        "bit less globally prominent, but never pick a clearly trivial regional item over a "
        "truly major global event.\n"
        "3) Write clean, NEUTRAL Persian. Use standard, non-partisan names: write 'اسرائیل', "
        "never 'رژیم صهیونیستی'; avoid any loaded or propaganda wording from any side. "
        "No opinion, no sensationalism.\n"
        "4) breaking=true ONLY for a sudden, major, high-impact event happening now "
        "(attack, missile strike, war escalation, disaster, major political shock). Else false."
    )
    user = (
        "Below are candidate news items. Pick the SINGLE best one per the rules above. "
        "If at least one is real hard news, pick the best; only if ALL are clearly trivial, "
        "return index -1.\n\n"
        "Respond with ONLY a JSON object, no markdown, no extra text:\n"
        '{\"index\": <number or -1>, \"title_fa\": \"<neutral Persian headline>\", '
        '\"summary_fa\": \"<1-2 sentence neutral Persian summary>\", \"breaking\": <true|false>}\n\n'
        f"Items:\n{listing}"
    )

    payload = {
        "model": AI_MODEL,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"}
    try:
        r = requests.post(AI_ENDPOINT, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
        content = re.sub(r"^```(?:json)?|```$", "", content.strip()).strip()
        data = json.loads(content)
        idx = int(data.get("index", -1))
        if idx == -1:
            return "SKIP"
        if 0 <= idx < len(candidates):
            title_fa = (data.get("title_fa") or "").strip()
            summary_fa = (data.get("summary_fa") or "").strip()
            breaking = bool(data.get("breaking", False))
            if title_fa:
                return (idx, title_fa, summary_fa, breaking)
        return None
    except Exception as e:
        print("  سردبیر AI در دسترس نیست:", e)
        return None


def rule_based_pick(candidates):
    """پشتیبان: خبر نرم را حذف، اولویت ایران←خاورمیانه←جهان، سپس اهمیت و تازگی."""
    pool = [c for c in candidates if importance_score(c["title"]) >= 0]
    if not pool:
        return None
    pool.sort(key=lambda c: (region_priority(c["title"]),
                             importance_score(c["title"]),
                             c["ts"]), reverse=True)
    chosen = pool[0]
    fa_title = translate_to_fa(chosen["title"])
    time.sleep(1)
    fa_summary = translate_to_fa(short_summary(chosen["raw"]))
    return (chosen, fa_title, fa_summary)


# ============================================================
#  منطق اصلی
# ============================================================

def main():
    seen = load_seen()
    seen_set = set(seen)

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
                "ts": get_timestamp(entry),
            })

    if not candidates:
        print("خبر تازه‌ای نبود.")
        return

    # تازه‌ترین‌ها را برای داوری انتخاب کن
    candidates.sort(key=lambda c: c["ts"], reverse=True)
    pool = candidates[:MAX_CANDIDATES_FOR_AI]

    result = ai_editor(pool)

    chosen = fa_title = fa_summary = None
    breaking = False

    if result is None:
        print("  بازگشت به روش قانونی (پشتیبان).")
        rb = rule_based_pick(pool)
        if rb:
            chosen, fa_title, fa_summary = rb
            # حالت پشتیبان: فقط کلمات صریحِ فوریت + خبر تازه (≤۳۰ دقیقه)
            breaking = source_is_urgent(chosen["title"], strict=True) and is_recent(chosen["ts"])
    elif result == "SKIP":
        print("  سردبیر AI: هیچ خبر مهمی در این نوبت نبود؛ چیزی ارسال نشد.")
    else:
        idx, fa_title, fa_summary, ai_breaking = result
        chosen = pool[idx]
        # فوری = AI گفت فوری + تیترِ منبع نشانه‌ی فوریت داشت + خبر تازه (≤۳۰ دقیقه)
        breaking = (ai_breaking and source_is_urgent(chosen["title"], strict=False)
                    and is_recent(chosen["ts"]))

    if not chosen:
        save_seen(seen)
        return

    fa_title = sanitize_fa(fa_title)
    fa_summary = sanitize_fa(fa_summary)

    try:
        post_news(chosen, fa_title, fa_summary, breaking)
        tag = "🚨فوری " if breaking else ""
        print(f"  منتشر شد: {tag}{fa_title}")
        seen.append(chosen["uid"])
    except Exception as e:
        print(f"  خطا در ارسال خبر: {e}")

    save_seen(seen)
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
