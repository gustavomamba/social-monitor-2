"""
apify_tiktok_male.py — TikTok collection for male health niche via Apify.

Two sources:
  SOURCE 1 — Keyword/hashtag search (14 keywords, max 5 per kw)
  SOURCE 2 — Profile monitoring (4 profiles, max 50 videos each)

Both sources filter to min 80k views and tag nicho = "male_health".

Usage (from project root):
    python scripts/apify_tiktok_male.py
"""
import sys
import os
import json
import time
import urllib.request
from datetime import date, datetime

sys.stdout.reconfigure(encoding='utf-8')

# ── Load .env ────────────────────────────────────────────────────────────────
_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
if os.path.exists(_ENV):
    with open(_ENV, encoding='utf-8') as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dedup

# ── Config ───────────────────────────────────────────────────────────────────
APIFY_TOKEN       = os.environ.get('APIFY_TOKEN', '')
ACTOR_ID          = 'clockworks~tiktok-scraper'
MIN_VIEWS         = 80_000
KW_MAX_RESULTS    = 10   # videos per keyword
PROFILE_MAX       = 50   # videos per profile (filter by views after)
TODAY             = date.today()
NICHO             = 'male_health'

KEYWORDS = [
    'testosterone',
    'kegel',
    'erectile dysfunction',
    'premature ejaculation',
    'male performance',
    'testosterone boost',
    'kegel training',
    'men sexual health',
    'low testosterone',
    'kegel exercises',
    'desempenho masculino',
    'testosterona',
    'ereção',
    'ejaculação precoce',
]

PROFILES = [
    'https://www.tiktok.com/@the_coach_app',
    'https://www.tiktok.com/@dr.kegel.app',
    'https://www.tiktok.com/@kegelmenapp',
    'https://www.tiktok.com/@latteboy868',
    'https://www.tiktok.com/@saludmasculinametodo',
]


# ── Apify helpers ─────────────────────────────────────────────────────────────
def _api_post(url, body):
    data = json.dumps(body).encode('utf-8')
    req  = urllib.request.Request(
        url, data=data,
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _api_get(url):
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _poll_and_fetch(run_id):
    """Poll run until done, return dataset items."""
    status_url = f'https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_TOKEN}'
    st = ''
    for _ in range(30):
        time.sleep(10)
        status = _api_get(status_url)
        st = status.get('data', {}).get('status', '')
        if st in ('SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'):
            break
    if st != 'SUCCEEDED':
        return []
    dataset_id = status['data'].get('defaultDatasetId', '')
    items_url = (f'https://api.apify.com/v2/datasets/{dataset_id}/items'
                 f'?token={APIFY_TOKEN}&format=json&clean=true')
    items = _api_get(items_url)
    return items if isinstance(items, list) else []


def run_keyword(keyword):
    """Hashtag search for one keyword."""
    run_url = f'https://api.apify.com/v2/acts/{ACTOR_ID}/runs?token={APIFY_TOKEN}'
    body = {
        'hashtags':    [keyword.replace(' ', '')],
        'resultsType': 'videos',
        'maxResults':  KW_MAX_RESULTS,
    }
    run = _api_post(run_url, body)
    run_id = run.get('data', {}).get('id', '')
    return _poll_and_fetch(run_id) if run_id else []


def run_profile(profile_url):
    """Profile scrape — returns up to PROFILE_MAX videos."""
    run_url = f'https://api.apify.com/v2/acts/{ACTOR_ID}/runs?token={APIFY_TOKEN}'
    body = {
        'profiles':    [profile_url],
        'resultsType': 'videos',
        'maxResults':  PROFILE_MAX,
    }
    run = _api_post(run_url, body)
    run_id = run.get('data', {}).get('id', '')
    return _poll_and_fetch(run_id) if run_id else []


# ── Item parser ───────────────────────────────────────────────────────────────
def parse_item(item, source_label):
    views = int(item.get('playCount') or item.get('videoMeta', {}).get('playCount') or 0)
    if views < MIN_VIEWS:
        return None

    video_id  = item.get('id', '')
    author    = (item.get('authorMeta', {}) or {}).get('name', '') or \
                (item.get('author', {}) or {}).get('uniqueId', '')
    desc      = item.get('text', '') or item.get('desc', '')
    pub_ts    = item.get('createTime') or item.get('createTimeISO', '')
    thumbnail = (item.get('videoMeta', {}) or {}).get('coverUrl', '') or \
                item.get('covers', {}).get('default', '')

    # Prefer webVideoUrl (profile runs have it), fall back to constructing it
    url = item.get('webVideoUrl', '')
    if not url and video_id and author:
        url = f'https://www.tiktok.com/@{author}/video/{video_id}'

    pub_date = ''
    dias = 0
    try:
        if isinstance(pub_ts, (int, float)):
            pub_date = datetime.fromtimestamp(pub_ts).strftime('%Y-%m-%d')
        elif isinstance(pub_ts, str) and pub_ts:
            pub_date = pub_ts[:10]
        if pub_date:
            dias = (TODAY - datetime.strptime(pub_date, '%Y-%m-%d').date()).days
    except Exception:
        pass

    return {
        'titulo':                desc[:200],
        'canal':                 author,
        'views':                 views,
        'likes':                 int(item.get('diggCount') or (item.get('stats') or {}).get('diggCount') or 0),
        'comentarios':           int(item.get('commentCount') or (item.get('stats') or {}).get('commentCount') or 0),
        'data':                  pub_date,
        'dias_desde_publicacao': dias,
        'url':                   url,
        'thumbnail':             thumbnail,
        'keyword':               source_label,
        'analise':               '',
        'nicho':                 NICHO,
    }


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    if not APIFY_TOKEN:
        print('ERROR: APIFY_TOKEN not set. Add it to .env file.')
        sys.exit(1)

    import sys as _sys
    profiles_only = '--profiles-only' in _sys.argv

    raw = []

    # ── SOURCE 1: Keywords ────────────────────────────────────────────────────
    if not profiles_only:
        print('── SOURCE 1: Keywords ──────────────────────────────────────────')
        print(f'   {len(KEYWORDS)} keywords | min {MIN_VIEWS:,} views | {KW_MAX_RESULTS} per keyword')
        print()
        for i, kw in enumerate(KEYWORDS, 1):
            print(f'  [{i:>2}/{len(KEYWORDS)}] {kw:<30}', end=' ', flush=True)
            try:
                items  = run_keyword(kw)
                parsed = [parse_item(x, kw) for x in items]
                parsed = [p for p in parsed if p]
                raw.extend(parsed)
                print(f'→ {len(parsed)} videos')
            except Exception as e:
                print(f'→ ERROR: {e}')
            time.sleep(2)

    # ── SOURCE 2: Profiles ────────────────────────────────────────────────────
    print()
    print('── SOURCE 2: Profiles ──────────────────────────────────────────')
    print(f'   {len(PROFILES)} profiles | min {MIN_VIEWS:,} views | up to {PROFILE_MAX} per profile')
    print()
    for i, profile_url in enumerate(PROFILES, 1):
        handle = profile_url.split('@')[-1]
        print(f'  [{i}/{len(PROFILES)}] @{handle:<25}', end=' ', flush=True)
        try:
            items  = run_profile(profile_url)
            parsed = [parse_item(x, f'profile:{handle}') for x in items]
            parsed = [p for p in parsed if p]
            raw.extend(parsed)
            print(f'→ {len(parsed)} videos (from {len(items)} fetched)')
        except Exception as e:
            print(f'→ ERROR: {e}')
        time.sleep(2)

    # ── Dedup across both sources ─────────────────────────────────────────────
    seen, batch = set(), []
    for v in sorted(raw, key=lambda x: x['views'], reverse=True):
        if v['url'] and v['url'] not in seen:
            seen.add(v['url'])
            batch.append(v)

    print(f'\n  Total unique videos (≥{MIN_VIEWS:,} views): {len(batch)}')

    if batch:
        print('\n── Results ─────────────────────────────────────────────────────')
        print(f'  {"Views":>9}  {"Canal":<22}  {"Title":<40}  Source')
        print(f'  {"-"*9}  {"-"*22}  {"-"*40}  {"-"*20}')
        for v in batch:
            print(f'  {v["views"]:>9,}  {v["canal"][:22]:<22}  {v["titulo"][:40]:<40}  {v["keyword"]}')
    else:
        print('\n  No videos passed all filters.')

    # ── Save: merge into tiktok array, preserving weight_loss and other platforms ──
    import os as _os, json as _json
    _latest_path = _os.path.join(dedup.DATA_DIR, 'latest.json')
    _existing = {}
    try:
        with open(_latest_path, encoding='utf-8') as _f:
            _existing = _json.load(_f)
    except Exception:
        pass

    # Keep existing tiktok items that are NOT male_health (weight_loss + untagged)
    existing_tiktok = _existing.get('tiktok', [])
    weight_loss_tiktok = [x for x in existing_tiktok if x.get('nicho') != 'male_health']

    payload = {
        'data_execucao': datetime.now().strftime('%d/%m/%Y %H:%M'),
        'youtube':  _existing.get('youtube',  []),
        'tiktok':   weight_loss_tiktok + batch,
        'facebook': _existing.get('facebook', []),
        'trends':   _existing.get('trends',   []),
        'analise':  _existing.get('analise',  {
            'tendencias':         '',
            'mecanismos_em_alta': '',
            'avatares_em_alta':   '',
            'recomendacoes':      '',
        }),
    }

    stats = dedup.save(payload, verbose=True)
    date_str = TODAY.strftime('%Y-%m-%d')
    print(f'\n  Saved → {stats.get("date_file", "")} + latest.json')

    # ── Git commit + push ─────────────────────────────────────────────────────
    import subprocess as _sub
    _project_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    try:
        _os.chdir(_project_dir)
        _sub.run(['git', 'add', '-f', 'data/'], check=True, capture_output=True, text=True)
        r = _sub.run(
            ['git', 'commit', '-m', f'male health tiktok {date_str}'],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            print(f'  Git commit: {r.stdout.strip()}')
        elif 'nothing to commit' in (r.stdout + r.stderr):
            print('  Git: nothing to commit')
        else:
            print(f'  Git commit warning: {r.stderr.strip()}')
        _sub.run(['git', 'push'], check=True, capture_output=True, text=True)
        print('  Git push: OK')
    except _sub.CalledProcessError as e:
        print(f'  Git error: {e.stderr}')
