"""
fb_search.py — Facebook Ad Library scraper with AI-powered creative analysis.

FLOW:
  1  Playwright scraping   — collect ads (text + lib_id) per keyword/country
  2  Creative capture      — navigate to each ad URL, grab video frames
                             (3s / 15s / 30s) or static image screenshot
  3  Relevance filter      — single Claude API batch call (YES/NO per ad text)
  4  Creative analysis     — single Claude API multimodal call (text + frames)
  5  Cross-ad analysis     — single Claude API call (patterns, repeated creatives)
  6  Save + git push       — merge facebook section into latest.json, dated file
  7  Cache bust            — empty commit to force GitHub Pages refresh

Usage:
    python scripts/fb_search.py                                # full 12-keyword run
    python scripts/fb_search.py "natural ozempic" "gelatin trick"  # test run
"""
import sys
import os
import re
import json
import asyncio
import base64
import urllib.parse
import logging
import subprocess
import time
from datetime import date, datetime
from pathlib import Path

# ── Dependency check ──────────────────────────────────────────────────────────
_missing = []
try:
    import anthropic
except ImportError:
    _missing.append("anthropic")
try:
    from PIL import Image as PilImage
except ImportError:
    _missing.append("Pillow")

if _missing:
    sys.exit(f"ERROR: Missing packages. Run: pip install {' '.join(_missing)}")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dedup

sys.stdout.reconfigure(encoding="utf-8")

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
DATA_DIR    = PROJECT_DIR / "data"
TEMP_DIR    = PROJECT_DIR / "temp_creatives"
LOG_DIR     = PROJECT_DIR / "logs"

for _d in [DATA_DIR, TEMP_DIR, LOG_DIR]:
    _d.mkdir(exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
_log_file = LOG_DIR / "fb_search.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("fb")

# ── Load .env ─────────────────────────────────────────────────────────────────
_env = PROJECT_DIR / ".env"
if _env.exists():
    with open(_env, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

# ── Config ────────────────────────────────────────────────────────────────────
TODAY        = date.today()
CLAUDE_MODEL = "claude-sonnet-4-6"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_API_KEY:
    log.warning("ANTHROPIC_API_KEY not set — Claude analysis steps will be skipped")

KEYWORDS = [
    "salt trick",
    "pink salt trick",
    "pink salt recipe",
    "gelatin trick",
    "gelatin recipe",
    "gelatine trick",
    "gelatine recipe",
    "ice water hack",
    "ice trick",
    "pink ice trick",
    "natural mounjaro",
    "natural ozempic",
]

COUNTRIES        = ["US", "GB", "DE"]
MIN_DAYS         = 10
MAX_DAYS         = 30
DELAY_SEARCH     = 1.5    # seconds between keyword/country searches
DELAY_CREATIVE   = 1.2    # seconds between creative capture navigations
FRAME_TIMESTAMPS = [3, 15, 30]   # seconds into video for frame grabs

# ── Date parser ───────────────────────────────────────────────────────────────
_MONTHS = {
    "jan":1, "feb":2, "mar":3,  "apr":4,  "may":5,  "jun":6,
    "jul":7, "aug":8, "sep":9,  "oct":10, "nov":11, "dec":12,
    "january":1, "february":2,  "march":3,   "april":4,
    "june":6,    "july":7,      "august":8,  "september":9,
    "october":10,"november":11, "december":12,
}

def _parse_date(s):
    s = (s or "").strip()
    m = re.search(r"\b([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\b", s)
    if m:
        mon = _MONTHS.get(m.group(1).lower()[:3])
        if mon:
            try: return date(int(m.group(3)), mon, int(m.group(2)))
            except ValueError: pass
    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})\b", s)
    if m:
        mon = _MONTHS.get(m.group(2).lower()[:3])
        if mon:
            try: return date(int(m.group(3)), mon, int(m.group(1)))
            except ValueError: pass
    return None

# ── Text helpers ──────────────────────────────────────────────────────────────
_SKIP_LINES = {
    "Learn more","Shop now","See more","Watch more","Sign up",
    "Book now","Contact us","Download","Like","Comment","Share",
    "Follow","Subscribe","Get offer","Apply now","Order now",
}

def _clean_text(raw):
    lines = [l.strip() for l in raw.split("\n") if l.strip() and l.strip() != "​"]
    out = []
    for line in lines:
        if re.match(r"^\d+:\d+\s*/\s*\d+:\d+", line): continue
        if re.match(r"^[A-Z]{2,}\.[A-Z]{2,}", line):  continue
        if line in _SKIP_LINES:                        continue
        out.append(line)
        if len(out) >= 8: break
    return " ".join(out)[:500]

def _is_english(text):
    markers = {
        "the","a","an","and","or","is","are","was","to","you","your",
        "we","our","this","that","with","for","weight","loss","fat",
        "natural","help","get","now","my","of","in","it","i","have","not","do","lose",
    }
    words = set(re.findall(r"\b[a-z]{2,}\b", text.lower()))
    return len(words & markers) >= 4

def _detect_avatar(text):
    t = text.lower()
    tags = []
    if re.search(r"\bdr\.?\b|doctor|physician|medical|clinically|specialist|nurse", t):
        tags.append("médico/autoridade")
    if re.search(r"\bbefore\b.{0,30}\bafter\b|\btransformation\b", t):
        tags.append("antes/depois")
    if any(w in t for w in ["mom","mother","wife"," she ","her "]):
        tags.append("mulher")
    if any(w in t for w in [" man ","husband"," he "," his "]):
        tags.append("homem")
    if any(w in t for w in ["recipe","kitchen","ingredient","mix","dissolve","drink","trick","ritual"]):
        tags.append("receita/truque")
    if any(w in t for w in ["natural","herb","plant","supplement","extract"]):
        tags.append("produto natural")
    return ", ".join(tags) if tags else "geral"

# ── Body text parser ──────────────────────────────────────────────────────────
def _parse_body(body_text, country, keyword):
    """Parse document.body.innerText into a list of ad dicts."""
    results = []
    segments = re.split(r"\nActive\n", body_text)
    for seg in segments[1:]:
        # Library ID
        lib_m = re.search(r"Library ID[:\s]+(\d{10,})", seg)
        lib_id = lib_m.group(1).strip() if lib_m else ""

        # Start date → days active
        date_m = re.search(r"Started running on\s+(.+?)(?:\n|$)", seg)
        start_dt = _parse_date(date_m.group(1)) if date_m else None
        if not start_dt:
            continue
        dias_ativo = (TODAY - start_dt).days
        if not (MIN_DAYS <= dias_ativo <= MAX_DAYS):
            continue

        # Page name + ad text
        detail_m = re.search(
            r"See ad details\n(.+?)\nSponsored\n([\s\S]*?)(?=\nActive\n|Library ID:|$)", seg
        )
        if detail_m:
            page_name   = detail_m.group(1).strip()
            ad_text_raw = detail_m.group(2)
        else:
            spon_m = re.search(
                r"\nSponsored\n([\s\S]*?)(?=\nActive\n|Library ID:|$)", seg
            )
            if not spon_m:
                continue
            page_name   = ""
            ad_text_raw = spon_m.group(1)

        ad_text = _clean_text(ad_text_raw)
        if len(ad_text) < 15 or not _is_english(ad_text):
            continue

        has_video = bool(re.search(r"\d+:\d+\s*/\s*\d+:\d+", seg))
        snap_url  = f"https://www.facebook.com/ads/library/?id={lib_id}" if lib_id else ""

        results.append({
            "lib_id":     lib_id,
            "page":       page_name,
            "texto":      ad_text,
            "data_inicio": start_dt.strftime("%b %d, %Y"),
            "dias_ativo": dias_ativo,
            "tipo_media": "VIDEO" if has_video else "IMAGE",
            "url":        snap_url,
            "pais":       country,
            "keyword":    keyword,
            "avatar":     _detect_avatar(ad_text),
            "analise":    "",
            "frames":     {},       # populated in ETAPA 2
        })
    return results


# ══════════════════════════════════════════════════════════════════════════════
# ETAPA 1 — Playwright Scraping
# ══════════════════════════════════════════════════════════════════════════════

async def _dismiss_cookies(page):
    for sel in [
        '[data-cookiebanner="accept_button"]',
        'button[title="Accept All"]',
        'button:has-text("Allow all cookies")',
        'button:has-text("Accept")',
        '[aria-label="Allow all cookies"]',
    ]:
        try:
            btn = page.locator(sel)
            if await btn.count() > 0:
                await btn.first.click(timeout=2000)
                await page.wait_for_timeout(800)
                return
        except Exception:
            pass


async def _scrape_search_page(page, country, keyword, retries=2):
    """Navigate to one country/keyword Ad Library search and return parsed ads."""
    url = (
        "https://www.facebook.com/ads/library/"
        f"?active_status=active&ad_type=all&country={country}"
        f"&q={urllib.parse.quote(keyword)}"
        f"&search_type=keyword_unordered&media_type=all"
    )
    for attempt in range(retries + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=35000)
            await page.wait_for_timeout(2500)
            await _dismiss_cookies(page)
            for _ in range(3):
                await page.keyboard.press("End")
                await page.wait_for_timeout(1200)
            body = await page.evaluate("document.body.innerText")
            return _parse_body(body, country, keyword)
        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(3)
                continue
            log.error(f"  Scrape failed [{country}] {keyword}: {e}")
            return []


# ══════════════════════════════════════════════════════════════════════════════
# ETAPA 2 — Creative Capture
# ══════════════════════════════════════════════════════════════════════════════

def _resize_frame(path, max_w=360, max_h=640, quality=72):
    """Resize a saved frame to keep file sizes small for API calls."""
    try:
        img = PilImage.open(path)
        img.thumbnail((max_w, max_h), PilImage.LANCZOS)
        img.convert("RGB").save(path, "JPEG", quality=quality)
    except Exception as e:
        log.warning(f"  Resize failed {path}: {e}")


async def _capture_creative(page, ad):
    """
    Navigate to the ad's individual library page and capture:
      - Video ads: seek to FRAME_TIMESTAMPS, screenshot video element each time.
      - Image ads: screenshot the ad card area.

    Returns a dict {timestamp_or_0: local_file_path}.
    """
    if not ad["lib_id"]:
        return {}

    ad_url = f"https://www.facebook.com/ads/library/?id={ad['lib_id']}"
    frames = {}

    try:
        await page.goto(ad_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)
        await _dismiss_cookies(page)
        await page.wait_for_timeout(1500)

        video_count = await page.locator("video").count()

        if video_count > 0:
            video_el = page.locator("video").first

            # Get duration; default 60s if unknown
            duration = await page.evaluate(
                "(document.querySelector('video') || {}).duration || 60"
            )
            try:
                duration = float(duration)
            except Exception:
                duration = 60.0

            # Unmute and start playback
            await page.evaluate("""
                const v = document.querySelector('video');
                if (v) { v.muted = true; v.play().catch(() => {}); }
            """)
            await page.wait_for_timeout(400)

            # Click play button overlay if present
            play_btns = page.locator('div[aria-label*="Play"]')
            if await play_btns.count() > 0:
                try:
                    await play_btns.first.click(timeout=2000)
                    await page.wait_for_timeout(400)
                except Exception:
                    pass

            for ts in FRAME_TIMESTAMPS:
                # Cap timestamp to video duration
                seek_to = min(ts, max(0.5, duration - 0.5))
                frame_path = str(TEMP_DIR / f"{ad['lib_id']}_f{ts}s.jpg")

                await page.evaluate(f"""
                    const v = document.querySelector('video');
                    if (v) {{ v.muted = true; v.currentTime = {seek_to}; }}
                """)
                await page.wait_for_timeout(700)

                try:
                    await video_el.screenshot(path=frame_path, type="jpeg", quality=75)
                    _resize_frame(frame_path)
                    frames[ts] = frame_path
                    kb = os.path.getsize(frame_path) // 1024
                    log.info(f"    ▶ frame {ts}s → {kb} KB")
                except Exception as e:
                    log.warning(f"    ▶ frame {ts}s failed: {e}")

            ad["tipo_media"] = "VIDEO"

        else:
            # Static image ad — screenshot the ad card area
            frame_path = str(TEMP_DIR / f"{ad['lib_id']}_img.jpg")
            await page.screenshot(
                path=frame_path, type="jpeg", quality=80,
                clip={"x": 0, "y": 100, "width": 640, "height": 640},
            )
            _resize_frame(frame_path, max_w=640, max_h=640)
            frames[0] = frame_path
            ad["tipo_media"] = "IMAGE"
            kb = os.path.getsize(frame_path) // 1024
            log.info(f"    🖼  image → {kb} KB")

    except Exception as e:
        log.error(f"  Creative capture failed {ad['lib_id']}: {e}")

    return frames


# ══════════════════════════════════════════════════════════════════════════════
# ETAPA 3 — Relevance Filter (single Claude API call)
# ══════════════════════════════════════════════════════════════════════════════

_RELEVANCE_PROMPT = """\
You are a filter for a Direct Response (DR) weight loss market intelligence tool.

You are reading AD TEXT ONLY (no visuals). Your job is to judge if the central theme of the ad is weight loss, fat loss, or natural slimming — regardless of what products or ingredients are mentioned.

APPROVE (YES) if the ad text is primarily about:
- Losing weight, burning fat, or a natural slimming trick/hack/mechanism
- GLP-1 medications (Ozempic, Mounjaro, semaglutide) or natural alternatives to them (berberine, etc.)
- Someone's personal weight loss story or transformation
- A natural food, ingredient, or habit being used for weight loss
- Appetite suppression, metabolism boost, or belly fat reduction

REJECT (NO) if the ad text is primarily about:
- Hair loss / hair growth (even if GLP-1 side effects are mentioned)
- Skincare, anti-aging, or neck/face treatments
- Sleep, anxiety, or mental health (not weight-related)
- Pure diabetes management with no weight loss angle
- Clothing, fashion, or wardrobe
- A B2B service (e.g. marketing agency, ad consultant)
- Bad breath, gut health, or digestion as the main topic (not as a weight loss side effect)

NOTE: Mentioning brand names (Ozempic, Mounjaro, berberine, GLP-1) is FINE and does NOT cause rejection. Only reject if the central theme is off-topic.

For each ad below, respond only YES or NO.

Respond in this EXACT format, one per line, nothing else:
1: YES
2: NO
...

ADS:
"""


def _filter_relevance(ads):
    """Single Claude API call — returns only the YES ads."""
    if not ANTHROPIC_API_KEY or not ads:
        log.warning("  [ETAPA 3] Skipped (no API key or no ads)")
        return ads

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    lines = []
    for i, ad in enumerate(ads, 1):
        page_label = f"[{ad['pais']}] {ad['page']}" if ad["page"] else f"[{ad['pais']}]"
        lines.append(f"{i}. {page_label}\n   {ad['texto'][:300]}")

    prompt = _RELEVANCE_PROMPT + "\n\n".join(lines)

    log.info(f"  Sending {len(ads)} ads to Claude for relevance check...")
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        log.info(f"  Claude response:\n{raw}")

        approved_idx = set()
        for line in raw.splitlines():
            m = re.match(r"^(\d+)\s*:\s*(YES|NO)", line.strip(), re.IGNORECASE)
            if m and m.group(2).upper() == "YES":
                approved_idx.add(int(m.group(1)))

        kept    = [ad for i, ad in enumerate(ads, 1) if i in approved_idx]
        removed = len(ads) - len(kept)
        log.info(f"  Result: {len(kept)} approved, {removed} rejected")
        return kept

    except Exception as e:
        log.error(f"  [ETAPA 3] Claude API error: {e}")
        return ads


# ══════════════════════════════════════════════════════════════════════════════
# ETAPA 4 — Creative Analysis (single multimodal Claude API call)
# ══════════════════════════════════════════════════════════════════════════════

_ANALYSIS_PROMPT = """\
You are a Direct Response (DR) creative analyst for a weight loss supplement brand targeting UK, US and Germany.

You will receive ad text + 3 video frames or image for each ad.

The goal of a DR weight loss creative is NOT to sell directly — it is to stop the scroll and generate enough curiosity about a method, solution or discovery so the lead clicks and watches the VSL.

FIRST: Apply visual filter — DISCARD the ad if ANY of these are true:
- No real person visible in the image/video (objects alone, clothes on a bed, food on a plate, text-only)
- Medical professional as main character (doctor, nurse, scientist in lab coat)
- Medical imagery (X-rays, organ illustrations, scientific diagrams)
- Product shown explicitly (bottle, pill, package, brand name)
- Image has no connection to weight loss (generic lifestyle, travel, fashion unrelated to body transformation)

Ask yourself: Would this image make someone stop scrolling and want to know more about how to lose weight? If NO — discard.

THEN: For ads that pass the visual filter, return JSON with:
- approved: true
- format: (Receita / UGC / Talking Head / Antes-Depois / Animado / Texto em Tela)
- avatar: description of who appears and context (ex: woman in kitchen, woman in car, man making gelatin)
- editing: visual style description
- observation: anything unusual or out of pattern
- highlight: anything that looks promising or worth testing

For discarded ads return:
- approved: false
- reason: brief explanation of why it was discarded

Each element must also have "ad_index" (1-based integer).
Return ONLY valid JSON array, no markdown, no explanation.

ADS TO ANALYZE:
"""


_ETAPA4_BATCH_SIZE = 5  # ads per Claude call — keeps each call well under 10k tokens/min


def _build_etapa4_content(batch):
    """Build the multimodal content list for a batch of ads."""
    content = [{"type": "text", "text": _ANALYSIS_PROMPT}]
    for i, ad in enumerate(batch, 1):
        content.append({
            "type": "text",
            "text": (
                f"\n\n=== AD {i} ===\n"
                f"Page: {ad['page'] or '(unknown)'}\n"
                f"Country: {ad['pais']}  |  Keyword: {ad['keyword']}  |  "
                f"Days active: {ad['dias_ativo']}  |  Type: {ad['tipo_media']}\n"
                f"Text:\n{ad['texto']}\n"
            ),
        })
        frame_count = 0
        for ts in sorted(ad.get("frames", {}).keys()):
            path = ad["frames"][ts]
            if not os.path.exists(path):
                continue
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            label = f"[Frame @ {ts}s]" if ts > 0 else "[Ad image]"
            content.append({"type": "text", "text": label})
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
            })
            frame_count += 1
        if frame_count == 0:
            content.append({"type": "text", "text": "[No visual captured]"})
    return content


def _analyze_creatives(approved_ads):
    """Visual filter + creative analysis — batched to stay under rate limits."""
    if not ANTHROPIC_API_KEY or not approved_ads:
        log.warning("  [ETAPA 4] Skipped (no API key or no approved ads)")
        return approved_ads

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    visually_approved = []
    rejected_visual = 0
    total_batches = (len(approved_ads) + _ETAPA4_BATCH_SIZE - 1) // _ETAPA4_BATCH_SIZE

    for batch_num, start in enumerate(range(0, len(approved_ads), _ETAPA4_BATCH_SIZE), 1):
        batch = approved_ads[start:start + _ETAPA4_BATCH_SIZE]
        log.info(f"  Batch {batch_num}/{total_batches}: sending {len(batch)} ads to Claude...")

        # Wait 65s between batches to reset the per-minute token window
        if batch_num > 1:
            log.info(f"  Waiting 65s before next batch (rate limit)...")
            time.sleep(65)

        try:
            content = _build_etapa4_content(batch)
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=8192,
                messages=[{"role": "user", "content": content}],
            )
            raw = response.content[0].text.strip()
            log.info(f"  Received {len(raw)} chars from Claude")

            json_match = re.search(r"\[[\s\S]*\]", raw)
            if not json_match:
                log.warning(f"  Batch {batch_num}: could not extract JSON — keeping all {len(batch)} ads")
                visually_approved.extend(batch)
                continue

            analyses = json.loads(json_match.group(0))
            for entry in analyses:
                idx = int(entry.get("ad_index", 0)) - 1
                if not (0 <= idx < len(batch)):
                    continue
                ad = batch[idx]
                if entry.get("approved", True):
                    ad["analise_criativa"] = {
                        "format":      entry.get("format", ""),
                        "avatar":      entry.get("avatar", ""),
                        "editing":     entry.get("editing", ""),
                        "observation": entry.get("observation", ""),
                        "highlight":   entry.get("highlight", ""),
                    }
                    visually_approved.append(ad)
                else:
                    rejected_visual += 1
                    log.info(f"    ✗ visual reject [{ad['page'] or 'no page'}]: {entry.get('reason', '')}")

        except Exception as e:
            log.error(f"  [ETAPA 4] Batch {batch_num} Claude API error: {e}")
            # On error keep the batch so we don't silently drop ads
            visually_approved.extend(batch)

    log.info(f"  Visual filter: {len(visually_approved)} passed, {rejected_visual} rejected")
    return visually_approved


# ══════════════════════════════════════════════════════════════════════════════
# ETAPA 5 — Cross-ad Analysis (single Claude API call)
# ══════════════════════════════════════════════════════════════════════════════

_CROSS_PROMPT = """\
You are a creative intelligence analyst for a weight loss supplement brand.

Analyze these ads as a group. Return ONLY a JSON object with these exact fields:
{
  "repeated_creatives": [
    {
      "description": "<what signals these ads share the same original video/image>",
      "ad_indices": [<1-based list>],
      "pages": [<page names>]
    }
  ],
  "frequent_avatars": [
    {
      "type": "<avatar archetype description>",
      "count": <number>,
      "ad_indices": [<1-based list>]
    }
  ],
  "dominant_mechanism": "<the #1 weight loss mechanism across all ads>",
  "emerging_angle": "<any fresh or unusual angle that appears only once but seems high-potential>",
  "market_signal": "<one sentence summary of what the UK/US/DE market is currently testing>"
}

Return ONLY valid JSON. No markdown, no explanation.

ADS:
"""


def _cross_analyze(approved_ads):
    """Single Claude API call — returns a cross-analysis dict."""
    if not ANTHROPIC_API_KEY or not approved_ads:
        log.warning("  [ETAPA 5] Skipped")
        return {}

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    lines = []
    for i, ad in enumerate(approved_ads, 1):
        criativa = ad.get("analise_criativa", {})
        lines.append(
            f"{i}. [{ad['pais']}] {ad['page'] or 'unknown'} | "
            f"Keyword: {ad['keyword']} | Days: {ad['dias_ativo']} | "
            f"Format: {criativa.get('format', '?')} | "
            f"Avatar: {criativa.get('avatar', '?')}\n"
            f"   Text: {ad['texto'][:200]}"
        )

    prompt = _CROSS_PROMPT + "\n\n".join(lines)

    log.info(f"  Sending {len(approved_ads)} ads to Claude for cross-analysis...")
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        json_match = re.search(r"\{[\s\S]*\}", raw)
        if json_match:
            result = json.loads(json_match.group(0))
            log.info("  Cross-analysis complete")
            return result

    except Exception as e:
        log.error(f"  [ETAPA 5] Claude API error: {e}")

    return {}


# ══════════════════════════════════════════════════════════════════════════════
# ETAPA 6 — Save Results
# ══════════════════════════════════════════════════════════════════════════════

def _make_thumbnail(frames):
    """Return base64 JPEG string from the first available frame file."""
    for ts in [3, 15, 30, 0]:
        path = frames.get(ts)
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
    return ""


def _clean_for_json(ad):
    """Strip internal fields (lib_id, frames dict) and add thumbnail."""
    out = {k: v for k, v in ad.items() if k not in ("lib_id", "frames")}
    out["thumbnail"] = _make_thumbnail(ad.get("frames", {}))
    if "analise_criativa" not in out:
        out["analise_criativa"] = {}
    return out


def _save_and_push(approved_ads, cross_analysis, date_str):
    """Merge facebook section into latest.json, save dated file, git push."""
    latest_path = DATA_DIR / "latest.json"
    dated_path  = DATA_DIR / f"{date_str}.json"

    # Load existing data (preserve YT / TikTok / Trends)
    existing = {}
    try:
        with open(latest_path, encoding="utf-8") as f:
            existing = json.load(f)
    except Exception:
        pass

    clean_ads = [_clean_for_json(ad) for ad in approved_ads]

    payload = {
        "data_execucao": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "youtube":  existing.get("youtube",  []),
        "tiktok":   existing.get("tiktok",   []),
        "facebook": clean_ads,
        "trends":   existing.get("trends",   []),
        "analise":  existing.get("analise",  {
            "tendencias": "", "mecanismos_em_alta": "",
            "avatares_em_alta": "", "recomendacoes": "",
        }),
        "facebook_cross_analysis": cross_analysis,
    }

    for path in (dated_path, latest_path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        log.info(f"  Saved → {path.name}")

    dedup.update_history(date_str)

    # Delete temp creatives
    deleted = sum(1 for f in TEMP_DIR.glob("*.jpg") if f.unlink() is None)
    log.info(f"  Temp files deleted: {deleted}")

    # Git operations
    try:
        os.chdir(PROJECT_DIR)
        subprocess.run(["git", "add", "-f", "data/"], check=True,
                       capture_output=True, text=True)
        r = subprocess.run(
            ["git", "commit", "-m", f"fb collection {date_str}"],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            log.info(f"  Git commit: {r.stdout.strip()}")
        elif "nothing to commit" in (r.stdout + r.stderr):
            log.info("  Git: nothing to commit")
        else:
            log.warning(f"  Git commit: {r.stderr.strip()}")

        subprocess.run(["git", "push"], check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "push", "v2", "main"], check=False,
                       capture_output=True, text=True)
        log.info("  Git push: OK")

    except subprocess.CalledProcessError as e:
        log.error(f"  Git error: {e.stderr}")


# ══════════════════════════════════════════════════════════════════════════════
# ETAPA 7 — Cache Bust
# ══════════════════════════════════════════════════════════════════════════════

def _cache_bust(date_str):
    """Force GitHub Pages CDN refresh via empty commit."""
    try:
        os.chdir(PROJECT_DIR)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", f"cache bust {date_str}"],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(["git", "push"], check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "push", "v2", "main"], check=False,
                       capture_output=True, text=True)
        log.info("  Cache bust: OK")
    except subprocess.CalledProcessError as e:
        log.error(f"  Cache bust error: {e.stderr}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def _main(keywords_override=None):
    date_str = TODAY.isoformat()
    keywords = keywords_override or KEYWORDS

    log.info("═" * 65)
    log.info("  Facebook Ad Library — AI Collection Pipeline")
    log.info(f"  Date      : {date_str}")
    log.info(f"  Keywords  : {keywords}")
    log.info(f"  Countries : {', '.join(COUNTRIES)}")
    log.info(f"  Days range: {MIN_DAYS}–{MAX_DAYS}")
    log.info(f"  Claude    : {'✓ API key set' if ANTHROPIC_API_KEY else '✗ no API key'}")
    log.info("═" * 65)

    from playwright.async_api import async_playwright

    # ── ETAPA 1: Scraping ──────────────────────────────────────────────────
    log.info("\n─── ETAPA 1: Collecting ads via Ad Library ───")
    all_ads = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        ctx = await browser.new_context(
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            viewport={"width": 1280, "height": 900},
        )
        page = await ctx.new_page()

        total_searches = len(COUNTRIES) * len(keywords)
        done = 0
        for country in COUNTRIES:
            for kw in keywords:
                done += 1
                log.info(f"  [{done:>2}/{total_searches}] [{country}] {kw}")
                ads = await _scrape_search_page(page, country, kw)
                log.info(f"    → {len(ads)} ads in date range")
                all_ads.extend(ads)
                await asyncio.sleep(DELAY_SEARCH)

        # Within-batch dedup by lib_id (or page+text fingerprint)
        seen_keys, unique = set(), []
        for ad in all_ads:
            key = ad["lib_id"] or (ad["page"] + ad["texto"][:40])
            if key not in seen_keys:
                seen_keys.add(key)
                unique.append(ad)

        log.info(f"\n  Total scraped: {len(all_ads)}  |  After within-batch dedup: {len(unique)}")

        # ── ETAPA 2: Creative Capture ─────────────────────────────────────
        log.info(f"\n─── ETAPA 2: Capturing creatives ({len(unique)} ads) ───")
        for i, ad in enumerate(unique, 1):
            label = ad["page"][:28] or "(no page)"
            log.info(f"  [{i:>2}/{len(unique)}] {label:<28} | lib={ad['lib_id'] or 'none'}")
            frames = await _capture_creative(page, ad)
            ad["frames"] = frames
            await asyncio.sleep(DELAY_CREATIVE)

        await browser.close()

    # Cross-run dedup — remove ads already in previous dated files
    prev_urls = dedup.load_existing_urls(exclude_date=date_str)
    new_ads   = [a for a in unique if not (a.get("url") and a["url"] in prev_urls)]
    dupes     = len(unique) - len(new_ads)
    log.info(f"\n  Cross-run duplicates removed: {dupes}  |  New ads: {len(new_ads)}")

    # ── ETAPA 3: Relevance Filter ──────────────────────────────────────────
    log.info(f"\n─── ETAPA 3: Relevance filter ({len(new_ads)} ads) ───")
    approved = _filter_relevance(new_ads)

    # ── ETAPA 4: Creative Analysis ─────────────────────────────────────────
    log.info(f"\n─── ETAPA 4: Creative analysis ({len(approved)} approved ads) ───")
    approved = _analyze_creatives(approved)

    # ── ETAPA 5: Cross-analysis ────────────────────────────────────────────
    log.info(f"\n─── ETAPA 5: Cross-ad pattern analysis ───")
    cross = _cross_analyze(approved)

    # ── ETAPA 6: Save + Push ───────────────────────────────────────────────
    log.info(f"\n─── ETAPA 6: Saving results and pushing to GitHub ───")
    _save_and_push(approved, cross, date_str)

    # ── ETAPA 7: Cache Bust ────────────────────────────────────────────────
    log.info(f"\n─── ETAPA 7: GitHub Pages cache bust ───")
    _cache_bust(date_str)

    # ── Final Summary ──────────────────────────────────────────────────────
    log.info("\n" + "═" * 65)
    log.info("  PIPELINE COMPLETE")
    log.info(f"  Scraped          : {len(all_ads)}")
    log.info(f"  After dedup      : {len(unique)}")
    log.info(f"  Cross-run dupes  : {dupes}")
    log.info(f"  Approved by AI   : {len(approved)}")

    if cross:
        log.info(f"  Dominant angle   : {cross.get('dominant_mechanism', '')}")
        log.info(f"  Market signal    : {cross.get('market_signal', '')}")
        avatars = cross.get("frequent_avatars", [])
        for av in avatars[:3]:
            log.info(f"  Avatar ({av.get('count','?')}x)      : {av.get('type','')}")

    log.info(f"\n  Data saved: data/{date_str}.json + latest.json")
    log.info(f"  Log saved : {_log_file}")
    log.info("═" * 65)

    # Print per-ad creative analysis to stdout
    if approved:
        log.info("\n  ── Per-ad creative analysis ──")
        for i, ad in enumerate(approved, 1):
            cr = ad.get("analise_criativa", {})
            log.info(
                f"\n  Ad {i}: [{ad['pais']}] {ad['page'] or '(no page)'}\n"
                f"    Text    : {ad['texto'][:80]}...\n"
                f"    Format  : {cr.get('format', '?')}\n"
                f"    Avatar  : {cr.get('avatar', '?')}\n"
                f"    Editing : {cr.get('editing', '?')}\n"
                f"    Highlight: {cr.get('highlight', '?')}"
            )

    return approved


if __name__ == "__main__":
    kw_override = sys.argv[1:] if len(sys.argv) > 1 else None
    if kw_override:
        log.info(f"TEST MODE — running with {len(kw_override)} keyword(s): {kw_override}")
    asyncio.run(_main(kw_override))
