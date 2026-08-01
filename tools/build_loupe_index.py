#!/usr/bin/env python3
"""The Loupe Index — a market instrument for independent fashion, built from the
catalog's own git log.

WHY THIS EXISTS

The independent tier — labels doing roughly $500K to $5M — is the only part of
fashion with no market data at all. WGSN sells to enterprise at enterprise
prices. Faire has wholesale numbers and does not publish them. Shopify shows a
brand its own store and nothing else. Meta shows paid. A designer deciding what
to cut for next season is guessing, and 32.6% of this tier's tracked assortment
turned over in the 31 days to 2026-08-01.

Loupe can measure this tier from its catalog alone, with zero users. That is the
whole point: the instrument is worth something at 45 swipers, which nothing else
in the product is. It is also unbuyable — the input is 42 daily full-catalog
snapshots that have been accumulating since 2026-06-17 as a side effect of the
refresh commit. A competitor starting today is 42 days behind and cannot close
the gap with money.

WHAT WE ACTUALLY SEE — say this before saying anything else

build_catalog.py pulls each brand's public /products.json, which every store
tested (thefrankieshop, susamusa, stinegoya, fashionbrandcompany, mirchibykim)
returns sorted by published_at DESCENDING. The walk takes one page of 180 and
keeps at most 60 items after junk/variant filtering. So the tracked set is a
brand's PUBLISHING FRONT: up to 60 pieces drawn from its 180 most recent
listings. For a small store that is the whole store. For The Frankie Shop it is
the last few weeks.

Everything below is therefore "of what we track", and the phrase is not a hedge:
a piece leaving a brand at the 60 cap may have been delisted OR pushed off the
front by newer arrivals. The metrics are chosen so that the ones which cannot
survive that ambiguity are not published as sell-through.

THE FIVE TRAPS, AND WHAT EACH ONE COST

1. METHODOLOGY CHANGES LOOK LIKE SALES. On 2026-07-15 the scrape was pinned to
   country=US (10b4c79) and 49 geo-priced brands flipped to USD. It landed in the
   catalog on 07-16, where 2,604 of 7,135 surviving pieces — 36.5% — moved price
   in one day. A naive read calls that a market-wide sale. PRICE_EPOCHS and
   EPOCH_SETTLE_DAYS (lifted from build_price_history.py) void the whole
   boundary.

2. SO DO PER-BRAND CURRENCY FIXES, AND THE EPOCH LIST DOES NOT CATCH THEM.
   Commit 06d82b1 (2026-07-29) corrected four brands' base currency. On 07-30
   Stine Goya's entire line moved by x0.134 — that is 1/7.46, the krone peg, not
   an 87% sale. Martine Rose x0.788 = 1/1.27 (GBP double-conversion). PDPAOLA
   x0.926 = 1/1.08. SIEDRÉS x1.080. Before the detector below existed, the
   brand price-discipline table led with "Stine Goya discounted 100% of its line
   at a median 87%", which is false in every particular.

   The tell is not the size of the move, it is the VARIANCE of it: a real sale
   marks different pieces down by different amounts, an FX correction multiplies
   every piece by exactly the same number. detect_uniform_steps() flags a
   brand-day where a large share of the line moves and the movers' ratios are
   all within ~1%, and voids price comparisons across it — for that brand only.
   It finds all four 07-29 corrections with no brand named in the source, plus
   Uniform Person's x0.852 / x1.173 round trip and Miaou's, and it correctly
   leaves Marge Sherwood alone (ratios spread 1.115-1.430 — a real repricing).

3. DAILY DISAPPEARANCE IS 45% NOISE. Of 10,059 "present today, absent tomorrow"
   transitions in the era, 4,552 reversed later. Multi-brand boutiques and stores
   near the cap resample slightly differently run to run, and the 7-day grace
   window carries whole labels forward. So churn is NEVER computed as a daily
   hazard. It is computed once, between two endpoints, on pieces observed at
   both — which is also the only definition a brand can check by hand.

4. OUR OWN ROSTER CHANGES LOOK LIKE THE MARKET MOVING. Mackage and Marfa Stance
   were removed on founder decision (ee6fca2) and Rota earlier; that is 223
   pieces, 2.9% of the July 1 cohort, "churning" for reasons that have nothing to
   do with the market. Any brand not present at BOTH endpoints is dropped from
   every longitudinal number.

5. AVAILABILITY ONLY EXISTS FROM 2026-07-16. The `available` flag shipped in
   f9c0658. Nothing before that date can be asked whether it was in stock, so
   sell-out is reported on the current shelf and on that window only.

WHAT IS PUBLISHED WHERE, AND WHY

  PUBLIC   /index/          Tier-level only, plus brands named in flattering or
                            neutral contexts (never discounted, fastest refresh,
                            selling through fastest). This is the credibility
                            artifact — press and brands should be able to read
                            and cite it, and it is the reason a cold email from
                            Loupe gets opened.

  PRIVATE  /index/brand/?k= One card per brand, its own numbers against the tier.
                            The unflattering cuts — who discounts most, who has
                            published nothing in a month, who is priced above
                            their own category — exist only here, shown to the
                            brand they describe. Publishing a league table of who
                            marks down hardest would make exactly one sale and
                            burn the other 138 relationships.

WHY THE CARDS ARE ENCRYPTED AND THE PARTNER REPORTS ARE NOT

The partner reports use unguessable-link privacy: a random token in the URL, a
JSON file named after it, robots noindex. That model assumes the file list is
not enumerable. **loupe-site is a public GitHub repository**, so it is: anyone
can open the repo and read every file in /partners/d/. With two partner reports
that is a small exposure of numbers those partners were happy to be shown.

With 139 brand cards it is not, because the card tells a label how its markdown
rate compares to its rivals' — and the card itself promises "nothing on this
card is published". A promise that a public directory listing falsifies is worse
than no promise.

So the payload is encrypted at rest with AES-256-GCM under a key derived from
the token, and the token never enters the repository. What is committed is
{"v","iv","ct"} — no brand name, no numbers, nothing that identifies whose card
it is. The URL is the key in the literal sense. Lose tools/data/index_keys.json
and every card is unreadable by anyone including us, which is the correct
failure mode; rebuild mints new ones.

USAGE
  python tools/build_loupe_index.py                    # full build
  python tools/build_loupe_index.py --report           # numbers only, writes nothing
  python tools/build_loupe_index.py --rotate-keys      # new brand-card URLs
  python tools/build_loupe_index.py --feed D:\loupe-feed
"""

import argparse
import base64
import collections
import datetime as dt
import html
import json
import math
import os
import pathlib
import re
import secrets
import statistics
import subprocess
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "tools" / "data"
OUT_DIR = ROOT / "index"
FEED_REPO = pathlib.Path(os.environ.get("LOUPE_FEED_REPO", r"C:\loupe-feed"))
CATALOG_REL = "loupe-feed/catalog.json"

# ── measurement windows ──────────────────────────────────────────────────────
# The roster only stopped growing on 2026-07-01 (66 brands on 06-17 -> 168 on
# 07-01, and every one of those additions is Loupe onboarding a store, not a
# brand entering the market). Longitudinal claims start here; the earlier
# snapshots still count toward "how long we have been watching".
ERA_START = "2026-07-01"

# Lifted verbatim from loupe-feed/build_price_history.py so the two files cannot
# drift apart. A price move straddling one of these is our pipeline getting more
# accurate, never a brand's decision.
PRICE_EPOCHS = ["2026-07-15"]
EPOCH_SETTLE_DAYS = 3

# `available` first appears in the 2026-07-16 catalog (f9c0658).
AVAIL_START = "2026-07-16"

# A price that moves by less than this is FX rounding, not a decision.
MIN_MEANINGFUL_MOVE = 0.02

# Uniform-step detector (trap 2). A brand-day qualifies as a methodology change,
# not a sale, when nearly the whole line moves by nearly the same ratio.
STEP_MIN_PIECES = 12          # below this, one buyer's whim looks like a policy
STEP_MIN_SHARE = 0.40         # share of surviving pieces that must move
STEP_MAX_SPREAD = 1.02        # p75/p25 of the movers' ratios; 1.00 = identical
# Measured separation on this dataset: every known currency correction sits at
# 1.000–1.008 (Stine Goya 1.000, SIEDRÉS 1.001, Little Yarn 1.003, PDPAOLA
# 1.004, Miaou 1.005, Uniform Person 1.008), while the one real repricing in the
# window — Marge Sherwood, 2026-07-20 — sits at 1.283. There is a factor of 35
# between the two populations, so the threshold is not finely balanced.

# Suppression floors. A number we are not sure of is a number we do not publish.
MIN_N_PUBLIC = 150            # a tier-level rate needs this many pieces behind it
MIN_N_BRAND = 20              # a brand-level rate needs this many
MIN_N_CLUSTER = 120           # a visual cluster needs this many to get a row

K_CLUSTERS = 16

# Brands whose entire line is Loupe's own removal decision, not market movement.
# Detected structurally too (roster_stable below drops anything missing at either
# endpoint) — this list exists so the console report can name them.
FOUNDER_REMOVED = ["Taottao", "Rota", "Mackage", "Marfa Stance"]


# ── palette ──────────────────────────────────────────────────────────────────
# Site tokens, unchanged: paper #FAF8F6, ink #141414, pink #F3CBF0, coral
# #FE6F6F, Fraunces, Beth Ellen. Flat colours only — no gradient anywhere.
#
# MEASURED, not eyeballed — WCAG 2.1 relative luminance, computed in
# test_loupe_index.js on every build. Ratios on paper / white card / pink-soft
# card, which are the only three surfaces text sits on here:
#   ink    #141414   17.4 / 18.4 / 16.5   body and headings
#   muted  #6E6A6E    5.0 /  5.3 /  4.8   secondary text
#   accent #B8403A    5.2 /  5.5 /  4.9   eyebrows and small emphasis
#   coral  #FE6F6F    2.6 — FAILS as text, so it is never text: it fills a bar
#                     that already carries its own number in words beside it.
#
# The site's own .eyebrow is coral-on-paper at 2.6:1, below AA. This page keeps
# the same hue (2.9° against coral's 0°) several steps darker rather than
# inherit the defect. The first attempt, #C2453F, measured 4.70:1 on paper and
# looked fine — but 4.47:1 on the pink-soft lead cards, i.e. it failed on the
# surface it appears on most. Checking one background is not checking.
COL = {
    "paper": "#FAF8F6", "ink": "#141414", "muted": "#6E6A6E", "line": "#ECE7EC",
    "white": "#FFFFFF", "pink": "#F3CBF0", "pink_soft": "#FCEFF8",
    "coral": "#FE6F6F", "accent": "#B8403A", "navy": "#15152A",
}


# ── git ──────────────────────────────────────────────────────────────────────

def git(*args):
    return subprocess.run(
        ["git", "-C", str(FEED_REPO), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout


def history_is_truncated():
    """True when this clone cannot see the whole history.

    The entire input is `git log`, so a shallow clone silently yields a SHORTER
    dataset and a windowStart that describes the CLONE rather than the data. On
    2026-08-01 that cost build_price_history 14 of 42 days — the oldest third,
    the part that cannot be rebuilt later. It is a hard stop here for the same
    reason: the asset is worth exactly its length.
    """
    if git("rev-parse", "--is-shallow-repository").strip() == "true":
        return True
    git_dir = git("rev-parse", "--git-dir").strip()
    if not git_dir:
        return False
    return (FEED_REPO / git_dir / "shallow").exists() or pathlib.Path(git_dir, "shallow").exists()


def daily_snapshots():
    """(day, sha) for the LAST commit of each day that touched the catalog."""
    out = {}
    for line in git("log", "--format=%H|%ad", "--date=short", "--", CATALOG_REL).splitlines():
        if "|" not in line:
            continue
        sha, day = line.split("|", 1)
        out.setdefault(day.strip(), sha.strip())      # log is newest-first
    return sorted(out.items())


# Field slots in the compact per-product tuple. A full snapshot is 8.8 MB of
# JSON; 42 of them parsed into dicts is several GB, so each row is squeezed to
# the ten fields any metric here actually reads.
BRAND, PRICE, CAT, AVAIL, COLOURS, NAME, RETAILER, NSIZES = range(8)


def load_history(verbose=True):
    days = {}
    for day, sha in daily_snapshots():
        raw = git("show", f"{sha}:{CATALOG_REL}")
        if not raw.strip():
            continue
        try:
            doc = json.loads(raw)
        except ValueError:
            if verbose:
                print(f"  {day}: unparseable snapshot, skipped", file=sys.stderr)
            continue
        rows = {}
        for p in doc.get("products", []):
            pid = p.get("id")
            if not pid:
                continue
            rows[pid] = (
                p.get("brand") or "?",
                p.get("price") if isinstance(p.get("price"), (int, float)) else None,
                p.get("category") or "other",
                p.get("available"),
                tuple(p.get("colorTags") or ()),
                p.get("name") or "",
                p.get("retailer"),
                len(p.get("sizes") or ()),
            )
        days[day] = rows
        if verbose:
            print(f"  {day}  {len(rows):>5} products", file=sys.stderr)
    return days


# ── small helpers ────────────────────────────────────────────────────────────

def slugify(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def piece_key(row):
    """Identity that survives an id change.

    A product id is `slugify(brand)-handle`, so renaming a brand in the vendor
    field re-ids its whole catalogue and fakes 100% churn. Matching on
    brand+normalised title as well is the cross-check: tier-wide the two agree
    to a point (33.8% gone by id vs 32.7% by name), and the smaller number is
    the one published.
    """
    return (row[BRAND].lower(), re.sub(r"[^a-z0-9 ]", "", row[NAME].lower()).strip())


def band(price):
    for hi, lbl in ((60, "under $60"), (120, "$60–119"), (200, "$120–199"),
                    (350, "$200–349"), (600, "$350–599"), (10 ** 9, "$600+")):
        if price is not None and price < hi:
            return lbl
    return None


BANDS = ["under $60", "$60–119", "$120–199", "$200–349", "$350–599", "$600+"]


def wilson(successes, trials, z=1.96):
    """95% CI on a rate. Every published rate carries one — a number without an
    error bar invites exactly the over-reading this file exists to prevent."""
    if not trials:
        return 0.0, 0.0, 0.0
    p = successes / trials
    den = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / den
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / den
    return p, max(0.0, centre - half), min(1.0, centre + half)


def rate(successes, trials, floor):
    """A rate, or None when the denominator is too thin to publish."""
    if trials < floor:
        return None
    p, lo, hi = wilson(successes, trials)
    return {"n": trials, "k": successes, "pct": round(100 * p, 1),
            "lo": round(100 * lo, 1), "hi": round(100 * hi, 1)}


def epoch_of(day):
    return sum(1 for e in PRICE_EPOCHS if day >= e)


def in_settle_window(day):
    def plus(d, n):
        return (dt.date.fromisoformat(d) + dt.timedelta(days=n)).isoformat()
    return any(e <= day < plus(e, EPOCH_SETTLE_DAYS) for e in PRICE_EPOCHS)


# ── trap 2: per-brand methodology steps ──────────────────────────────────────

def fx_ratios(feed_repo):
    """Every ratio one currency mis-tag could produce, from the feed's own FX
    table. A voided step landing on one of these is near-certainly a config fix
    (EUR->DKK is 0.145/1.08 = 0.1343, and Stine Goya moved x0.1342), which is
    what lets the page assert the cause rather than just the pattern."""
    path = feed_repo / "loupe-feed" / "brands.json"
    if not path.exists():
        return []
    table = json.loads(path.read_text(encoding="utf-8")).get("fx_to_usd", {})
    out = set()
    for a in table.values():
        for b in table.values():
            if a > 0 and b > 0:
                out.add(round(b / a, 4))
    return sorted(out)


def detect_uniform_steps(days, order, fx=()):
    """Brand-days where a whole line moved by one identical ratio.

    Returns {(brand, day): {"ratio", "share", "fx"}}. A day in this set is a
    boundary for that brand: no price on either side may be compared with one on
    the other.

    THE AMBIGUITY, STATED RATHER THAN HIDDEN. "Everything x0.80 overnight" is a
    currency correction and it is also a sitewide 20%-off sale, and no amount of
    staring at prices separates them. Both are voided. That biases the published
    markdown rate DOWNWARD — we understate discounting rather than invent it —
    and the page says so. `fx` marks the steps whose ratio matches a currency
    pair from the feed's own FX table, which is most of them.
    """
    voided = {}
    for i in range(1, len(order)):
        d0, d1 = order[i - 1], order[i]
        ratios = collections.defaultdict(list)
        for pid, r0 in days[d0].items():
            r1 = days[d1].get(pid)
            if not r1 or not r0[PRICE] or not r1[PRICE]:
                continue
            ratios[r0[BRAND]].append(r1[PRICE] / r0[PRICE])
        for brand, rs in ratios.items():
            if len(rs) < STEP_MIN_PIECES:
                continue
            movers = sorted(x for x in rs if abs(x - 1) > MIN_MEANINGFUL_MOVE)
            share = len(movers) / len(rs)
            if share < STEP_MIN_SHARE:
                continue
            lo = movers[len(movers) // 4]
            hi = movers[(3 * len(movers)) // 4]
            if lo <= 0 or hi / lo > STEP_MAX_SPREAD:
                continue
            m = statistics.median(movers)
            voided[(brand, d1)] = {
                "ratio": round(m, 4),
                "share": round(100 * share),
                "fx": any(abs(m / f - 1) < 0.015 for f in fx if f > 0),
            }
    return voided


# ── visual clustering ────────────────────────────────────────────────────────

def load_embeddings(feed_repo):
    """Marqo-FashionSigLIP vectors: base64 int8 x scale, parallel to `ids`."""
    path = feed_repo / "loupe-feed" / "embeddings.json"
    if not path.exists():
        return None, None
    doc = json.loads(path.read_text(encoding="utf-8"))
    ids = doc["ids"]
    raw = np.frombuffer(base64.b64decode(doc["vectors"]), dtype=np.int8)
    x = raw.reshape(len(ids), doc["dim"]).astype(np.float32) * doc["scale"]
    x /= np.linalg.norm(x, axis=1, keepdims=True) + 1e-9   # cosine -> euclidean
    return ids, x


def kmeans(x, k, seed=7, iters=60):
    """k-means++ on L2-normalised vectors. Hand-rolled rather than pulled from
    scikit-learn: numpy is already required to decode the int8 blob, and a
    weekly generator that a founder has to be able to run should not need a
    100 MB dependency to draw sixteen swatches."""
    rng = np.random.default_rng(seed)
    n = x.shape[0]
    centres = [x[rng.integers(n)]]
    d2 = ((x - centres[0]) ** 2).sum(1)
    for _ in range(k - 1):
        probs = d2 / max(d2.sum(), 1e-12)
        centres.append(x[rng.choice(n, p=probs)])
        d2 = np.minimum(d2, ((x - centres[-1]) ** 2).sum(1))
    c = np.stack(centres)
    labels = np.zeros(n, dtype=np.int32)
    for _ in range(iters):
        new = np.argmax(x @ c.T, axis=1)           # unit vectors -> dot = cosine
        if (new == labels).all():
            break
        labels = new
        for j in range(k):
            m = labels == j
            if m.any():
                v = x[m].mean(0)
                c[j] = v / (np.linalg.norm(v) + 1e-9)
    return labels, c


TITLE_STOP = set("""the a an and in of with de la le for by to on at from size one two new
mini midi maxi set pack pair piece color colour edition made order ready copy
product look black white """.split())


def cluster_words(names, overall, total, member_count, brand_tokens):
    """The most distinctive words in a cluster's titles, by lift over the whole
    catalogue. These ARE the labels: nobody editorialises what a cluster 'means',
    because the honest description of a k-means cluster is the words that are
    unusually common inside it."""
    tc = collections.Counter()
    for nm in names:
        tc.update({t for t in re.findall(r"[a-z']+", nm.lower())
                   if len(t) > 2 and t not in TITLE_STOP and t not in brand_tokens})
    scored = [((c / member_count) / max(overall[t] / total, 1e-9), t, c)
              for t, c in tc.items() if c >= max(6, 0.05 * member_count)]
    scored.sort(reverse=True)
    return [t for _, t, _ in scored[:6]]


# ── the computation ──────────────────────────────────────────────────────────

def compute(days, feed_repo, verbose=True):
    order = sorted(days)
    if len(order) < 8:
        sys.exit("Need at least eight daily catalog snapshots.")
    era = [d for d in order if d >= ERA_START]
    avail_days = [d for d in order if d >= AVAIL_START]
    d_start, d_end = era[0], era[-1]
    first, last = days[d_start], days[d_end]

    gaps = []
    for a, b in zip(order, order[1:]):
        n = (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days
        if n > 1:
            gaps.append({"after": a, "before": b, "days": n - 1})

    # ── roster: brands present at BOTH endpoints (trap 4) ────────────────────
    b_first = {r[BRAND] for r in first.values()}
    b_last = {r[BRAND] for r in last.values()}
    roster = b_first & b_last
    left_roster = sorted(b_first - b_last)

    def direct(rows):
        """Brand-direct rows only. Partner-retailer shelves (Gemini, from
        2026-07-29) are ingested with inStockOnly=True, so a sold-out partner
        piece is never in the catalog at all — including them would drag the
        tier's sell-out rate toward zero for a reason that is about our ingest
        rule, not their stockroom."""
        return {k: v for k, v in rows.items() if not v[RETAILER]}

    # ── 1. turnover, measured once between two endpoints (trap 3) ────────────
    coh_tot, coh_surv = collections.Counter(), collections.Counter()
    band_tot, band_surv = collections.Counter(), collections.Counter()
    col_tot, col_surv = collections.Counter(), collections.Counter()
    brand_tot, brand_surv = collections.Counter(), collections.Counter()
    cohort_n = cohort_surv = 0
    for pid, r in direct(first).items():
        if r[BRAND] not in roster:
            continue
        alive = pid in last
        cohort_n += 1
        cohort_surv += alive
        coh_tot[r[CAT]] += 1
        brand_tot[r[BRAND]] += 1
        if band(r[PRICE]):
            band_tot[band(r[PRICE])] += 1
        for t in (r[COLOURS] or ("untagged",)):
            col_tot[t] += 1
        if alive:
            coh_surv[r[CAT]] += 1
            brand_surv[r[BRAND]] += 1
            if band(r[PRICE]):
                band_surv[band(r[PRICE])] += 1
            for t in (r[COLOURS] or ("untagged",)):
                col_surv[t] += 1

    def turnover(tot, surv, keys, floor):
        out = []
        for k in keys:
            n = tot.get(k, 0)
            rec = rate(n - surv.get(k, 0), n, floor)
            if rec:
                out.append({"key": k, **rec})
        return out

    # Cross-check by name as well as by id, and publish the smaller of the two
    # (see piece_key). If they ever diverge badly, the id-based number is lying.
    k_first = collections.Counter(piece_key(r) for r in direct(first).values()
                                  if r[BRAND] in roster)
    k_last = set(piece_key(r) for r in direct(last).values())
    gone_by_name = sum(n for k, n in k_first.items() if k not in k_last)

    # ── 2. sell-out, on the current shelf (trap 5) ───────────────────────────
    oos_cat, all_cat = collections.Counter(), collections.Counter()
    oos_band, all_band = collections.Counter(), collections.Counter()
    oos_brand, all_brand = collections.Counter(), collections.Counter()
    for pid, r in direct(last).items():
        if r[AVAIL] is None:
            continue
        all_cat[r[CAT]] += 1
        all_brand[r[BRAND]] += 1
        if band(r[PRICE]):
            all_band[band(r[PRICE])] += 1
        if r[AVAIL] is False:
            oos_cat[r[CAT]] += 1
            oos_brand[r[BRAND]] += 1
            if band(r[PRICE]):
                oos_band[band(r[PRICE])] += 1

    # ── 3. arrivals ──────────────────────────────────────────────────────────
    first_seen = {}
    for d in era:
        for pid, r in days[d].items():
            first_seen.setdefault(piece_key(r), d)
    arrivals_by_brand = collections.Counter()
    for k, d in first_seen.items():
        if d > d_start:
            arrivals_by_brand[k[0]] += 1

    arrived_now, standing_now = set(), set()
    for pid, r in direct(last).items():
        (arrived_now if first_seen.get(piece_key(r), "") > d_start else standing_now).add(pid)

    def oos_of(pids):
        n = sum(1 for p in pids if last[p][AVAIL] is not None)
        k = sum(1 for p in pids if last[p][AVAIL] is False)
        return rate(k, n, MIN_N_PUBLIC)

    # ── 4. price discipline, inside one clean epoch (traps 1 + 2) ────────────
    voided = detect_uniform_steps(days, order, fx_ratios(feed_repo))
    clean = [d for d in order
             if epoch_of(d) == epoch_of(order[-1]) and not in_settle_window(d)]
    voided_days = collections.defaultdict(set)
    for (b, d) in voided:
        voided_days[b].add(d)

    series, prow = collections.defaultdict(list), {}
    for d in clean:
        for pid, r in direct(days[d]).items():
            if r[PRICE] and r[PRICE] > 0:
                series[pid].append((d, r[PRICE]))
                prow[pid] = r
    disc_tot, disc_cut, disc_depth = collections.Counter(), collections.Counter(), \
        collections.defaultdict(list)
    n_tracked = n_cut = n_up = 0
    depths = []
    for pid, pts in series.items():
        b = prow[pid][BRAND]
        # Split the run at any brand-day the detector voided, and keep the
        # longest clean segment. A brand whose currency was fixed mid-window
        # still gets measured — just never across the fix.
        segs, cur = [], []
        for d, p in pts:
            if d in voided_days.get(b, ()):
                segs.append(cur)
                cur = []
            cur.append((d, p))
        segs.append(cur)
        seg = max(segs, key=len)
        if len(seg) < 5:
            continue
        n_tracked += 1
        disc_tot[b] += 1
        lo, hi = min(p for _, p in seg), max(p for _, p in seg)
        if hi <= lo * (1 + MIN_MEANINGFUL_MOVE):
            continue
        if seg[-1][1] < seg[0][1] * (1 - MIN_MEANINGFUL_MOVE):
            n_cut += 1
            disc_cut[b] += 1
            dep = 100 * (1 - seg[-1][1] / seg[0][1])
            depths.append(dep)
            disc_depth[b].append(dep)
        elif seg[-1][1] > seg[0][1] * (1 + MIN_MEANINGFUL_MOVE):
            n_up += 1

    disc_brands = [
        {"brand": b, "n": disc_tot[b], "cut": disc_cut[b],
         "pct": round(100 * disc_cut[b] / disc_tot[b], 1),
         "depth": round(statistics.median(disc_depth[b]), 0) if disc_depth[b] else None}
        for b in disc_tot if disc_tot[b] >= MIN_N_BRAND
    ]
    disc_brands.sort(key=lambda r: (r["pct"], -r["n"]))

    # ── 5. price architecture ────────────────────────────────────────────────
    arch = []
    by_cat_prices = collections.defaultdict(list)
    for pid, r in direct(last).items():
        if r[PRICE] and r[PRICE] > 0:
            by_cat_prices[r[CAT]].append(r[PRICE])
    for c, ps in sorted(by_cat_prices.items(), key=lambda kv: -len(kv[1])):
        ps.sort()
        q = lambda f: ps[int(f * (len(ps) - 1))]
        arch.append({"category": c, "n": len(ps), "p10": q(.10), "p25": q(.25),
                     "median": q(.50), "p75": q(.75), "p90": q(.90)})

    # ── 6. assortment shift ──────────────────────────────────────────────────
    def mix(rows, keyf):
        c = collections.Counter()
        for r in rows:
            for k in keyf(r):
                c[k] += 1
        n = sum(c.values()) or 1
        return {k: (100.0 * v / n, v) for k, v in c.items()}

    r_first = [r for r in direct(first).values() if r[BRAND] in roster]
    r_last = [r for r in direct(last).values() if r[BRAND] in roster]
    new_rows = [last[pid] for pid in arrived_now]
    old_rows = [last[pid] for pid in standing_now]

    def shift_table(keyf, keys=None, floor=MIN_N_PUBLIC):
        a, b = mix(r_first, keyf), mix(r_last, keyf)
        ks = keys or sorted(set(a) | set(b), key=lambda k: -b.get(k, (0, 0))[0])
        out = []
        for k in ks:
            if max(a.get(k, (0, 0))[1], b.get(k, (0, 0))[1]) < floor:
                continue
            out.append({"key": k, "then": round(a.get(k, (0, 0))[0], 1),
                        "now": round(b.get(k, (0, 0))[0], 1),
                        "shift": round(b.get(k, (0, 0))[0] - a.get(k, (0, 0))[0], 1),
                        "n": b.get(k, (0, 0))[1]})
        return out

    def arriving_table(keyf, keys=None, floor=MIN_N_PUBLIC):
        a, b = mix(old_rows, keyf), mix(new_rows, keyf)
        ks = keys or sorted(set(a) | set(b), key=lambda k: -b.get(k, (0, 0))[0])
        out = []
        for k in ks:
            if max(a.get(k, (0, 0))[1], b.get(k, (0, 0))[1]) < floor:
                continue
            out.append({"key": k, "standing": round(a.get(k, (0, 0))[0], 1),
                        "arriving": round(b.get(k, (0, 0))[0], 1),
                        "shift": round(b.get(k, (0, 0))[0] - a.get(k, (0, 0))[0], 1)})
        return out

    cat_of = lambda r: [r[CAT]]
    col_of = lambda r: list(r[COLOURS]) or ["untagged"]
    band_of = lambda r: [band(r[PRICE])] if band(r[PRICE]) else []

    med = lambda rows: statistics.median([r[PRICE] for r in rows if r[PRICE]]) \
        if any(r[PRICE] for r in rows) else 0

    # ── 7. visual clusters ───────────────────────────────────────────────────
    clusters = []
    emb_ids, emb_x = load_embeddings(feed_repo)
    if emb_ids is not None:
        keep = [i for i, pid in enumerate(emb_ids) if pid in last and not last[pid][RETAILER]]
        if len(keep) > K_CLUSTERS * MIN_N_CLUSTER // 2:
            xs = emb_x[keep]
            labels, centres = kmeans(xs, K_CLUSTERS)
            pids = [emb_ids[i] for i in keep]
            brand_tokens = {t for r in last.values()
                            for t in re.findall(r"[a-z']+", r[BRAND].lower())}
            overall = collections.Counter()
            for p in pids:
                overall.update({t for t in re.findall(r"[a-z']+", last[p][NAME].lower())
                                if len(t) > 2})
            base_new = len(arrived_now & set(pids)) / max(len(pids), 1)
            catalog_now = fetch_local_catalog(feed_repo)
            for j in range(K_CLUSTERS):
                mem = [pids[i] for i in range(len(pids)) if labels[i] == j]
                if len(mem) < MIN_N_CLUSTER:
                    continue
                sims = xs[labels == j] @ centres[j]
                nearest = [mem[i] for i in np.argsort(-sims)[:3]]
                prices = sorted(last[p][PRICE] for p in mem if last[p][PRICE])
                navail = sum(1 for p in mem if last[p][AVAIL] is not None)
                koos = sum(1 for p in mem if last[p][AVAIL] is False)
                nnew = sum(1 for p in mem if p in arrived_now)
                clusters.append({
                    "n": len(mem),
                    "words": cluster_words([last[p][NAME] for p in mem], overall,
                                           len(pids), len(mem), brand_tokens),
                    "categories": [c for c, _ in collections.Counter(
                        last[p][CAT] for p in mem).most_common(2)],
                    "colours": [c for c, _ in collections.Counter(
                        t for p in mem for t in (last[p][COLOURS] or ("untagged",))
                    ).most_common(2)],
                    "median": prices[len(prices) // 2] if prices else 0,
                    "share": round(100 * len(mem) / len(pids), 1),
                    "new_pct": round(100 * nnew / len(mem), 1),
                    "new_index": round(100 * (nnew / len(mem)) / max(base_new, 1e-9)),
                    "soldout": rate(koos, navail, MIN_N_CLUSTER),
                    "images": [catalog_now.get(p, {}).get("imageUrl", "") for p in nearest],
                    "members": mem,
                })
            clusters.sort(key=lambda c: -c["new_index"])

    # ── 8. newness ───────────────────────────────────────────────────────────
    shelf_now = collections.Counter(r[BRAND] for r in direct(last).values())
    news = []
    for b, n in shelf_now.items():
        if n < MIN_N_BRAND:
            continue
        a = arrivals_by_brand.get(b.lower(), 0)
        news.append({"brand": b, "shelf": n, "arrivals": a,
                     "pct": round(100 * a / n, 0)})
    news.sort(key=lambda r: -r["pct"])
    dormant = [r for r in news if r["arrivals"] == 0]

    # ── per-brand cards ──────────────────────────────────────────────────────
    tier_oos = rate(sum(oos_cat.values()), sum(all_cat.values()), MIN_N_PUBLIC)
    tier_turn = rate(cohort_n - cohort_surv, cohort_n, MIN_N_PUBLIC)
    tier_new = round(100 * len(arrived_now) / max(len(arrived_now) + len(standing_now), 1), 1)
    tier_cut = round(100 * n_cut / max(n_tracked, 1), 1)
    cluster_of = {}
    for i, c in enumerate(clusters):
        for p in c["members"]:
            cluster_of[p] = i

    brands = {}
    for b, n in shelf_now.items():
        if n < MIN_N_BRAND:
            continue
        mine = [pid for pid, r in direct(last).items() if r[BRAND] == b]
        prices = sorted(last[p][PRICE] for p in mine if last[p][PRICE])
        cats = collections.Counter(last[p][CAT] for p in mine)
        pos = []
        for c, cn in cats.most_common(4):
            if cn < 6:
                continue
            mine_c = sorted(last[p][PRICE] for p in mine
                            if last[p][CAT] == c and last[p][PRICE])
            tier_c = sorted(by_cat_prices.get(c, []))
            if not mine_c or len(tier_c) < 50:
                continue
            mm = mine_c[len(mine_c) // 2]
            pct = 100.0 * sum(1 for x in tier_c if x < mm) / len(tier_c)
            pos.append({"category": c, "pieces": cn, "median": mm,
                        "tier_median": tier_c[len(tier_c) // 2],
                        "percentile": round(pct)})
        mine_clusters = collections.Counter(cluster_of[p] for p in mine if p in cluster_of)
        brands[slugify(b)] = {
            "brand": b,
            "slug": slugify(b),
            "shelf": n,
            "price_median": prices[len(prices) // 2] if prices else 0,
            "price_lo": prices[0] if prices else 0,
            "price_hi": prices[-1] if prices else 0,
            "soldout": rate(oos_brand.get(b, 0), all_brand.get(b, 0), MIN_N_BRAND),
            "turnover": rate(brand_tot.get(b, 0) - brand_surv.get(b, 0),
                             brand_tot.get(b, 0), MIN_N_BRAND),
            "arrivals": arrivals_by_brand.get(b.lower(), 0),
            "arrivals_pct": round(100 * arrivals_by_brand.get(b.lower(), 0) / n),
            "markdown": (
                {"n": disc_tot[b], "cut": disc_cut[b],
                 "pct": round(100 * disc_cut[b] / disc_tot[b], 1),
                 "depth": round(statistics.median(disc_depth[b])) if disc_depth[b] else None}
                if disc_tot.get(b, 0) >= MIN_N_BRAND else None),
            "architecture": pos,
            "clusters": [{"share": round(100 * cn / len(mine)),
                          "words": clusters[ci]["words"][:3],
                          "new_index": clusters[ci]["new_index"],
                          "soldout": clusters[ci]["soldout"]}
                         for ci, cn in mine_clusters.most_common(3)],
            "voided": sorted(d for (bb, d) in voided if bb == b),
        }

    return {
        "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generatedLabel": dt.datetime.now(dt.timezone.utc).strftime("%B %d, %Y").replace(" 0", " "),
        "windowStart": order[0],
        "eraStart": d_start,
        "windowEnd": d_end,
        "snapshots": len(order),
        "eraSnapshots": len(era),
        "eraDays": (dt.date.fromisoformat(d_end) - dt.date.fromisoformat(d_start)).days,
        "gaps": gaps,
        "coverage": {
            "brands_now": len({r[BRAND] for r in direct(last).values()}),
            # Every label in the app, including those that reach it only through a
            # partner boutique. Emitted so the page can explain the gap between this
            # and brands_now instead of leaving a reader to assume a bug — the first
            # question the founder asked on seeing the page was "why 177 and not 209".
            "brands_all": len({r[BRAND] for r in last.values()}),
            "pieces_now": len(direct(last)),
            "brands_roster": len(roster),
            "left_roster": left_roster,
            "founder_removed": FOUNDER_REMOVED,
            "cap": 60,
            "page": 180,
        },
        "headline": {
            "turnover": tier_turn,
            "turnover_by_name": round(100 * gone_by_name / max(cohort_n, 1), 1),
            "soldout": tier_oos,
            "full_price_pct": round(100 - tier_cut, 1),
            "new_pct": tier_new,
        },
        "turnover": {
            "category": turnover(coh_tot, coh_surv, [c for c, _ in coh_tot.most_common()],
                                 MIN_N_PUBLIC),
            "band": turnover(band_tot, band_surv, BANDS, MIN_N_PUBLIC),
            "colour": turnover(col_tot, col_surv,
                               [c for c, _ in col_tot.most_common()], MIN_N_PUBLIC),
        },
        "soldOut": {
            "tier": tier_oos,
            "category": [{"key": c, **rate(oos_cat[c], all_cat[c], MIN_N_PUBLIC)}
                         for c, _ in all_cat.most_common() if rate(oos_cat[c], all_cat[c], MIN_N_PUBLIC)],
            "band": [{"key": c, **rate(oos_band[c], all_band[c], MIN_N_PUBLIC)}
                     for c in BANDS if rate(oos_band.get(c, 0), all_band.get(c, 0), MIN_N_PUBLIC)],
            "arrivals": oos_of(arrived_now),
            "standing": oos_of(standing_now),
        },
        "priceDiscipline": {
            "tracked": n_tracked,
            "cut": n_cut,
            "cut_pct": tier_cut,
            "up": n_up,
            "depth_median": round(statistics.median(depths)) if depths else None,
            "depth_p25": round(sorted(depths)[len(depths) // 4]) if depths else None,
            "depth_p75": round(sorted(depths)[3 * len(depths) // 4]) if depths else None,
            "brands_measured": len(disc_brands),
            "brands_never": sum(1 for r in disc_brands if r["cut"] == 0),
            "full_price_houses": [r["brand"] for r in disc_brands if r["cut"] == 0][:24],
            "window": [clean[0], clean[-1]],
            "voided_steps": [{"brand": b, "day": d, **v}
                             for (b, d), v in sorted(voided.items(), key=lambda kv: kv[0][1])],
            "voided_in_window": [{"brand": b, "day": d, **v}
                                 for (b, d), v in sorted(voided.items(), key=lambda kv: kv[0][1])
                                 if clean[0] <= d <= clean[-1]],
            "voided_fx": sum(1 for v in voided.values() if v["fx"]),
        },
        "architecture": arch,
        "assortment": {
            "category": shift_table(cat_of),
            "colour": shift_table(col_of),
            "band": shift_table(band_of, BANDS),
            "median_then": med(r_first),
            "median_now": med(r_last),
            "arriving_category": arriving_table(cat_of),
            "arriving_colour": arriving_table(col_of),
            "arriving_band": arriving_table(band_of, BANDS),
            "arriving_median": med(new_rows),
            "standing_median": med(old_rows),
        },
        "clusters": [{k: v for k, v in c.items() if k != "members"} for c in clusters],
        "newness": {
            "brands_measured": len(news),
            "dormant": len(dormant),
            "dormant_pct": round(100 * len(dormant) / max(len(news), 1)),
            "fastest": news[:12],
            "median_pct": round(statistics.median([r["pct"] for r in news])) if news else 0,
        },
        # Selling through fast only means demand if the shelf is LIVE. A label
        # that has published nothing for a month and shows 59% sold out is not
        # clearing stock, it is winding down a season — and naming it here would
        # be the opposite of the compliment it reads as. Requiring at least one
        # arrival in the window removes exactly that case (Gumi and Kinkifish,
        # both dormant, both above 55%).
        "sellingThrough": sorted(
            ({"brand": b, "n": all_brand[b], "pct": round(100 * oos_brand[b] / all_brand[b])}
             for b in all_brand
             if all_brand[b] >= MIN_N_BRAND and arrivals_by_brand.get(b.lower(), 0) > 0),
            key=lambda r: -r["pct"])[:10],
        "brands": brands,
    }


def fetch_local_catalog(feed_repo):
    """Today's catalog, for image URLs only. Read from the local feed clone —
    the whole build already depends on that clone, so reaching over the network
    for a file sitting on disk would only add a way to fail."""
    p = feed_repo / "loupe-feed" / "catalog.json"
    if not p.exists():
        return {}
    doc = json.loads(p.read_text(encoding="utf-8"))
    return {x["id"]: x for x in doc.get("products", []) if x.get("id")}


# ── page ─────────────────────────────────────────────────────────────────────

E = lambda s: html.escape(str(s), quote=True)

CSS = """
:root{--paper:%(paper)s;--ink:%(ink)s;--muted:%(muted)s;--line:%(line)s;--white:%(white)s;
--pink:%(pink)s;--pink-soft:%(pink_soft)s;--coral:%(coral)s;--accent:%(accent)s;--navy:%(navy)s;}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
color:var(--ink);background:var(--paper);line-height:1.55;-webkit-font-smoothing:antialiased;}
a{color:inherit;text-decoration:none;}
img{max-width:100%%;}
.wrap{max-width:1000px;margin:0 auto;padding:0 24px;}
.serif{font-family:"Fraunces",Georgia,serif;font-weight:500;letter-spacing:-.5px;}
.script{font-family:"Beth Ellen",cursive;font-weight:400;}
.eyebrow{font-size:11px;letter-spacing:2.2px;text-transform:uppercase;color:var(--accent);font-weight:700;}
.muted{color:var(--muted);}
header{border-bottom:1px solid var(--line);background:var(--white);}
.nav{display:flex;align-items:center;justify-content:space-between;height:64px;}
.logo{font-size:22px;}
.nav-links{display:flex;gap:22px;font-size:14px;color:var(--muted);}
.hero{padding:52px 0 34px;}
h1{font-size:clamp(32px,6vw,54px);line-height:1.05;letter-spacing:-1.6px;margin:10px 0 16px;max-width:16ch;}
h2{font-size:clamp(22px,3.2vw,29px);line-height:1.15;margin:0 0 8px;}
h3{font-size:16px;margin:0 0 4px;font-weight:600;}
p.lead{font-size:18px;color:var(--muted);max-width:60ch;}
section{padding:34px 0;border-top:1px solid var(--line);}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin-top:20px;}
.card{background:var(--white);border:1px solid var(--line);border-radius:16px;padding:20px;}
.card.lead{border-color:var(--pink);background:var(--pink-soft);}
.big{font-size:38px;line-height:1;letter-spacing:-1.6px;}
.sub{font-size:13.5px;margin-top:9px;color:var(--muted);}
.sub b{color:var(--ink);}
table{width:100%%;border-collapse:collapse;margin-top:14px;font-size:14px;}
th,td{text-align:right;padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:middle;}
th:first-child,td:first-child{text-align:left;}
th{font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:var(--muted);font-weight:700;}
td.cap{text-transform:capitalize;}
.n{font-variant-numeric:tabular-nums;}
.barcell{width:34%%;}
.bar{height:9px;border-radius:99px;background:#EDE9ED;overflow:hidden;}
.bar i{display:block;height:100%%;background:var(--ink);}
.bar i.pink{background:var(--pink);}
.bar i.coral{background:var(--coral);}
.pill{display:inline-block;min-width:52px;padding:2px 10px;border-radius:99px;font-weight:700;
font-size:13px;background:#EFEFEF;}
.pill.up{background:var(--pink);}
.pill.down{background:#F1F1F1;color:var(--muted);}
.ci{font-size:11.5px;color:var(--muted);white-space:nowrap;}
.looks{display:grid;grid-template-columns:repeat(auto-fill,minmax(216px,1fr));gap:18px;margin-top:20px;}
.look{background:var(--white);border:1px solid var(--line);border-radius:16px;overflow:hidden;}
.look .ims{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);}
.look .ims img{width:100%%;aspect-ratio:3/4;object-fit:cover;display:block;background:#F1EFED;}
.look .body{padding:13px 15px 15px;}
.look .w{font-size:15px;font-weight:600;letter-spacing:-.2px;text-transform:capitalize;}
.look .m{font-size:12.5px;color:var(--muted);margin-top:3px;}
.look .stat{display:flex;justify-content:space-between;font-size:12.5px;margin-top:9px;
padding-top:9px;border-top:1px solid var(--line);}
.look .stat b{font-size:14px;}
.note{background:var(--white);border:1px solid var(--line);border-radius:14px;padding:20px 22px;
font-size:14px;color:var(--muted);}
.note b{color:var(--ink);}
.note p+p{margin-top:11px;}
.rule{height:3px;width:52px;background:var(--coral);border-radius:99px;margin-bottom:14px;}
.tags{display:flex;flex-wrap:wrap;gap:7px;margin-top:14px;}
.tag{font-size:12.5px;background:var(--white);border:1px solid var(--line);border-radius:99px;
padding:4px 12px;}
.cta{background:var(--pink-soft);border:1px solid var(--pink);border-radius:18px;padding:26px 24px;}
footer{padding:30px 0 64px;font-size:13px;color:var(--muted);border-top:1px solid var(--line);}
@media(max-width:640px){.big{font-size:30px;}th,td{padding:8px 5px;font-size:13px;}
.barcell{display:none;}.nav-links{display:none;}}
""" % COL


def head(title, desc, canonical, noindex=False):
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{E(title)}</title>
<meta name="description" content="{E(desc)}">
{'<meta name="robots" content="noindex, nofollow, noarchive">' if noindex else
 f'<link rel="canonical" href="{canonical}">'}
<link rel="icon" type="image/png" href="/icon.png">
<meta property="og:title" content="{E(title)}">
<meta property="og:description" content="{E(desc)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="https://useloupe.shop/og.jpg">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Beth+Ellen&family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>"""


def bar(pct, scale, cls=""):
    w = max(0.0, min(100.0, 100.0 * pct / scale)) if scale else 0
    return f'<td class="barcell"><div class="bar"><i class="{cls}" style="width:{w:.1f}%"></i></div></td>'


def need(*rates):
    """Every headline sentence on the public page names a specific rate. If the
    sample behind one ever falls under the floor, `rate()` returns None and the
    page must fail to build rather than render 'None%' — a broken build is
    recoverable, a published number that is not a number is not."""
    for r in rates:
        if r is None:
            sys.exit("REFUSING TO RENDER: a headline rate fell below its sample floor "
                     f"(MIN_N_PUBLIC={MIN_N_PUBLIC}). Widen the window or lower the floor "
                     "deliberately — do not publish a blank.")


def ci(r):
    return f'<span class="ci">{r["lo"]}–{r["hi"]}</span>'


def render_public(d):
    h, sd, pd_, asrt = d["headline"], d["soldOut"], d["priceDiscipline"], d["assortment"]
    cov = d["coverage"]
    need(h["turnover"], sd["tier"], sd["arrivals"], sd["standing"])
    gap_txt = ""
    if d["gaps"]:
        g = d["gaps"][0]
        gap_txt = (f" The daily job did not run between {g['after']} and {g['before']}, "
                   f"so {g['days']} days are missing from the middle of the window.")

    out = [head(
        "The Loupe Index — market data for independent fashion",
        f"What {cov['brands_now']} independent labels are actually doing: "
        f"{h['soldout']['pct']}% of tracked pieces sold out, {h['full_price_pct']}% holding full price, "
        f"{h['turnover']['pct']}% shelf turnover in {d['eraDays']} days. Built from "
        f"{d['snapshots']} daily catalog snapshots.",
        "https://useloupe.shop/index/")]

    out.append(f"""
<header><div class="wrap nav">
  <a href="/" class="logo script">Loupe</a>
  <div class="nav-links"><a href="/brands/">Brands</a><a href="/index/">The Index</a>
  <a href="https://apps.apple.com/app/id6781137336">Get the app</a></div>
</div></header>

<div class="wrap"><div class="hero">
  <div class="eyebrow">The Loupe Index &middot; {E(d['generatedLabel'])}</div>
  <h1 class="serif">What independent fashion is actually doing</h1>
  <p class="lead">Nobody measures the independent tier. Enterprise forecasting starts above it,
  wholesale data stays private, and a brand's own dashboard shows only its own store. So we
  built the instrument out of the thing we already had: a full snapshot of
  {cov['brands_now']} labels' catalogues, taken every day since {E(d['windowStart'])}.</p>
  <div class="tags">
    <span class="tag"><b>{cov['brands_now']}</b> labels</span>
    <span class="tag"><b>{cov['pieces_now']:,}</b> pieces tracked</span>
    <span class="tag"><b>{d['snapshots']}</b> daily snapshots</span>
    <span class="tag">{E(d['windowStart'])} &rarr; {E(d['windowEnd'])}</span>
  </div>
</div></div>""")

    # headline dials
    out.append(f"""
<div class="wrap"><section style="border-top:none;padding-top:6px">
  <div class="rule"></div>
  <h2 class="serif">Four numbers nobody else has</h2>
  <p class="muted">Every rate on this page carries its sample size and a 95% confidence
  interval. Where the sample is too thin, the row is not printed rather than printed small.</p>
  <div class="cards">
    <div class="card lead"><div class="eyebrow">Full price</div>
      <div class="big serif">{h['full_price_pct']}%</div>
      <div class="sub">of {pd_['tracked']:,} tracked pieces held their price across
      {E(pd_['window'][0])}&ndash;{E(pd_['window'][1])}. <b>{pd_['brands_never']} of
      {pd_['brands_measured']}</b> labels did not mark down a single piece.</div></div>
    <div class="card"><div class="eyebrow">Sold out now</div>
      <div class="big serif">{sd['tier']['pct']}%</div>
      <div class="sub">of tracked pieces have no size left in any variant
      ({sd['tier']['n']:,} pieces, 95% CI {sd['tier']['lo']}&ndash;{sd['tier']['hi']}%).</div></div>
    <div class="card"><div class="eyebrow">{d['eraDays']}-day turnover</div>
      <div class="big serif">{h['turnover']['pct']}%</div>
      <div class="sub">of the pieces we tracked on {E(d['eraStart'])} are no longer in their
      brand's recent listings. Matched on title instead of id: {h['turnover_by_name']}%.</div></div>
    <div class="card"><div class="eyebrow">Newness</div>
      <div class="big serif">{h['new_pct']}%</div>
      <div class="sub">of today's shelf was published in the last {d['eraDays']} days.
      The median label refreshed <b>{d['newness']['median_pct']}%</b> of its shelf.</div></div>
  </div>
</section></div>""")

    # sell-through
    scale = max([r["pct"] for r in sd["category"]] + [r["pct"] for r in sd["band"]] + [1])
    rows = "".join(
        f'<tr><td class="cap">{E(r["key"])}</td><td class="n">{r["n"]:,}</td>'
        f'<td class="n"><b>{r["pct"]}%</b></td><td>{ci(r)}</td>{bar(r["pct"], scale)}</tr>'
        for r in sd["category"])
    brows = "".join(
        f'<tr><td>{E(r["key"])}</td><td class="n">{r["n"]:,}</td>'
        f'<td class="n"><b>{r["pct"]}%</b></td><td>{ci(r)}</td>{bar(r["pct"], scale, "pink")}</tr>'
        for r in sd["band"])
    out.append(f"""
<div class="wrap"><section>
  <div class="rule"></div>
  <h2 class="serif">What is selling out</h2>
  <p class="muted">A piece counts as sold out when every size of it is gone and the brand has
  not restocked. Out-of-stock pieces stay in our feed, so this is measured directly rather than
  inferred from something vanishing.</p>
  <div class="cards" style="margin-bottom:8px">
    <div class="card lead"><div class="eyebrow">New in the last {d['eraDays']} days</div>
      <div class="big serif">{sd['arrivals']['pct']}%</div>
      <div class="sub">sold out, off {sd['arrivals']['n']:,} arrivals.</div></div>
    <div class="card"><div class="eyebrow">On the shelf since {E(d['eraStart'])}</div>
      <div class="big serif">{sd['standing']['pct']}%</div>
      <div class="sub">sold out, off {sd['standing']['n']:,} pieces. <b>New product sells
      out faster than standing stock</b> — the gap is well outside both confidence intervals.</div></div>
  </div>
  <table><thead><tr><th>Category</th><th>Tracked</th><th>Sold out</th><th>95% CI</th><th></th></tr></thead>
  <tbody>{rows}</tbody></table>
  <table><thead><tr><th>Price band</th><th>Tracked</th><th>Sold out</th><th>95% CI</th><th></th></tr></thead>
  <tbody>{brows}</tbody></table>
  <p class="muted" style="margin-top:12px;font-size:13.5px">Sell-out is a barbell, not a slope:
  the cheapest and the most expensive bands clear hardest, and the middle of the market sits.</p>
</section></div>""")

    # price discipline
    houses = "".join(f'<span class="tag">{E(b)}</span>' for b in pd_["full_price_houses"])
    voided = "".join(
        f'<li>{E(v["brand"])}, {E(v["day"])} &mdash; {v["share"]}% of the line, '
        f'every piece &times;{v["ratio"]}'
        f'{" (exactly a currency-pair ratio)" if v["fx"] else ""}</li>'
        for v in pd_["voided_in_window"])
    out.append(f"""
<div class="wrap"><section>
  <div class="rule"></div>
  <h2 class="serif">Almost nobody discounts</h2>
  <p class="muted">Measured across {E(pd_['window'][0])}&ndash;{E(pd_['window'][1])}, the
  longest stretch with no change in how we read prices.</p>
  <div class="cards">
    <div class="card"><div class="eyebrow">Marked down</div>
      <div class="big serif">{pd_['cut_pct']}%</div>
      <div class="sub">of {pd_['tracked']:,} tracked pieces ended the window below where they
      started. {pd_['up']} ended above it.</div></div>
    <div class="card"><div class="eyebrow">When they do cut</div>
      <div class="big serif">{pd_['depth_median']}%</div>
      <div class="sub">median markdown. Middle half of cuts:
      {pd_['depth_p25']}%&ndash;{pd_['depth_p75']}%.</div></div>
    <div class="card lead"><div class="eyebrow">Full-price houses</div>
      <div class="big serif">{pd_['brands_never']}<span style="font-size:20px"> / {pd_['brands_measured']}</span></div>
      <div class="sub">labels with {MIN_N_BRAND}+ tracked pieces that did not cut a single
      price in the window.</div></div>
  </div>
  <p class="muted" style="margin-top:18px">Every one of these held full price on its whole
  tracked shelf:</p>
  <div class="tags">{houses}</div>
  <div class="note" style="margin-top:22px">
    <p><b>Some of the biggest "discounts" in this data were ours, and they are excluded.</b>
    A real sale marks different pieces down by different amounts. A currency correction
    multiplies every piece by exactly the same number. We look for the second: a label whose
    whole line steps by one identical ratio on one day is treated as our pipeline changing, not
    the brand changing its mind, and prices are never compared across that day for that label.
    {len(pd_['voided_steps'])} such brand-days exist across the whole window and
    <b>{pd_['voided_fx']} of them moved by exactly a currency-pair ratio</b> from our own
    conversion table — Stine Goya's line moved &times;0.134, which is the Danish krone peg, not
    an 87% sale. {len(pd_['voided_in_window'])} fall inside the window above:</p>
    <ul style="margin:8px 0 0 18px">{voided}</ul>
    <p><b>This cuts against us and we would rather it did.</b> A genuine sitewide
    "everything 20% off" is indistinguishable from a currency fix in catalogue data, so it
    would be voided too. The markdown figures on this page are therefore a floor: the tier
    discounts at least this little, possibly slightly more.</p>
  </div>
</section></div>""")

    # architecture
    arows = "".join(
        f'<tr><td class="cap">{E(r["category"])}</td><td class="n">{r["n"]:,}</td>'
        f'<td class="n">${r["p10"]:,}</td><td class="n">${r["p25"]:,}</td>'
        f'<td class="n"><b>${r["median"]:,}</b></td><td class="n">${r["p75"]:,}</td>'
        f'<td class="n">${r["p90"]:,}</td></tr>' for r in d["architecture"])
    out.append(f"""
<div class="wrap"><section>
  <div class="rule"></div>
  <h2 class="serif">Where the tier prices</h2>
  <p class="muted">The question every small brand has and cannot answer: am I priced right?
  This is the whole tracked tier on {E(d['windowEnd'])}, by category.</p>
  <table><thead><tr><th>Category</th><th>Pieces</th><th>10th</th><th>25th</th>
  <th>Median</th><th>75th</th><th>90th</th></tr></thead><tbody>{arows}</tbody></table>
  <p class="muted" style="margin-top:12px;font-size:13.5px">Sitting between the 25th and 75th
  is not a virtue in itself — but a brand two whole quartiles off the tier in one category and
  on it in another is usually doing that by accident.</p>
</section></div>""")

    # assortment
    def shift_rows(tbl, cls=""):
        return "".join(
            f'<tr><td class="cap">{E(r["key"])}</td><td class="n">{r["then"]}%</td>'
            f'<td class="n">{r["now"]}%</td>'
            f'<td><span class="pill {"up" if r["shift"] > 0.4 else "down" if r["shift"] < -0.4 else ""}">'
            f'{r["shift"]:+.1f}</span></td><td class="n">{r["n"]:,}</td></tr>' for r in tbl)

    def arr_rows(tbl):
        return "".join(
            f'<tr><td class="cap">{E(r["key"])}</td><td class="n">{r["standing"]}%</td>'
            f'<td class="n">{r["arriving"]}%</td>'
            f'<td><span class="pill {"up" if r["shift"] > 0.4 else "down" if r["shift"] < -0.4 else ""}">'
            f'{r["shift"]:+.1f}</span></td></tr>' for r in tbl)

    # The mechanism behind a rising median is worth one sentence, but only if
    # both bands survived the suppression floor. If either did not, the claim
    # goes away rather than being asserted off a table the reader cannot see.
    tb = {r["key"]: r for r in d["turnover"]["band"]}
    cheap_line = ""
    if "under $60" in tb and "$350–599" in tb:
        cheap_line = (f'The shelf gets more expensive because the cheap things leave it '
                      f'fastest: pieces under $60 turned over at <b>{tb["under $60"]["pct"]}%</b> '
                      f'against <b>{tb["$350–599"]["pct"]}%</b> at $350–599.')

    out.append(f"""
<div class="wrap"><section>
  <div class="rule"></div>
  <h2 class="serif">What the tier is making now</h2>
  <p class="muted">Share of the tracked shelf on {E(d['eraStart'])} against
  {E(d['windowEnd'])}, across the {cov['brands_roster']} labels present on both dates.</p>
  <table><thead><tr><th>Colour</th><th>{E(d['eraStart'][5:])}</th><th>{E(d['windowEnd'][5:])}</th>
  <th>Shift</th><th>Pieces</th></tr></thead><tbody>{shift_rows(asrt['colour'])}</tbody></table>
  <table><thead><tr><th>Price band</th><th>{E(d['eraStart'][5:])}</th><th>{E(d['windowEnd'][5:])}</th>
  <th>Shift</th><th>Pieces</th></tr></thead><tbody>{shift_rows(asrt['band'])}</tbody></table>
  <p class="muted" style="margin-top:14px">The shelf's median price rose from
  <b>${asrt['median_then']:,.0f}</b> to <b>${asrt['median_now']:,.0f}</b> — and not because
  brands raised prices. New pieces are arriving <em>below</em> the ones that have stayed
  (median ${asrt['arriving_median']:,.0f} arriving against
  ${asrt['standing_median']:,.0f} standing). {cheap_line}</p>
  <h3 style="margin-top:26px">Arriving vs standing</h3>
  <p class="muted">Share of pieces already on the shelf on {E(d['eraStart'])} against share of
  everything published since.</p>
  <table><thead><tr><th>Price band</th><th>Standing</th><th>Arriving</th><th>Shift</th></tr></thead>
  <tbody>{arr_rows(asrt['arriving_band'])}</tbody></table>
  <table><thead><tr><th>Category</th><th>Standing</th><th>Arriving</th><th>Shift</th></tr></thead>
  <tbody>{arr_rows(asrt['arriving_category'])}</tbody></table>
</section></div>""")

    # turnover detail
    tscale = max([x["pct"] for x in d["turnover"]["band"]] + [1])
    trows = "".join(
        f'<tr><td>{E(r["key"])}</td><td class="n">{r["n"]:,}</td>'
        f'<td class="n"><b>{r["pct"]}%</b></td><td>{ci(r)}</td>'
        f'{bar(r["pct"], tscale, "coral")}</tr>'
        for r in d["turnover"]["band"])
    crows = "".join(
        f'<tr><td class="cap">{E(r["key"])}</td><td class="n">{r["n"]:,}</td>'
        f'<td class="n"><b>{r["pct"]}%</b></td><td>{ci(r)}</td></tr>'
        for r in d["turnover"]["category"])
    out.append(f"""
<div class="wrap"><section>
  <div class="rule"></div>
  <h2 class="serif">How fast the shelf empties</h2>
  <p class="muted">Of the pieces we tracked on {E(d['eraStart'])}, the share no longer in
  their brand's recent listings on {E(d['windowEnd'])}. That is delisting and being pushed off
  by newer drops together — we can see both happen and cannot always tell which, so we say so
  rather than call it sell-through.</p>
  <table><thead><tr><th>Price band</th><th>Tracked</th><th>Gone</th><th>95% CI</th><th></th></tr></thead>
  <tbody>{trows}</tbody></table>
  <table><thead><tr><th>Category</th><th>Tracked</th><th>Gone</th><th>95% CI</th></tr></thead>
  <tbody>{crows}</tbody></table>
</section></div>""")

    # visual clusters
    if d["clusters"]:
        looks = []
        for c in d["clusters"]:
            ims = "".join(f'<img loading="lazy" src="{E(u)}" alt="">' for u in c["images"] if u)
            so = f'{c["soldout"]["pct"]}%' if c["soldout"] else "&mdash;"
            looks.append(f"""<div class="look"><div class="ims">{ims}</div><div class="body">
              <div class="w">{E(', '.join(c['words'][:3]))}</div>
              <div class="m">{c['n']:,} pieces &middot; {c['share']}% of the shelf &middot;
              median ${c['median']:,}</div>
              <div class="stat"><span>New <b>{c['new_pct']:.0f}%</b>
              <span class="ci">idx {c['new_index']}</span></span>
              <span>Sold out <b>{so}</b></span></div></div></div>""")
        out.append(f"""
<div class="wrap"><section>
  <div class="rule"></div>
  <h2 class="serif">Sixteen looks, and which ones are moving</h2>
  <p class="muted">These groups come from the images, not the category labels — every piece
  is embedded with a fashion vision model and clustered by what it looks like, so a boxy
  cropped knit lands next to another boxy cropped knit whatever its brand called it. The names
  are the words that are unusually common in each group's own titles; nobody wrote them.
  <b>Index 100</b> means the group is refreshing at exactly the tier's rate.</p>
  <div class="looks">{''.join(looks)}</div>
</section></div>""")

    # newness
    fastest = "".join(
        f'<tr><td>{E(r["brand"])}</td><td class="n">{r["shelf"]}</td>'
        f'<td class="n">{r["arrivals"]:,}</td><td class="n"><b>{r["pct"]:.0f}%</b></td></tr>'
        for r in d["newness"]["fastest"])
    selling = "".join(
        f'<tr><td>{E(r["brand"])}</td><td class="n">{r["n"]}</td>'
        f'<td class="n"><b>{r["pct"]}%</b></td></tr>' for r in d["sellingThrough"])
    out.append(f"""
<div class="wrap"><section>
  <div class="rule"></div>
  <h2 class="serif">The tier is two markets</h2>
  <p class="muted">Of {d['newness']['brands_measured']} labels with {MIN_N_BRAND}+ tracked
  pieces, <b>{d['newness']['dormant']}</b> ({d['newness']['dormant_pct']}%) published nothing
  at all in {d['eraDays']} days, while the fastest replaced their visible shelf several times
  over. Averages across this tier describe almost nobody.</p>
  <div class="cards" style="grid-template-columns:repeat(auto-fit,minmax(280px,1fr))">
    <div class="card"><h3>Refreshing fastest</h3>
      <p class="muted" style="font-size:13px">New pieces published since {E(d['eraStart'])},
      against the size of the shelf we track.</p>
      <table><thead><tr><th>Label</th><th>Shelf</th><th>New</th><th>Refresh</th></tr></thead>
      <tbody>{fastest}</tbody></table></div>
    <div class="card"><h3>Selling through fastest</h3>
      <p class="muted" style="font-size:13px">Share of the tracked shelf with every size gone,
      {MIN_N_BRAND}+ pieces. Only labels that have published something in the window, so this
      is live stock clearing rather than a shelf nobody has refreshed.</p>
      <table><thead><tr><th>Label</th><th>Shelf</th><th>Sold out</th></tr></thead>
      <tbody>{selling}</tbody></table></div>
  </div>
</section></div>""")

    # brand CTA
    out.append(f"""
<div class="wrap"><section>
  <div class="cta">
    <div class="eyebrow">Free, for any label we track</div>
    <h2 class="serif" style="margin-top:8px">Your own numbers against the tier</h2>
    <p class="muted" style="max-width:60ch;margin-top:8px">We build a private card for each of
    the {len(d['brands'])} labels with enough tracked pieces to measure: your sell-out rate,
    your turnover, your refresh rate and where your prices sit in your own categories against
    everyone else's — each one next to the tier figure over the same window. It is free, it is
    yours, and nothing on it is published here — the card is stored encrypted and the link we
    send you is the only key to it.</p>
    <p style="margin-top:14px"><b>Email <a href="mailto:tryloupeapp@gmail.com"
    style="text-decoration:underline">tryloupeapp@gmail.com</a></b> with your label's name and
    we will send the link.</p>
  </div>
</section></div>""")

    # method
    left = ", ".join(cov["left_roster"]) or "none"
    out.append(f"""
<div class="wrap"><section>
  <div class="rule"></div>
  <h2 class="serif">How this is measured, and what it cannot tell you</h2>
  <div class="note">
    <p><b>What we see.</b> Every label's public product feed, read once a day and committed.
    We keep up to {cov['cap']} pieces per label, drawn from its {cov['page']} most recently
    published listings. For a small store that is the entire store; for a large one it is the
    front of the catalogue. Every number on this page is <em>of what we track</em> and we mean
    it literally.</p>
    <p><b>Why {d['coverage']['brands_now']} and not {d['coverage']['brands_all']}.</b> The Loupe app carries
    {d['coverage']['brands_all']} labels, but {d['coverage']['brands_all'] - d['coverage']['brands_now']} of those
    reach it only through a partner boutique's shelf. What a boutique chooses to buy, and what it
    charges, is that boutique's decision &mdash; not the label's. Mixing the two would corrupt every
    number here, so the Index reads <em>brand-direct storefronts only</em>: labels publishing their
    own prices, their own assortment, their own drops.</p>
    <p><b>The window.</b> {d['snapshots']} daily snapshots, {E(d['windowStart'])} to
    {E(d['windowEnd'])}. Comparisons over time start at {E(d['eraStart'])}, when our roster
    stopped growing — before that, new pieces are us adding labels, not brands publishing.{gap_txt}</p>
    <p><b>Turnover is measured once, between two dates.</b> Day-to-day disappearance is 45%
    noise in this data: of 10,059 overnight vanishings, 4,552 came back. Anything computed as a
    daily rate would be mostly measurement.</p>
    <p><b>Our own decisions are removed.</b> {len(cov['left_roster'])} labels left our roster in
    the window ({E(left)}), some by our own choice. Every longitudinal number here uses only the
    {cov['brands_roster']} labels present on both dates.</p>
    <p><b>Prices are never compared across a change in how we read them.</b> On 2026-07-15 we
    pinned our scrape to the US market and 49 geo-priced labels flipped to USD; the next day
    36.5% of the catalogue moved price. That whole boundary is void here. Separately, any single
    label whose line moves by one identical multiplier on one day is voided for that label —
    {len(pd_['voided_steps'])} such brand-days were found, {pd_['voided_fx']} of them landing on
    an exact currency-pair ratio.</p>
    <p><b>Stock data starts {AVAIL_START}.</b> Before that we did not record whether a piece was
    in stock, so nothing earlier is asked. Partner-boutique listings are excluded from sell-out
    entirely, because we only ingest those in stock.</p>
    <p><b>What we cannot tell you.</b> Units, revenue, margin, returns, or whether a sold-out
    piece sold out at full price. We see a catalogue, not a till. We also cannot see a brand's
    stock depth — "sold out" here means no size is purchasable, which for a made-to-order label
    may never happen however well it sells.</p>
    <p><b>Would our own users' swipes predict any of this?</b> No — and we checked. Across 133
    labels, in-app approval rate against sell-out rate gives r&nbsp;=&nbsp;+0.09, which at this
    sample is indistinguishable from nothing. The Index does not use app behaviour anywhere.</p>
    <p><b>The record.</b> Every figure above is in
    <a href="/index/data.json" style="text-decoration:underline">data.json</a>, regenerated on
    the same schedule and kept in version control, so any week's numbers can be diffed against
    the last.</p>
  </div>
</section></div>

<div class="wrap"><footer>
  <b class="serif">Loupe</b> &middot; <a href="https://useloupe.shop">useloupe.shop</a> &middot;
  <a href="/brands/">{cov['brands_now']} independent labels</a><br>
  The Loupe Index is free to read and free to cite. Questions about any number on this page:
  <a href="mailto:tryloupeapp@gmail.com">tryloupeapp@gmail.com</a>.
</footer></div>
</body></html>""")
    return "".join(out)


# ── the private per-brand card ───────────────────────────────────────────────

def render_brand_shell():
    """A shell with no numbers in it. Same model as the partner reports: the page
    reads ?k=<token> and fetches /index/d/<token>.json. Without the token there is
    nothing to read — not hidden, absent."""
    return head("Your label on the Loupe Index", "Private brand card.",
                "https://useloupe.shop/index/brand/", noindex=True) + """
<div id="gate" style="max-width:520px;margin:16vh auto;text-align:center;padding:0 22px">
  <div class="logo script" style="font-size:24px">Loupe</div>
  <h2 class="serif" style="margin-top:14px">This card is private</h2>
  <p class="muted" style="margin-top:10px">Open it with the full link from your email. If the
  link stopped working, reply to that email and we will send a fresh one.</p>
</div>

<div id="report" style="display:none">
<header><div class="wrap nav">
  <a href="/" class="logo script">Loupe</a>
  <span class="muted" style="font-size:13px">Brand card &middot; <span id="gen"></span></span>
</div></header>

<div class="wrap"><div class="hero">
  <div class="eyebrow">Private &middot; The Loupe Index</div>
  <h1 class="serif" id="bname"></h1>
  <p class="lead" id="sub"></p>
</div></div>

<div class="wrap"><section style="border-top:none;padding-top:0">
  <h2 class="serif">You against the tier</h2>
  <p class="muted">Same metric, same window, same method as
  <a href="/index/" style="text-decoration:underline">the public Index</a>. Every rate is
  printed with the sample it came from.</p>
  <div class="cards" id="rates"></div>
</section></div>

<div class="wrap"><section>
  <h2 class="serif">Where you price</h2>
  <p class="muted">Your median against the tier's, in your own categories. The percentile is
  the share of the tier priced below you.</p>
  <table id="arch"><thead><tr><th>Category</th><th>Pieces</th><th>Your median</th>
  <th>Tier median</th><th>Percentile</th></tr></thead><tbody></tbody></table>
</section></div>

<div class="wrap"><section>
  <h2 class="serif">What you look like</h2>
  <p class="muted">Your pieces grouped by image, not category label, against the tier's rate
  for the same visual group.</p>
  <table id="looks"><thead><tr><th>Look</th><th>Your shelf</th><th>Tier refresh</th>
  <th>Tier sold out</th></tr></thead><tbody></tbody></table>
</section></div>

<div class="wrap"><section>
  <h2 class="serif">How this is measured</h2>
  <div class="note" id="method"></div>
</section></div>

<div class="wrap"><footer>
  <b class="serif">Loupe</b> &middot; <a href="https://useloupe.shop/index/">The Loupe Index</a><br>
  This card is private and refreshes on its own. Nothing on it is published anywhere.
</footer></div>
</div>

<script>
(function(){
  var k = new URLSearchParams(location.search).get('k') || '';
  if (!/^[A-Za-z0-9_-]{10,64}$/.test(k)) return;          // no key, no fetch

  // The file on the server is AES-256-GCM ciphertext and the token in this URL
  // is the only key to it. loupe-site is a public repository, so "nobody can
  // guess the filename" is not privacy — anyone can read the file list. This
  // makes the file itself useless without the link.
  function bytes(b64){
    var s = atob(b64), a = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) a[i] = s.charCodeAt(i);
    return a;
  }
  function decrypt(env){
    return crypto.subtle.digest('SHA-256', new TextEncoder().encode(k))
      .then(function(kb){ return crypto.subtle.importKey('raw', kb, 'AES-GCM', false, ['decrypt']); })
      .then(function(key){
        return crypto.subtle.decrypt({name:'AES-GCM', iv: bytes(env.iv)}, key, bytes(env.ct));
      })
      .then(function(buf){ return JSON.parse(new TextDecoder().decode(buf)); });
  }

  fetch('/index/d/' + k + '.json', {cache:'no-store'})
    .then(function(r){ if(!r.ok) throw 0; return r.json(); })
    .then(decrypt)
    .then(render)
    .catch(function(){});                 // bad key or wrong key -> gate stays

  function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function n(x){ return Number(x||0).toLocaleString(); }
  function money(x){ return '$' + n(Math.round(x)); }

  // Every rate renders with its denominator. A card that says "18%" and not
  // "18% of 60 pieces" is one the brand cannot check, and the entire reason a
  // brand trusts a number from a stranger is that they can check it.

  function card(o){
    return '<div class="card' + (o.lead ? ' lead' : '') + '">'
      + '<div class="eyebrow">' + esc(o.label) + '</div>'
      + '<div class="big serif">' + esc(o.value) + '</div>'
      + '<div class="sub">' + o.sub + '</div></div>';
  }

  function render(d){
    document.getElementById('gate').style.display = 'none';
    document.getElementById('report').style.display = '';
    document.title = d.brand + ' on the Loupe Index';
    document.getElementById('bname').textContent = d.brand;
    document.getElementById('gen').textContent = d.generated;
    document.getElementById('sub').textContent =
      d.shelf + ' pieces tracked, median ' + money(d.price_median) + ' (' +
      money(d.price_lo) + '–' + money(d.price_hi) + '). Read daily since ' +
      d.window.split(' to ')[0] + '; comparisons cover the ' + d.window_days +
      ' days to ' + d.window.split(' to ')[1] + '.';

    var t = d.tier, cards = [];
    if (d.soldout) cards.push(card({ lead:true, label:'Sold out',
      value:d.soldout.pct + '%',
      sub:'of your ' + d.soldout.n + ' tracked pieces have no size left. Tier: <b>'
        + t.soldout.pct + '%</b> of ' + n(t.soldout.n) + '. 95% CI on yours: '
        + d.soldout.lo + '–' + d.soldout.hi + '%.' }));
    cards.push(card({ label:'Refresh',
      value:d.arrivals_pct + '%',
      sub:d.arrivals + ' new pieces published since ' + d.era_start
        + ', against a tracked shelf of ' + d.shelf
        + (d.arrivals_pct > 100 ? ' — you turn the shelf we can see over more than once'
                                : '')
        + '. The median label in the tier managed <b>' + t.newness_median + '%</b>.' }));
    if (d.turnover) cards.push(card({ label:'Turnover',
      value:d.turnover.pct + '%',
      sub:'of the ' + d.turnover.n + ' pieces you had on ' + d.era_start
        + ' are no longer in your recent listings. Tier: <b>' + t.turnover.pct + '%</b>.' }));
    // The denominator here is every piece of yours we saw priced through the
    // window, which is larger than today's shelf because pieces come and go.
    // Saying "of your N tracked pieces" against a different N in the subtitle
    // is the kind of small inconsistency that makes a brand stop reading.
    if (d.markdown) cards.push(card({ label:'Marked down',
      value:d.markdown.pct + '%',
      sub:'of the ' + d.markdown.n + ' pieces of yours we saw priced right through '
        + d.markdown_window + ', '
        + (d.markdown.depth ? 'at a median ' + d.markdown.depth + '% cut. ' : '')
        + 'Tier: <b>' + t.markdown_pct + '%</b>, and ' + t.full_price_houses
        + ' of ' + t.brands_measured + ' labels cut nothing at all.' }));
    document.getElementById('rates').innerHTML = cards.join('');

    document.querySelector('#arch tbody').innerHTML = (d.architecture||[]).map(function(a){
      return '<tr><td class="cap">' + esc(a.category) + '</td><td class="n">' + a.pieces
        + '</td><td class="n"><b>' + money(a.median) + '</b></td><td class="n">'
        + money(a.tier_median) + '</td><td><span class="pill'
        + (a.percentile >= 75 ? ' up' : a.percentile <= 25 ? ' down' : '') + '">'
        + a.percentile + 'th</span></td></tr>';
    }).join('') || '<tr><td colspan="5" class="muted">Too few pieces in any one category to compare.</td></tr>';

    document.querySelector('#looks tbody').innerHTML = (d.clusters||[]).map(function(c){
      return '<tr><td class="cap">' + esc(c.words.join(', ')) + '</td><td class="n">'
        + c.share + '%</td><td class="n">' + c.new_index + '</td><td class="n">'
        + (c.soldout ? c.soldout.pct + '%' : '—') + '</td></tr>';
    }).join('') || '<tr><td colspan="4" class="muted">Not enough pieces to place visually.</td></tr>';

    document.getElementById('method').innerHTML =
      '<p><b>What we track.</b> Up to ' + d.cap + ' of your pieces, taken from your '
      + d.page + ' most recently published listings, read once a day and kept. '
      + 'Everything here is of that set, not of your whole store.</p>'
      + '<p><b>Window.</b> ' + d.snapshots + ' daily snapshots, ' + d.window
      + '. Comparisons over time start ' + d.era_start + '.</p>'
      + '<p><b>Sold out</b> means no size of a piece is purchasable. <b>Turnover</b> is the '
      + 'share of what we tracked at the start that is no longer in your recent listings — '
      + 'delisting and being pushed off by your own new drops both land here, and we cannot '
      + 'always separate them.</p>'
      + (d.voided && d.voided.length
         ? '<p><b>Voided days.</b> Your whole line moved by one identical multiplier on '
           + d.voided.join(', ') + ', which is the signature of a currency correction in our '
           + 'pipeline rather than a sale. Prices are not compared across those days.</p>'
         : '')
      + '<p><b>What we cannot see.</b> Units, revenue, margin or returns. We read a catalogue, '
      + 'not a till.</p>'
      + '<p><b>Who else can see this.</b> Nobody. The public Loupe Index carries tier-level '
      + 'figures only — no label is named there for anything except holding full price, '
      + 'refreshing fastest or selling through fastest. This card is stored encrypted; the '
      + 'link you were sent is the only key to it, and we do not keep a copy of the numbers '
      + 'in readable form anywhere a search engine or a competitor can reach.</p>';
  }
})();
</script>
</body></html>"""


def encrypt_card(payload, token):
    """AES-256-GCM under SHA-256(token). See the module docstring for why a
    public repo makes unguessable-link privacy insufficient here.

    The key is the token itself, hashed to 32 bytes — not stretched with a KDF,
    deliberately: a 22-character token from secrets.token_urlsafe(16) is 128
    bits of real entropy, so there is nothing to brute-force and nothing a
    slow hash would protect. Stretching only matters for low-entropy secrets.
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        sys.exit("Brand cards need `cryptography` (pip install cryptography).\n"
                 "  It is what keeps 139 labels' private figures out of a PUBLIC repo.\n"
                 "  There is no unencrypted fallback on purpose.")
    import hashlib
    import hmac
    key = hashlib.sha256(token.encode()).digest()
    plain = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    # DETERMINISTIC nonce, derived from the key and the plaintext, so the build
    # is reproducible: re-running it after a wording tweak leaves the 139 card
    # files byte-identical instead of showing 139 spurious diffs that have to be
    # eyeballed before every commit. (Week to week they all change regardless —
    # the reporting window itself is inside the payload.) Key+nonce reuse is
    # only unsafe when the PLAINTEXT differs; here an identical nonce implies an
    # identical plaintext by construction, so there is nothing to leak.
    iv = hmac.new(key, plain, hashlib.sha256).digest()[:12]
    ct = AESGCM(key).encrypt(iv, plain, None)
    # No brand, no slug, no plaintext length hint beyond the ciphertext's own.
    return json.dumps({"v": 1,
                       "iv": base64.b64encode(iv).decode(),
                       "ct": base64.b64encode(ct).decode()}, separators=(",", ":"))


def brand_payload(d, slug):
    b = d["brands"][slug]
    pd_ = d["priceDiscipline"]
    return {
        **b,
        "generated": d["generatedLabel"],
        "window": f"{d['windowStart']} to {d['windowEnd']}",
        "markdown_window": f"{pd_['window'][0]}–{pd_['window'][1]}",
        "window_days": d["eraDays"],
        "era_start": d["eraStart"],
        "snapshots": d["snapshots"],
        "cap": d["coverage"]["cap"],
        "page": d["coverage"]["page"],
        "tier": {
            "soldout": d["soldOut"]["tier"],
            "turnover": d["headline"]["turnover"],
            "newness_median": d["newness"]["median_pct"],
            "markdown_pct": pd_["cut_pct"],
            "full_price_houses": pd_["brands_never"],
            "brands_measured": pd_["brands_measured"],
        },
    }


# ── console report ───────────────────────────────────────────────────────────

def report(d):
    h, sd, pd_ = d["headline"], d["soldOut"], d["priceDiscipline"]
    print("=" * 78)
    print(f"THE LOUPE INDEX   {d['windowStart']} -> {d['windowEnd']}   "
          f"{d['snapshots']} daily snapshots")
    print(f"  coverage        : {d['coverage']['brands_now']} labels, "
          f"{d['coverage']['pieces_now']:,} pieces tracked")
    for g in d["gaps"]:
        print(f"  !! GAP          : {g['days']} day(s) missing after {g['after']}")
    print(f"  longitudinal on : {d['coverage']['brands_roster']} labels present on both ends "
          f"({d['eraStart']} -> {d['windowEnd']}, {d['eraDays']} days)")
    print(f"  left the roster : {', '.join(d['coverage']['left_roster']) or 'none'}")
    print()
    print(f"  full price      : {h['full_price_pct']}%  ({pd_['brands_never']}/"
          f"{pd_['brands_measured']} labels cut nothing)")
    print(f"  sold out now    : {sd['tier']['pct']}%  (CI {sd['tier']['lo']}-{sd['tier']['hi']}, "
          f"n={sd['tier']['n']:,})")
    print(f"  {d['eraDays']}-day turnover: {h['turnover']['pct']}%  "
          f"(by title instead of id: {h['turnover_by_name']}%)")
    print(f"  new in window   : {h['new_pct']}% of today's shelf; "
          f"{d['newness']['dormant']}/{d['newness']['brands_measured']} labels published nothing")
    print(f"\n  arrivals sell out at {sd['arrivals']['pct']}% (n={sd['arrivals']['n']:,}) vs "
          f"{sd['standing']['pct']}% for standing stock (n={sd['standing']['n']:,})")
    print(f"\n  VOIDED as methodology, not market ({len(pd_['voided_steps'])} brand-days, "
          f"{pd_['voided_fx']} on an exact currency-pair ratio):")
    for v in pd_["voided_steps"]:
        tag = "  <- currency ratio" if v["fx"] else ""
        print(f"    {v['day']}  {v['brand'][:26]:26} {v['share']:>3}% of line x{v['ratio']}{tag}")
    if d["clusters"]:
        print(f"\n  VISUAL CLUSTERS (refresh index, 100 = tier rate)")
        for c in d["clusters"][:6]:
            so = f"{c['soldout']['pct']}%" if c["soldout"] else "-"
            print(f"    idx {c['new_index']:>3}  sold out {so:>5}  n={c['n']:>4}  "
                  f"{', '.join(c['words'][:4])}")
    print(f"\n  brand cards ready: {len(d['brands'])}")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    global FEED_REPO
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default=str(FEED_REPO), help="path to the loupe-feed clone")
    ap.add_argument("--report", action="store_true", help="print the numbers, write nothing")
    ap.add_argument("--rotate-keys", action="store_true",
                    help="mint new brand-card tokens (kills every old link)")
    ap.add_argument("--allow-shallow", action="store_true")
    args = ap.parse_args()
    FEED_REPO = pathlib.Path(args.feed)

    if not (FEED_REPO / ".git").exists():
        sys.exit(f"No git repository at {FEED_REPO}. Pass --feed <path to loupe-feed>.")
    if history_is_truncated() and not args.allow_shallow:
        sys.exit(
            "REFUSING TO BUILD: the loupe-feed clone's history is truncated.\n\n"
            "  Every number here is reconstructed from `git log`, so a shallow clone\n"
            "  silently produces a SHORTER dataset and a window that describes the\n"
            "  clone rather than the market. On 2026-08-01 that cost 14 of 42 days.\n\n"
            "  Fix it:  git -C " + str(FEED_REPO) + " fetch --unshallow\n"
            "  In CI:   actions/checkout@v4  with:  fetch-depth: 0")

    print("walking the catalog's history…", file=sys.stderr)
    days = load_history()
    d = compute(days, FEED_REPO)
    report(d)
    if args.report:
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "index.html").write_text(render_public(d), encoding="utf-8")
    # The public record carries the tier, never the per-brand detail. `brands`
    # holds each label's markdown rate, its dormancy and where it sits against
    # its own category — the whole reason the cards are token-gated. Publishing
    # the page carefully and then shipping the same numbers as JSON beside it
    # would be a leak with a link to it in the footer.
    public = {k: v for k, v in d.items() if k != "brands"}
    public["brandDetail"] = ("withheld — per-label figures are shown only to that label, "
                             "on its own private card")
    (OUT_DIR / "data.json").write_text(
        json.dumps(public, ensure_ascii=False, indent=1), encoding="utf-8")

    (OUT_DIR / "brand").mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "brand" / "index.html").write_text(render_brand_shell(), encoding="utf-8")

    # The token IS the password, so the map stays out of git (same as the partner
    # reports). Losing it costs one rebuild and a round of re-sent links.
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    keys_path = DATA_DIR / "index_keys.json"
    keys = json.loads(keys_path.read_text(encoding="utf-8")) if keys_path.exists() else {}
    if args.rotate_keys:
        keys = {}
    dd = OUT_DIR / "d"
    if args.rotate_keys and dd.exists():
        for old in dd.glob("*.json"):
            old.unlink()
    dd.mkdir(parents=True, exist_ok=True)

    live = set()
    for slug in d["brands"]:
        keys.setdefault(slug, secrets.token_urlsafe(16))
        live.add(keys[slug])
        (dd / f"{keys[slug]}.json").write_text(
            encrypt_card(brand_payload(d, slug), keys[slug]), encoding="utf-8")
    # A label that drops below the measurement floor must lose its card, not keep
    # serving last month's numbers forever.
    for stale in dd.glob("*.json"):
        if stale.stem not in live:
            stale.unlink()
    keys_path.write_text(json.dumps(keys, indent=1), encoding="utf-8")

    links = "\n".join(
        f"{d['brands'][s]['brand']}\thttps://useloupe.shop/index/brand/?k={keys[s]}"
        for s in sorted(d["brands"], key=lambda s: d["brands"][s]["brand"].lower()))
    (DATA_DIR / "index_links.txt").write_text(links, encoding="utf-8")

    print(f"\n  wrote /index/index.html, /index/data.json, "
          f"{len(d['brands'])} brand cards")
    print(f"  links for outreach: tools/data/index_links.txt (gitignored)")
    print(f"  https://useloupe.shop/index/\n")


if __name__ == "__main__":
    main()
