#!/usr/bin/env python3
"""One static page per available piece, at /product/<id>/.

WHY THIS EXISTS

Every share link Loupe produced used to be dead on the web. The app's external
product share sent a friend straight to the BRAND's storefront, so the person
who received it had no idea where the piece came from and no way to install
Loupe; and /product/<id> was declared in the Universal Links association file
without a single page behind it, so a tap on a shared link from a phone WITHOUT
Loupe installed landed on a 404.

These pages close that loop. On a phone with Loupe installed, iOS matches the
URL against /.well-known/apple-app-site-association and opens the app before the
page is ever fetched. On every other device the page renders the piece — image,
brand, price, sizes — with a link to buy it direct from the brand and a Smart App
Banner + CTA for Loupe. Because the page carries og:image, the piece's own
photograph is what previews in iMessage, WhatsApp and Instagram DMs, which is the
entire reason a share gets opened at all.

DESIGN RULES (they are load-bearing, do not relax them casually)

  * DETERMINISTIC. Nothing time-varying goes on a page — no build timestamp, no
    lastSeenAt, no "updated" line. The workflow rebuilds daily and commits only
    when something actually changed, so a non-deterministic byte anywhere would
    produce a 7,800-file commit every single morning.
  * SMALL. One shared stylesheet at /product/p.css; every page well under 3 KB.
    7,800 pages live in a git repo that GitHub Pages has to publish.
  * AVAILABLE ONLY. A page exists exactly while the piece is on sale. When it
    goes, the directory is deleted and the site's 404.html router says so
    ("this piece has sold out or left the shelf") with a route back into Loupe.
  * COPY. No "AI", no "algorithm", no "recommend", no "personalised". Flat
    colours, no gradients.

USAGE
    python tools/build_product_pages.py [--catalog PATH|URL] [--dry-run]
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request

CATALOG_URL = "https://cdn.jsdelivr.net/gh/HOboGoblin45/loupe-feed@main/loupe-feed/catalog.json"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "product")

SITE = "https://useloupe.shop"
APPSTORE = "https://apps.apple.com/app/id6781137336"
APP_ID = "6781137336"

# Words that must never appear in customer-facing copy on this site.
BANNED = re.compile(r"\b(a\.?i\.?|algorithm|algorithms|recommend\w*|personali[sz]\w*)\b", re.I)

MAX_SIZES_SHOWN = 12


# ── helpers ──────────────────────────────────────────────────────────────────


def brand_slug(brand: str) -> str:
    """The /brands/ directory slug convention (kept identical for URL stability:
    SIEDRES -> siedr-s, With Jean -> with-j-an, Bec + Bridge -> bec-plus-bridge)."""
    s = brand.lower().replace("’", "").replace("'", "").replace("+", " plus ")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def e(s) -> str:
    """HTML-escape, quotes included."""
    return html.escape("" if s is None else str(s), quote=True)


def path_seg(pid: str) -> str:
    """The id as it appears inside a URL. Ids are mostly ASCII slugs, but ~270
    carry accents (dôen-…, siedrés-…); those are percent-encoded in links while
    the directory on disk keeps the raw UTF-8 name, so the URL the app builds
    with encodeURIComponent resolves to the file GitHub Pages serves."""
    return urllib.parse.quote(pid, safe="")


WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def usable_id(pid: str) -> bool:
    """Reject anything that cannot be a directory name on both Windows and Linux."""
    if not pid or len(pid) > 120:
        return False
    if any(c in pid for c in '\\/:*?"<>|') or any(ord(c) < 32 for c in pid):
        return False
    if pid != pid.strip() or pid.endswith("."):
        return False
    if pid.split(".")[0].lower() in WINDOWS_RESERVED:
        return False
    return True


def money(price, currency="USD") -> str:
    try:
        n = int(round(float(price)))
    except (TypeError, ValueError):
        return ""
    return f"${n:,}" if currency == "USD" else f"${n:,}"


def clean_sizes(sizes) -> list:
    out, seen = [], set()
    for s in sizes or []:
        s = str(s).strip()
        if not s or len(s) > 14:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
        if len(out) >= MAX_SIZES_SHOWN:
            break
    return out


def load_catalog(src: str) -> dict:
    if src.startswith("http://") or src.startswith("https://"):
        req = urllib.request.Request(src, headers={"User-Agent": "loupe-site-builder"})
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    with open(src, encoding="utf-8") as f:
        return json.load(f)


# ── the shared stylesheet ────────────────────────────────────────────────────

STYLESHEET = """@import url("https://fonts.googleapis.com/css2?family=Beth+Ellen&family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&display=swap");
:root{--pink:#F3CBF0;--pink-soft:#FCEFF8;--ink:#141414;--muted:#6E6A6E;--line:#ECE7EC;--coral:#FE6F6F;--white:#FFFFFF;--paper:#FAF8F6;}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;color:var(--ink);background:var(--paper);line-height:1.55;-webkit-font-smoothing:antialiased;}
a{color:inherit;text-decoration:none;}
.wrap{max-width:1000px;margin:0 auto;padding:0 24px;}
.serif{font-family:"Fraunces",Georgia,serif;font-weight:500;letter-spacing:-.5px;}
.script{font-family:"Beth Ellen",cursive;font-weight:400;}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;background:var(--ink);color:var(--white);padding:13px 24px;border-radius:999px;font-size:15px;font-weight:600;transition:transform .14s ease;}
.btn:hover{transform:translateY(-2px);}
.btn-pink{background:var(--pink);color:var(--ink);}
.btn-ghost{background:transparent;color:var(--ink);border:1px solid var(--ink);}
header{border-bottom:1px solid var(--line);background:var(--paper);}
.nav{display:flex;align-items:center;justify-content:space-between;height:66px;}
.logo{font-size:23px;line-height:1.4;}
.nav .btn{padding:10px 20px;font-size:14px;}
.crumb{font-size:13px;color:var(--muted);padding:18px 0 0;}
.crumb a:hover{color:var(--ink);}
.p{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:34px;padding:22px 0 52px;align-items:start;}
@media(max-width:760px){.p{grid-template-columns:1fr;gap:22px;}}
.ph{aspect-ratio:3/4;background:var(--pink-soft);border:1px solid var(--line);border-radius:18px;overflow:hidden;}
.ph img{width:100%;height:100%;object-fit:cover;display:block;}
.bd{font-size:12px;letter-spacing:2px;text-transform:uppercase;color:var(--coral);font-weight:700;}
.d h1{font-size:clamp(26px,4vw,40px);letter-spacing:-1.1px;margin:8px 0 12px;}
.pr{font-size:22px;font-weight:600;letter-spacing:-.4px;}
.sz{margin:16px 0 4px;}
.sz .k{font-size:12px;letter-spacing:.4px;text-transform:uppercase;color:var(--muted);font-weight:700;margin-bottom:7px;}
.sz .row{display:flex;flex-wrap:wrap;gap:7px;}
.sz .row span{border:1px solid var(--line);background:var(--white);border-radius:999px;padding:5px 12px;font-size:13px;font-weight:600;}
.acts{display:flex;flex-direction:column;gap:10px;margin-top:24px;max-width:340px;}
.note{color:var(--muted);font-size:13px;margin-top:16px;max-width:46ch;}
.disclosure{padding:24px 0;border-top:1px solid var(--line);}
.disclosure p{text-align:center;font-size:12.5px;color:var(--muted);max-width:74ch;margin:0 auto;}
footer{padding:30px 0 52px;border-top:1px solid var(--line);}
.foot{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px;}
.foot .logo{font-size:26px;}
.foot-links{display:flex;gap:20px;font-size:14px;color:var(--muted);flex-wrap:wrap;}
.foot-links a:hover{color:var(--ink);}
"""

FOOTER = (
    '<section class=disclosure><div class=wrap><p><strong>Affiliate disclosure:</strong> '
    "Loupe may earn a commission on links here, at no extra cost to you. Prices and "
    "availability come from each brand and may change.</p></div></section>"
    '<footer><div class="wrap foot"><a href="/" class="logo script">Loupe</a>'
    '<nav class=foot-links><a href="/brands/">All brands</a>'
    f'<a href="{APPSTORE}">iPhone app</a>'
    '<a href="/privacy.html">Privacy</a><a href="/terms.html">Terms</a></nav>'
    "</div></footer>"
)

HEADER = (
    '<header><div class="wrap nav"><a href="/" class="logo script">Loupe</a>'
    f'<a href="{APPSTORE}" class="btn btn-pink">Get the app</a></div></header>'
)


# ── page ─────────────────────────────────────────────────────────────────────


def render(p: dict) -> str:
    pid = p["id"]
    seg = path_seg(pid)
    url = f"{SITE}/product/{seg}/"
    brand = (p.get("brand") or "").strip()
    name = (p.get("name") or "").strip() or "Piece"
    bslug = brand_slug(brand)
    img = (p.get("imageUrl") or "").strip()
    shop = (p.get("affiliateUrl") or "").strip()
    price = money(p.get("price"), p.get("currency") or "USD")
    sizes = clean_sizes(p.get("sizes"))

    og_title = f"{name} by {brand}" if brand else name
    title = f"{og_title} — {price} | Loupe" if price else f"{og_title} | Loupe"
    bits = [b for b in (price, ("Sizes " + ", ".join(sizes)) if sizes else "") if b]
    desc = f"{og_title}. " + ("".join(b + ". " for b in bits)) + "On Loupe — shop direct from the label."

    size_html = ""
    if sizes:
        chips = "".join(f"<span>{e(s)}</span>" for s in sizes)
        size_html = f'<div class=sz><div class=k>Available sizes</div><div class=row>{chips}</div></div>'

    shop_html = ""
    if shop:
        label = f"Shop at {brand}" if brand else "Shop this piece"
        shop_html = f'<a class=btn href="{e(shop)}" rel="noopener nofollow sponsored">{e(label)}</a>'

    brand_link = f'<a class=bd href="/brands/{e(bslug)}.html">{e(brand)}</a>' if brand and bslug else ""
    crumb_brand = f' / <a href="/brands/{e(bslug)}.html">{e(brand)}</a>' if brand and bslug else ""

    # Deliberately NO ld+json here. It would repeat the name, brand, price and the
    # 130-character image URL a second time on every one of ~7,800 pages for rich
    # results that a shelf this fast-moving will not be crawled quickly enough to
    # earn. The structured, crawlable surface is the /brands/ directory; this page
    # exists to open the app, preview well in a DM, and sell the piece.
    return (
        "<!DOCTYPE html><html lang=en><head>"
        '<meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">'
        f'<meta name=apple-itunes-app content="app-id={APP_ID}, app-argument=loupe://product/{e(seg)}">'
        "<meta name=referrer content=no-referrer>"
        f"<title>{e(title)}</title>"
        f'<meta name=description content="{e(desc)}">'
        '<link rel=icon href="/icon.png">'
        f'<link rel=canonical href="{e(url)}">'
        # og:description and og:url are omitted on purpose: every scraper that
        # matters falls back to <meta name=description> and the canonical URL,
        # and repeating them costs ~180 bytes on each of ~7,800 pages.
        "<meta property=og:type content=product>"
        f'<meta property=og:title content="{e(og_title)}">'
        f'<meta property=og:image content="{e(img)}">'
        "<meta property=og:site_name content=Loupe>"
        "<meta name=twitter:card content=summary_large_image>"
        '<link rel=stylesheet href="/product/p.css">'
        "</head><body>"
        + HEADER
        + f'<div class="wrap crumb"><a href="/">Loupe</a>{crumb_brand} / {e(name)}</div>'
        + '<main class="wrap p">'
        + f'<div class=ph>{f"""<img src="{e(img)}" alt="{e(og_title)}">""" if img else ""}</div>'
        + "<div class=d>"
        + brand_link
        + f'<h1 class=serif>{e(name)}</h1>'
        + f"<div class=pr>{e(price)}</div>"
        + size_html
        + "<div class=acts>"
        + shop_html
        + f'<a class="btn btn-ghost" href="{APPSTORE}">Get Loupe on the App Store</a>'
        + "</div>"
        + '<p class=note>Loupe is a swipe app for independent women’s fashion.</p>'
        + "</div></main>"
        + FOOTER
        + "</body></html>\n"
    )


# ── build ────────────────────────────────────────────────────────────────────


def write_if_changed(path: str, text: str, dry: bool) -> bool:
    data = text.encode("utf-8")
    if os.path.exists(path):
        with open(path, "rb") as f:
            if f.read() == data:
                return False
    if not dry:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--catalog", default=CATALOG_URL, help="catalog.json path or URL")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cat = load_catalog(args.catalog)
    products = cat.get("products") or []
    live = []
    seen = set()
    skipped = 0
    for p in products:
        if not p.get("available"):
            continue
        pid = p.get("id")
        if not isinstance(pid, str) or not usable_id(pid) or pid in seen:
            skipped += 1
            continue
        seen.add(pid)
        live.append(p)
    live.sort(key=lambda x: x["id"])

    os.makedirs(OUT_DIR, exist_ok=True)

    written = 0
    pages = 0
    total_bytes = 0
    biggest = 0
    biggest_id = ""
    for p in live:
        page = render(p)
        # Check LOUPE's copy, not the label's. A brand is free to call a piece
        # the "'AI Betrayed Me' T-shirt" (Conner Ives does); quoting a product
        # name is reporting, not marketing, so the piece's own name and brand
        # are removed before the ban is applied.
        chrome = re.sub(r"<script[^>]*>.*?</script>", " ", page, flags=re.S)
        chrome = re.sub(r"<[^>]+>", " ", chrome)
        chrome = re.sub(r"https?://\S+", " ", chrome)
        for own in (p.get("name") or "", p.get("brand") or ""):
            if own:
                chrome = chrome.replace(own, " ").replace(html.escape(own, quote=True), " ")
        if BANNED.search(chrome):
            raise SystemExit(f"banned word in generated copy for {p['id']!r}")
        pages += 1
        n = len(page.encode("utf-8"))
        total_bytes += n
        if n > biggest:
            biggest, biggest_id = n, p["id"]
        if write_if_changed(os.path.join(OUT_DIR, p["id"], "index.html"), page, args.dry_run):
            written += 1

    css_changed = write_if_changed(os.path.join(OUT_DIR, "p.css"), STYLESHEET, args.dry_run)

    # Remove pages for pieces that are no longer available. Old links are caught
    # by the site's 404.html router, which says the piece has left the shelf.
    keep = {p["id"] for p in live}
    removed = 0
    for entry in sorted(os.listdir(OUT_DIR)):
        full = os.path.join(OUT_DIR, entry)
        if not os.path.isdir(full):
            continue
        if entry not in keep:
            removed += 1
            if not args.dry_run:
                shutil.rmtree(full)

    avg = total_bytes // max(pages, 1)
    print(
        f"product pages: {pages} live  ({written} written/changed, {removed} removed, "
        f"{skipped} skipped)  css {'updated' if css_changed else 'unchanged'}  "
        f"total {total_bytes / 1048576:.2f} MB  avg {avg} B/page"
    )
    print(f"largest page: {biggest} B  ({biggest_id})")
    # The budget is on the AVERAGE. A handful of Shopify image URLs are 300+
    # characters on their own, and the page carries the URL because the whole
    # point of the page is that the piece previews in a DM — so the tail is
    # allowed to run over as long as the typical page does not.
    if avg >= 3072:
        print("FAIL: average page exceeds the 3 KB budget", file=sys.stderr)
        return 1
    if biggest >= 4096:
        print("WARNING: at least one page exceeds 4 KB", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
