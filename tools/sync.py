"""Build / sync the amazing-posters GitHub repo from the public posterlet.com API.

Layout (written to --out, default ./gh-repo):
  README.md                       hub: two-level index + prompt anatomy
  LICENSE                         CC BY 4.0 for the prompt text
  data/<bucket>/<sub>.jsonl       full records incl. prompt, split per subcollection
  gallery/<bucket>/<sub>.md       browsable 4-up grid, 40 per page (-2, -3 ...)
  tools/sync.py                   this script, copied into the repo so CI can re-run it
  .github/workflows/sync.yml      weekly refresh

Data source is the *public* API, so the CI job needs no credentials:
  /api/themes?limit=50                     -> theme slugs + counts
  /api/themes/<slug>?limit=100&page=N      -> stable, complete per-theme asset list
  /api/assets?limit=1000&page=N            -> random 1000-row sample, NOT a stable
                                              partition; union converges to `total`

Usage:
  python script/gh_build_repo.py --stats
  python script/gh_build_repo.py --out gh-repo --cache .cache/public_assets.json
"""
import argparse
import json
import math
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

SITE = "https://posterlet.com"
CDN = "https://files.posterlet.com/assets/generated"
REPO = "amazing-posters"
PAGE_SIZE = 40
MIN_PROMPT = 40
UA = {"User-Agent": "amazing-posters-sync/1.0 (+https://posterlet.com)"}

CI_WORKFLOW = """name: Sync posters


# Pulls every public poster from posterlet.com and rebuilds the galleries + data.
# Uses only the public API, so no secrets are required.
on:
  schedule:
    - cron: "0 3 * * 1"
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: sync
  cancel-in-progress: false

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Rebuild from the public API
        id: build
        run: |
          out=$(python tools/sync.py --out .)
          echo "$out" | tail -5
          echo "total=$(echo "$out" | grep -o 'TOTAL=[0-9]*' | cut -d= -f2)" >> "$GITHUB_OUTPUT"
      - name: Commit if anything changed
        run: |
          if [ -z "$(git status --porcelain)" ]; then
            echo "already up to date"
            exit 0
          fi
          git config user.name  "posterlet-sync"
          git config user.email "sync@posterlet.com"
          git add -A
          git commit -m "Sync ${{ steps.build.outputs.total }} poster specs ($(date -u +%Y-%m-%d))"
          git push
"""

# --------------------------------------------------------------- taxonomy
PRODUCT_SUBS = [
    ("beauty", "Beauty & Skincare", [
        "skincare", "beauty", "cosmetics", "makeup", "lipstick", "serum", "cream",
        "perfume", "fragrance", "toner", "cleanser", "moisturizer", "sunscreen",
        "shampoo", "mascara", "foundation", "nail"]),
    ("food-drink", "Food & Drink", [
        "food", "fruit", "produce", "seafood", "snack", "tea", "coffee", "beverage",
        "drink", "juice", "wine", "meat", "vegetable", "bakery", "dessert",
        "sauce", "milk", "rice", "noodle", "candy", "chocolate"]),
    ("apparel", "Apparel & Accessories", [
        "clothing", "apparel", "wear", "shirt", "dress", "jacket", "shoe", "sneaker",
        "bag", "jewelry", "sunglasses", "hat", "handbag", "sweater", "hoodie",
        "sock", "scarf"]),
    ("electronics", "Electronics", [
        "earbuds", "headphone", "phone", "laptop", "speaker", "camera", "charger",
        "smartwatch", "monitor", "keyboard", "gadget", "tablet", "drone",
        "earphone", "power bank"]),
    ("home-appliance", "Home & Kitchen Appliances", [
        "appliance", "vacuum", "blender", "cooker", "kettle", "purifier", "heater",
        "microwave"]),
    ("home-living", "Home & Living", [
        "furniture", "chair", "lamp", "lighting", "bedding", "pillow", "towel",
        "decor", "mattress", "sofa", "curtain", "rug", "storage"]),
    ("health", "Health & Wellness", [
        "supplement", "vitamin", "protein", "medicine", "wellness", "massage",
        "fitness", "nutrition", "health"]),
    ("baby-kids", "Baby & Kids", [
        "baby", "infant", "kid", "children", "toy", "formula", "nursery",
        "toddler"]),
    ("general", "General Products", None),
]

GIG_SUBS = [
    ("web-app", "Web & App Development", [
        "web design", "website", "web development", "wordpress", "shopify",
        "landing page", "e-commerce", "online store", "mobile app",
        "app development", "frontend", "html"]),
    ("design-brand", "Design & Branding", [
        "brand identity", "logo", "branding", "graphic design", "illustration",
        "packaging", "business card", "ux", "ui"]),
    ("marketing-seo", "Marketing & SEO", [
        "digital marketing", "seo", "social media", "ads", "email", "funnel",
        "advertising"]),
    ("data-analytics", "Data & Analytics", [
        "data visualization", "dashboard", "analytics", "excel", "power bi",
        "tableau", "data analysis"]),
    ("video-anim", "Video & Animation", [
        "video editing", "animation", "motion", "explainer", "youtube"]),
    ("audio", "Audio & Podcast", [
        "podcast", "voice over", "audio", "music", "mixing", "sound"]),
    ("writing-biz", "Writing & Business", [
        "pitch deck", "business plan", "research", "copywriting", "blog",
        "translation", "resume", "book"]),
    ("photo-3d", "Photo & 3D", [
        "product photography", "photo", "retouch", "3d", "render"]),
    ("general", "General Services", None),
]

SALE_KW = ["sale", "discount", "offer", "deal", "promo", "price", "black friday",
           "cyber monday", "clearance", "coupon", "markdown"]
EVENT_KW = ["party", "event", "concert", "festival", "invite", "invitation",
            "club", "parade", "carnival", "trick or treat", "gathering",
            "celebration", "contest"]

BUCKETS = [
    dict(key="halloween", theme="halloween", theme_slug="halloween-poster-designs", name="Halloween Posters",
         blurb="Spooky sale, party and event posters for October campaigns.",
         subs=[("sale", "Sales & Discounts", SALE_KW),
               ("event", "Events & Parties", EVENT_KW),
               ("atmosphere", "Greeting & Decor", None)]),
    dict(key="black-friday", theme="black friday sale", theme_slug="black-friday-sale-posters", name="Black Friday & Cyber Monday",
         blurb="High-contrast discount posters built for peak sale season.",
         single=("sale", "Sale Posters")),
    dict(key="christmas", theme="christmas", theme_slug="christmas-sale-and-event-poster-designs", name="Christmas & Holiday",
         blurb="Festive retail, greeting and event posters for the holiday season.",
         subs=[("sale", "Sales & Discounts", SALE_KW),
               ("event", "Events & Parties", EVENT_KW),
               ("atmosphere", "Greeting & Decor", None)]),
    dict(key="infographic", theme="infographic", theme_slug="infographic", name="Infographics",
         blurb="Data storytelling layouts: process, comparison, timeline, anatomy.",
         single=("data-visualization", "Data Visualization")),
    dict(key="product-thumbnails", theme="product thumbnail", theme_slug="product-thumbnails", name="Product Thumbnails",
         blurb="E-commerce main images and listing thumbnails on clean grounds.",
         subs=PRODUCT_SUBS),
    dict(key="gig-covers", theme="gig cover", theme_slug="fiverr-gig-cover", name="Gig Covers",
         blurb="Marketplace service covers for freelancers and studios.", subs=GIG_SUBS),
]
FALLBACK = dict(key="poster-designs", name="Other Poster Designs",
                blurb="Campaign, brand and editorial posters outside the six main collections.")
THEME_MAP = {b["theme"]: b for b in BUCKETS}
THEME_SLUG_MAP = {b["theme_slug"]: b for b in BUCKETS}
BY_KEY = {b["key"]: b for b in BUCKETS}


# -------------------------------------------------------------------- net
def http_json(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001 - network flake, retry
            last = e
            time.sleep(2 + i * 3)
    raise RuntimeError(f"GET {url} failed: {last}")


def fetch_themes():
    d = http_json(f"{SITE}/api/themes?limit=50")
    return d.get("data") or []


def fetch_theme_members():
    """theme slug -> set(asset id). Theme pagination IS stable and complete."""
    owner = {}
    themes = fetch_themes()
    for t in themes:
        slug, name = t["slug"], str(t.get("name") or t["slug"])
        total = int(t.get("total") or t.get("assetCount") or 0)
        found, page = 0, 1
        while page <= 200:
            d = http_json(f"{SITE}/api/themes/{urllib.parse.quote(slug)}?limit=100&page={page}")
            imgs = (d.get("data") or {}).get("images") or []
            if not imgs:
                break
            for x in imgs:
                owner[x["id"]] = slug
            found += len(imgs)
            if total and found >= total:
                break
            page += 1
        print(f"  theme {name:42s} {found:5d} assets")
    if not owner:
        print("  WARNING: the theme endpoint returned nothing; pass --theme-map to reuse a local map")
    return owner


def load_theme_map(path):
    raw = json.load(open(path, encoding="utf-8"))
    return {int(k): v for k, v in raw.items()}


def save_theme_map(path, owner):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    json.dump({str(k): v for k, v in owner.items()},
              open(path, "w", encoding="utf-8"), ensure_ascii=False)


def fetch_assets(load=None, save=None, max_extra=6):
    """`limit` is honoured but `page` is not: page N returns a fresh random slice,
    so paging yields ~35% duplicates. One oversized limit gets everything, and if
    the server ever caps it we top up with a few extra draws and dedupe by id."""
    if load and os.path.exists(load):
        rows = json.load(open(load, encoding="utf-8"))
        print(f"  cache {load}: {len(rows)} assets")
        return rows, len(rows)
    d = http_json(f"{SITE}/api/assets?limit=5000")
    total = int(d.get("total") or 0)
    seen = {x["id"]: x for x in (d.get("data") or [])}
    print(f"  bulk call: {len(seen)}/{total} assets")
    extra = 0
    while total and len(seen) < total and extra < max_extra:
        extra += 1
        d = http_json(f"{SITE}/api/assets?limit=5000&page={extra + 1}")
        for x in (d.get("data") or []):
            seen.setdefault(x["id"], x)
        print(f"  top-up {extra}: {len(seen)}/{total}", flush=True)
    rows = list(seen.values())
    if save:
        os.makedirs(os.path.dirname(save) or ".", exist_ok=True)
        json.dump(rows, open(save, "w", encoding="utf-8"), ensure_ascii=False)
    return rows, total


# ---------------------------------------------------------------- helpers
def as_list(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip():
        try:
            p = json.loads(v)
            return p if isinstance(p, list) else [v]
        except Exception:
            return [v]
    return []


def prepare(rows, owner):
    out = []
    for r in rows:
        if r.get("status") not in (None, "completed"):
            continue
        if r.get("assetType") not in (None, "image"):
            continue
        if r.get("isPrivate") in (1, True):
            continue
        slug = (r.get("slug") or "").strip()
        prompt = (r.get("prompt") or "").strip()
        fname = (r.get("fileName") or "").strip()
        if not slug or not prompt or not fname:
            continue
        if len(prompt) < MIN_PROMPT:  # "yellow cat" is not a spec
            continue
        r["slug"], r["prompt"], r["fileName"] = slug, prompt, fname
        r["tags"] = [str(t) for t in as_list(r.get("tags")) if str(t).strip()]
        r["_theme"] = owner.get(r["id"])
        out.append(r)
    return out


def reduce_ratio(w, h):
    if not w or not h:
        return ""
    g = math.gcd(int(w), int(h))
    a, b = int(w) // g, int(h) // g
    if a > 40 or b > 40:
        common = [(9, 16), (2, 3), (3, 4), (4, 5), (1, 1), (16, 9),
                  (21, 9), (4, 3), (5, 4), (3, 2), (2, 1), (9, 21)]
        target = w / h
        a, b = min(common, key=lambda r: abs(r[0] / r[1] - target))
    return f"{a}:{b}"


def match(tags, keywords):
    """Word-level match, so 'tea' does not fire on 'steak'."""
    toks, phrases = set(), []
    for t in tags:
        t = str(t).lower()
        phrases.append(t)
        toks.update(re.findall(r"[a-z0-9]+", t))
    for k in keywords:
        if " " in k:
            if any(k in p for p in phrases):
                return True
        elif k in toks:
            return True
    return False


def subs_of(bucket):
    """Every collection is a directory, so every collection needs at least one sub.
    Homogeneous ones (black friday, infographics) declare a `single` sub instead."""
    if bucket.get("single"):
        return [bucket["single"]]
    return bucket.get("subs") or []


def classify(theme_key, tags):
    """theme_key is a posterlet theme slug (or legacy name) -> (bucket, sub, label).
    Assets with no theme are dropped: they belong to no collection."""
    key = str(theme_key or "").strip().lower()
    bucket = THEME_SLUG_MAP.get(key) or THEME_MAP.get(key)
    if bucket is None:
        return None, None, None
    if bucket.get("single"):
        return bucket["key"], bucket["single"][0], bucket["single"][1]
    subs = bucket.get("subs") or []
    if not subs:
        return bucket["key"], None, None
    for key, label, kws in subs:
        if kws is None or match(tags, kws):
            return bucket["key"], key, label
    return bucket["key"], subs[-1][0], subs[-1][1]


def score(a):
    p, s = a["prompt"], 0.0
    s += 3 if "[Format]" in p else 0
    s += 2 if "[Layout]" in p else 0
    s += 2 if "[Subject]" in p else 0
    s += 1 if "[Colors]" in p else 0
    s += 1 if len(a["tags"]) >= 8 else 0
    s += 1 if max(a.get("width") or 0, a.get("height") or 0) >= 2048 else 0
    s += 1 if 20 <= len(a.get("title") or "") <= 60 else 0
    s += 2 if 900 <= len(p) <= 2600 else 0
    if re.search(r"\$\d", p):
        s -= 1.5
    if re.search(r"\b20(2[0-9])\b", p) or re.search(r"\b20(2[0-9])\b", a.get("title") or ""):
        s -= 1
    return s


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def collect(rows):
    kept = []
    for r in rows:
        r["_score"] = score(r)
        r["_bucket"], r["_sub"], r["_sub_label"] = classify(r["_theme"], r["tags"])
        if r["_bucket"]:
            kept.append(r)
    groups = defaultdict(list)
    for r in kept:
        groups[(r["_bucket"], r["_sub"])].append(r)
    for k in groups:
        groups[k].sort(key=lambda r: (-r["_score"], r["slug"]))
    return groups


def order_groups(groups):
    order = []
    for b in BUCKETS:
        for s in [x[0] for x in subs_of(b)]:
            if (b["key"], s) in groups:
                order.append((b["key"], s))
    return order


# ------------------------------------------------------------------ emit
def sub_name(bucket_key, sub):
    if sub is None:
        return BY_KEY.get(bucket_key, FALLBACK)["name"], None
    b = BY_KEY[bucket_key]
    if b.get("single") and b["single"][0] == sub:
        return b["name"], b["single"][1]
    for k, label, _kw in (b.get("subs") or []):
        if k == sub:
            return b["name"], label
    return bucket_key, sub.replace("-", " ").title()


def gpath(bucket_key, sub, part):
    base = sub if sub else bucket_key
    fname = f"{base}.md" if part == 1 else f"{base}-{part}.md"
    return f"gallery/{fname}" if sub is None else f"gallery/{bucket_key}/{fname}"


def dpath(bucket_key, sub):
    return f"data/{bucket_key}/{sub}.jsonl" if sub else f"data/{bucket_key}.jsonl"


def write_gallery(bucket_key, sub, chunk, part, n_pages, total_sub):
    name, label = sub_name(bucket_key, sub)
    blurb = BY_KEY.get(bucket_key, FALLBACK)["blurb"]
    up = "../" * (2 if sub else 1)
    title = f"{name} — {label}" if label else name
    base = sub or bucket_key

    out = [f"<h2>{title}</h2>", ""]
    if n_pages > 1:
        first = (part - 1) * PAGE_SIZE + 1
        nav = [f"<b>Part {part} of {n_pages}</b> — {first}–{first + len(chunk) - 1} of {total_sub}"]
        if part > 1:
            nav.append(f"[← Previous]({base}{'.md' if part == 2 else f'-{part - 1}.md'})")
        if part < n_pages:
            nav.append(f"[Next →]({base}-{part + 1}.md)")
        out += ["<p>" + " · ".join(nav) + "</p>", ""]

    out += [f"<p>{blurb} Every image links to a live, editable example on "
            f"<a href=\"{SITE}\">posterlet.com</a>. The prompt text for all "
            f"{total_sub} specs is in <a href=\"{up}{dpath(bucket_key, sub)}\">"
            f"{dpath(bucket_key, sub)}</a>. "
            f"<a href=\"{up}README.md\">All collections →</a></p>", "",
            '<table width="100%" style="table-layout: fixed;">']

    kind = label or name
    for i in range(0, len(chunk), 4):
        out.append("<tr>")
        for a in chunk[i:i + 4]:
            stem = os.path.splitext(a["fileName"])[0]
            page = f"{SITE}/poster/{a['slug']}"
            ratio = reduce_ratio(a.get("width"), a.get("height"))
            title_txt = a.get("title") or a["slug"].replace("-", " ").title()
            alt = esc(f"{title_txt} — {ratio} {kind} poster design".replace("  ", " "))
            tags = " · ".join(esc(t) for t in a["tags"][:4])
            out.append(f'<td valign="top" width="25%"><a id="{a["slug"]}"></a>')
            out.append(f'<a href="{page}"><img src="{CDN}/md/{stem}.webp" alt="{alt}" width="100%"></a>')
            out.append(f'<div style="margin-top: 8px;"><b>{esc(title_txt)}</b></div>')
            out.append(f'<div>{ratio + " · " if ratio else ""}<a href="{page}">Open on posterlet.com →</a></div>')
            out.append(f'<div><sub>{tags}</sub></div></td>')
        out.append("</tr>")
    out.append("</table>")
    if n_pages > 1 and part < n_pages:
        out += ["", f"<p>[Next →]({base}-{part + 1}.md)</p>"]
    return "\n".join(out) + "\n"


def record(a):
    stem = os.path.splitext(a["fileName"])[0]
    return {
        "slug": a["slug"],
        "title": a.get("title") or a["slug"].replace("-", " ").title(),
        "collection": a["_bucket"],
        "subcollection": a["_sub"],
        "theme": a.get("_theme"),
        "ratio": reduce_ratio(a.get("width"), a.get("height")),
        "width": a.get("width"),
        "height": a.get("height"),
        "style": a.get("style"),
        "model": a.get("modelName"),
        "tags": a["tags"],
        "prompt": a["prompt"],
        "image_md": f"{CDN}/md/{stem}.webp",
        "image_lg": f"{CDN}/lg/{stem}.webp",
        "image_full": f"{CDN}/full/{stem}.webp",
        "page": f"{SITE}/poster/{a['slug']}",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="gh-repo")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--cache", default="", help="path to save / reuse a fetched asset dump")
    ap.add_argument("--use-cache", action="store_true", help="reuse --cache instead of refetching")
    ap.add_argument("--with-ci", action="store_true", help="also emit .github/workflows/sync.yml")
    ap.add_argument("--theme-map", default="", help="cache file for the id -> theme mapping")
    args = ap.parse_args()
    OUT = os.path.abspath(args.out)

    if args.use_cache and args.theme_map and os.path.exists(args.theme_map):
        owner = load_theme_map(args.theme_map)
        print(f"theme map {args.theme_map}: {len(owner)} assets")
    else:
        print("fetching themes ...")
        owner = fetch_theme_members()
        if args.theme_map and owner:
            save_theme_map(args.theme_map, owner)
    print("fetching assets ...")
    rows, total = fetch_assets(load=args.cache if args.use_cache else None,
                               save=args.cache or None)
    print(f"api total {total}, sampled {len(rows)}")
    rows = prepare(rows, owner)
    print(f"usable {len(rows)} (public, completed images with slug + prompt)")
    groups = collect(rows)
    order = order_groups(groups)
    n_total = sum(len(groups[k]) for k in order)
    n_pages = sum(math.ceil(len(groups[k]) / PAGE_SIZE) for k in order)
    print(f"TOTAL={n_total} COLLECTIONS={len(order)} PAGES={n_pages}")
    for k in order:
        name, label = sub_name(*k)
        n = len(groups[k])
        print(f"  {k[0]:20s} {str(k[1]):14s} {n:5d}  {math.ceil(n / PAGE_SIZE):3d}p  {label or name}")
    if args.stats:
        return

    # only generated paths are wiped; .git/.github/tools survive
    for p in ["gallery", "data"]:
        shutil.rmtree(os.path.join(OUT, p), ignore_errors=True)
    os.makedirs(os.path.join(OUT, "gallery"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "data"), exist_ok=True)

    index = []
    for bucket_key, sub in order:
        items = groups[(bucket_key, sub)]
        npages = math.ceil(len(items) / PAGE_SIZE)
        name, label = sub_name(bucket_key, sub)
        for part in range(1, npages + 1):
            rel = gpath(bucket_key, sub, part)
            full = os.path.join(OUT, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            open(full, "w", encoding="utf-8", newline="\n").write(
                write_gallery(bucket_key, sub, items[(part - 1) * PAGE_SIZE: part * PAGE_SIZE],
                              part, npages, len(items)))
        index.append((bucket_key, sub, name, label, len(items), npages, gpath(bucket_key, sub, 1)))

    # data/<bucket>/<sub>.jsonl — one file per subcollection so no blob is too
    # large for GitHub's web viewer, and the name says what is inside.
    data_rows = []
    for bucket_key, sub in order:
        items = groups[(bucket_key, sub)]
        rel = dpath(bucket_key, sub)
        full = os.path.join(OUT, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            for a in items:
                f.write(json.dumps(record(a), ensure_ascii=False) + "\n")
        data_rows.append((rel, len(items), os.path.getsize(full)))

    lines, cur = [], None
    for bucket_key, sub, name, label, n, npages, rel in index:
        if bucket_key != cur:
            cur = bucket_key
            here = [x for x in index if x[0] == bucket_key]
            tot = sum(x[4] for x in here)
            sole = len(here) == 1          # one sub -> link the collection row itself
            head = f"**[{name}]({rel})**" if sole else f"**{name}**"
            lines.append(f"| {head} | | {tot} |")
        if not sole:
            lines.append(f"| | [{label}]({rel}) | {n} ({npages}p) |")
    rows_md = "\n".join(lines)

    lines = []
    cur = None
    for rel, n, sz in data_rows:
        col = rel.split("/")[1] if rel.count("/") > 1 else rel[5:-6]
        if col != cur:
            cur = col
            name = BY_KEY.get(col, FALLBACK)["name"]
            tot = sum(x[1] for x in data_rows if (x[0].split("/")[1] if x[0].count("/") > 1 else x[0][5:-6]) == col)
            lines.append(f"| **{name}** | {tot} | |")
        label = rel.split("/")[2][:-6] if rel.count("/") > 1 else "all"
        lines.append(f"| | [`{rel}`]({rel}) | {sz/1e6:.2f} MB |")
    data_md = "\n".join(lines)

    hero = groups[order[0]][0]
    hero_stem = os.path.splitext(hero["fileName"])[0]
    hero_slug = hero["slug"]
    readme = f"""# {REPO}

**{n_total} poster prompt specs** — the exact structured text behind each image, paired with the
finished example. Free to copy, adapt and ship.

[![](https://img.shields.io/badge/site-posterlet.com-111)]({SITE})
[![](https://img.shields.io/badge/prompts-{n_total}-e02020)](data/)
[![](https://img.shields.io/badge/license-CC%20BY%204.0-blue)](LICENSE)

[![]({CDN}/md/{hero_stem}.webp)]({SITE}/poster/{hero_slug})

## What this is

Every poster on [posterlet.com]({SITE}) is generated from a structured prompt spec rather than a one-line
description. Posterlet is an SI (superintelligence) poster generator, and this repository publishes {n_total}
of the specs behind its output — the exact text that produced each image — so you can see how layout,
color, typography and subject are constrained separately, and copy the patterns into your own pipeline.

All prompt text lives in **[`data/`](data/)**, one JSON object per poster, split into one file per
subcollection. The galleries below are the browsable index: every thumbnail links to the live, editable
version.

| Collection | Records | File size |
|---|---|---|
{data_md}

Each record looks like this:

```json
{{"slug": "...", "title": "...", "collection": "halloween", "subcollection": "sale",
 "ratio": "9:16", "width": 1536, "height": 2752, "style": "3d", "tags": ["..."],
 "prompt": "[Format] ... [Colors] ... [Layout] ...",
 "image_md": ".../md/x.webp", "image_lg": "...", "image_full": "...",
 "page": "https://posterlet.com/poster/..."}}
```

Most specs are split into labelled sections, which is what makes the output reproducible:

| Section | What it controls |
|---|---|
| `[Format]` | aspect ratio, medium, overall style, what the image is for |
| `[Colors]` | named palette with hex values, contrast and background treatment |
| `[Layout]` | where each block sits, grid, hierarchy, negative space |
| `[Subject]` | people, products, scenes — wardrobe, pose, lighting |
| `[Headline]` / `[Copy]` | the literal text rendered into the image |
| `[Mood]` | tonal direction that ties the choices together |

The infographic collection is the exception: those specs are a single narrative paragraph, because a
whole-page diagram is easier to specify as one description than as independent blocks.

## Galleries

| Collection | Subcollection | Prompts |
|---|---|---|
{rows_md}

Pages hold at most {PAGE_SIZE} images, so a large subcollection continues as `-2.md`, `-3.md` and so on.

## Linking to a single poster

Every entry carries an anchor built from its slug, so any one poster can be cited directly:

`{index[0][6]}#{hero_slug}`

## Using these prompts

Copy a spec, swap the `[Subject]` and `[Headline]` blocks, keep the structure. The section headers are the
part that carries the weight — models follow `[Layout]` instructions far more reliably when the frame,
palette and subject are already pinned down by their own sections.

Text rendering (headlines, prices, tags) is the usual failure point: keep quoted copy short, explicitly name
the type style, and state the position twice — once in `[Layout]`, once in `[Headline]`.

## Updates

This repository is generated, never hand-edited. `tools/sync.py` pulls every public poster from the
posterlet.com API and rebuilds the files; a scheduled GitHub Action re-runs it weekly.

## License

Prompt text is licensed [CC BY 4.0](LICENSE) — use it commercially, just credit
[posterlet.com]({SITE}). Example images are SI-generated and remain hosted on posterlet.com; they are shown
here for reference and are not included in the license.
"""
    open(os.path.join(OUT, "README.md"), "w", encoding="utf-8", newline="\n").write(readme)

    license_md = f"""CC BY 4.0 — Creative Commons Attribution 4.0 International

The prompt text in this repository (README.md, gallery/**, data/**) is licensed under
Creative Commons Attribution 4.0 International.

You are free to share and adapt the material for any purpose, including commercially, provided you give
appropriate credit, provide a link to the license, and indicate if changes were made.

Full legal code: https://creativecommons.org/licenses/by/4.0/legalcode

Suggested attribution:
  Poster prompts from posterlet.com ({SITE}), licensed CC BY 4.0.

Excluded from this license: the example poster images, which are SI-generated (superintelligence) and
hosted on posterlet.com. They are linked here for reference only.

Copyright (c) 2026 posterlet.com
"""
    open(os.path.join(OUT, "LICENSE"), "w", encoding="utf-8", newline="\n").write(license_md)

    # ship the generator itself so CI can refresh the repo without local help
    tools = os.path.join(OUT, "tools")
    os.makedirs(tools, exist_ok=True)
    shutil.copyfile(os.path.abspath(__file__), os.path.join(tools, "sync.py"))

    wf = os.path.join(OUT, ".github", "workflows")
    wf_file = os.path.join(wf, "sync.yml")
    if args.with_ci:
        os.makedirs(wf, exist_ok=True)
        open(wf_file, "w", encoding="utf-8", newline="\n").write(CI_WORKFLOW)
    elif os.path.exists(wf_file):
        os.remove(wf_file)  # keep the tree in sync when CI is turned off

    print(f"\nwrote {OUT}")
    print(f"  README.md, LICENSE, tools/sync.py")
    print(f"  data jsonl x{len(data_rows)} ({n_total} rows)")
    print(f"  gallery md x{n_pages}")


if __name__ == "__main__":
    main()
