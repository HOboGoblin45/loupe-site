#!/usr/bin/env python3
"""One positioning brief per independent label — the thing you send a founder
cold, that is true, that they can check, and that asks for nothing.

WHY THIS EXISTS

A label doing $500K–$5M has no idea whether it is priced right, because every
benchmark it can buy is built from department stores and fast fashion. Loupe
holds the only daily archive of that tier's own storefronts, so it can answer
the one question with a peer set instead of a guess: against 170-odd labels
your size, in your own categories, where do you actually sit?

That is the whole product hypothesis in one page. If a founder reads it and
does not care, the business is not there — so this file is deliberately short
of things to pad it with.

WHAT IS ON A BRIEF, AND WHY IN THAT ORDER

  1. WHERE THEY PRICE, by category, against the tier with their own pieces
     removed from the comparison. Most surprising, most theirs, and the only
     claim here nobody else can make.
  2. WHAT THE TIER DID ON MARKDOWNS. Almost every brand believes everyone
     around them is discounting. Measured, ~98% of tracked pieces held their
     price and most labels cut nothing at all. An inverted belief is worth more
     than a confirmed one, and this one is checkable against any of their
     rivals' websites in five minutes.
  3. THEIR ASSORTMENT SHAPE against the tier.
  4. THEIR PUBLISHING CADENCE, as a CEILING and never as a rate we rank.

WHAT IS DELIBERATELY NOT ON A BRIEF — this list is the point of the file

  • NO PER-PIECE RISK. A sell-out model fitted on 2026-07-16→07-23 scored AUC
    0.635 on the window it was published against and 0.519 on a fresh window it
    had never seen, with 0.92x lift in its top decile — worse than random. It
    does not replicate, so there is no "this piece is at risk" number here and
    there will not be one until there is.
  • NO ABSENCE-BASED FIGURE. Until 2026-08-06 the scrape kept a brand's 60 most
    recently published pieces, and products.json is published_at DESC, so for a
    store bigger than that the tracked shelf ROTATED. Measured: 981 of 2,041
    disappearances between 2026-07-16 and 2026-08-01 were whole-brand rotation.
    Turnover, "selling through fastest", "refreshing fastest" and every
    retired-piece count are therefore roughly half our own sampler for any
    window ending before that date. They are not on a brief in any form, and
    test_loupe_index.js fails the build if the vocabulary reappears.
  • NO PRICE BARBELL, NO DEAD BAND. The published "$200–349 is where sell-out
    goes to die" came from a prevalence on the shelf. Recomputed as a
    rotation-immune incidence it is a monotone decline, and on a second window
    it flattens. Withdrawn.
  • NO NEW-ARRIVAL COUNT AS A COUNT. build_catalog only carried addedAt forward
    from the PREVIOUS catalog, so a piece that rotated off the front and came
    back was stamped brand new: 747 of 2,735 pieces flagged new on 2026-08-01 —
    27.3% — were pieces the archive had already seen. Cadence here removes
    re-entries and is still published as an upper bound, because a piece can
    also surface for the first time simply because something newer left.
  • NO SELL-THROUGH FOR THE BRAND ITSELF. "Sold out" is one Shopify variant
    flag. It is not units, not revenue, not demand, not stock depth, and a
    per-label sell-out rate on a rotating 60-piece front is exactly the claim
    six already-sent outreach emails have to be corrected for. Tier-level
    sell-out is on the brief because it is a flag figure on a fixed cohort;
    theirs is not, because it would read as a sales number and it is not one.

EVERY FIGURE CARRIES THREE THINGS

  its sample (n), its 95% interval, and its BASIS — one of exactly three words:

    flag          the store's own `available` field, on pieces present in both
                  snapshots. Our sampler cannot fake it.
    price-series  the same piece's price read on 5+ comparable days inside one
                  clean epoch, never across one of that brand's uniform
                  methodology steps.
    descriptive   a description of the tracked set on one day. No inference, no
                  prediction, no claim about anything we did not observe.

  There is no fourth basis. `absence` figures exist in data.json and are barred
  from this page by construction and by test.

WHERE THIS WRITES

  briefs-staging/ — gitignored, and named so nobody mistakes it for a live
  route. Nothing here is published. If these ever go on the site they need the
  same AES-GCM-under-the-token treatment /index/d/ already has, because
  loupe-site is a PUBLIC repository and an unguessable filename protects
  nothing there.

USAGE
  python tools/build_brand_briefs.py                 # every eligible label
  python tools/build_brand_briefs.py --report        # numbers only, writes nothing
  python tools/build_brand_briefs.py --ref origin/main
  python tools/build_brand_briefs.py --feed D:\loupe-feed
"""

import argparse
import collections
import datetime as dt
import json
import math
import pathlib
import statistics
import sys
import unicodedata
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import build_loupe_index as bli   # noqa: E402  (path juggling has to come first)
from build_loupe_index import (   # noqa: E402
    AVAIL, BRAND, CAT, PRICE,
    E, MIN_N_BRAND, MIN_N_PUBLIC,
    direct, flip_incidence, piece_key, price_runs, run_verdict, slugify, wilson,
)

# Redirected stdout on Windows defaults to cp1252, which cannot encode DémodéMODÉ
# or SIEDRÉS. Without this the run dies two thirds of the way through with a
# UnicodeEncodeError and everything already printed looks fine.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "briefs-staging"

# A category row needs enough of a label's own pieces to have a median with an
# interval at all (6 is the smallest n for which a distribution-free 95% CI
# exists; 8 keeps the widest ones off the page) and enough tier pieces to be a
# tier rather than a handful.
MIN_CAT_PIECES = 8
MIN_TIER_CAT = MIN_N_PUBLIC

# A headline may only claim two categories are far apart if their intervals do
# not touch. Below that it says the opposite thing — that the label is priced
# consistently — which is also useful and is not an artefact of eight pieces.
HEADLINE_SPREAD_PTS = 25

BASES = ("flag", "price-series", "descriptive")


# ══════════════════════════════════════════════════════════════════════════════
# statistics the Index does not already do
# ══════════════════════════════════════════════════════════════════════════════

def file_slug(brand):
    """A filename a founder can attach to an email without wincing.

    NOT build_loupe_index.slugify, which drops any character outside [a-z0-9]
    and turns DémodéMODÉ into "d-mod-mod" and SIEDRÉS into "siedr-s". That is
    harmless there — those slugs are dictionary keys behind an opaque token —
    and it is not harmless on a file called brief-d-mod-mod.html. Decomposing
    first keeps the letters and drops only the accents. The label's real name,
    accents and all, is what appears IN the file; this only shapes the filename.
    """
    flat = "".join(c for c in unicodedata.normalize("NFKD", brand or "")
                   if not unicodedata.combining(c))
    return slugify(flat) or slugify(brand)


def median_ci(values, conf=0.95):
    """Distribution-free 95% interval for a median, from the binomial order
    statistics — no normality assumed, which matters because a small label's
    price list is lumpy and bimodal far more often than it is bell-shaped.

    Returns (lo, hi), or (None, None) when n is too small for ANY interval to
    reach the coverage (n < 6). Returning a narrower interval instead, or a
    normal-approximation one, would be inventing precision at exactly the
    sample sizes where a brand is most likely to check us.
    """
    n = len(values)
    if n < 6:
        return None, None
    v = sorted(values)
    alpha = (1 - conf) / 2
    best = 0
    cdf = 0.0
    for l in range(1, n // 2 + 1):
        cdf += math.comb(n, l - 1) / (2.0 ** n)     # P(X <= l-1), X ~ Bin(n, .5)
        if cdf <= alpha:
            best = l
        else:
            break
    if best == 0:
        return None, None
    return v[best - 1], v[n - best]


def share_below(sorted_vals, x):
    """Share of a sorted list strictly below x, as a percentage. The tier ECDF."""
    if not sorted_vals:
        return None
    lo, hi = 0, len(sorted_vals)
    while lo < hi:                                   # bisect_left, no import
        mid = (lo + hi) // 2
        if sorted_vals[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return 100.0 * lo / len(sorted_vals)


def pct_ci(k, n):
    """(pct, lo, hi) as percentages, Wilson — the same interval the Index uses."""
    p, lo, hi = wilson(k, n)
    return round(100 * p, 1), round(100 * lo, 1), round(100 * hi, 1)


# ══════════════════════════════════════════════════════════════════════════════
# the measurement
# ══════════════════════════════════════════════════════════════════════════════

def read_walk(path):
    """The live walk of the whole roster to exhaustion, if it is on disk.

    This is what turns "our set is the front of your catalogue" from a hedge
    into a measurement, so it is worth reading — but it is read, never
    hardcoded. There are two probe files from 2026-08-06 twelve minutes apart:
    the 05:11 one got HTTP 429 from 151 of 162 stores and answers with a median
    of 245 off ten shops, and the 05:50 one answers with 157 off 157. A number
    typed into a docstring from the wrong one of those is indistinguishable
    from a number typed in from the right one, which is why nothing here is
    typed in.

    Returns None unless every store counted was walked to exhaustion, because
    "we saw all of it" and "we stopped early" must never be the same figure.
    """
    p = pathlib.Path(path)
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rows = [r for r in doc.get("results", [])
            if r.get("pages", 0) > 0
            and not str(r.get("brand", "")).startswith("[retailer]")
            and isinstance(r.get("eligible"), int)]
    if len(rows) < 50 or any(r.get("truncated") for r in rows):
        return None
    el = sorted(r["eligible"] for r in rows)
    q = lambda f: el[int(f * (len(el) - 1))]
    return {"probedAt": (doc.get("probedAt") or "")[:10],
            "stores": len(rows), "eligible": sum(el),
            "median": q(.50), "p90": q(.90), "max": q(1.0), "el": el}


def measure(days, feed_repo, walk=None, verbose=True):
    """Everything every brief needs, computed once for the whole tier."""
    order = sorted(days)
    if len(order) < 8:
        sys.exit("Need at least eight daily catalog snapshots.")

    era = [d for d in order if d >= bli.ERA_START]
    if bli.crosses_sampling_epoch(era[0], era[-1]):
        # There is no honest way to average an arrival count across the day the
        # walk depth changed, and a brief's cadence line is an arrival count.
        sys.exit(
            f"REFUSING TO BUILD: this window spans {bli.SAMPLING_EPOCHS[-1]}, the day\n"
            "  the per-brand walk depth changed. Arrivals and absences mean different\n"
            "  things on either side of it. Clamp the window to one side and re-run.")
    d_start, d_end = era[0], era[-1]
    first, last = days[d_start], days[d_end]
    last_direct = direct(last)

    # ── how deep we actually sampled, read off the data rather than config ────
    # brands.json is the future: it was edited to 750 on 2026-08-06 and every
    # snapshot in this archive was taken at 60. A page that reads the config
    # tells the brand we saw twelve times more of their store than we did.
    shelf_by_day = collections.Counter()
    for d in era:
        for b, n in collections.Counter(r[BRAND] for r in direct(days[d]).values()).items():
            shelf_by_day[b] = max(shelf_by_day[b], n)
    observed_cap = max(shelf_by_day.values()) if shelf_by_day else 0
    near_cap = observed_cap - 2
    n_at_cap = sum(1 for n in shelf_by_day.values() if n >= near_cap)

    # ── first sighting across the WHOLE archive, not just the era ────────────
    # The era-only version is what makes a re-entry look like a new listing.
    first_seen_all, first_seen_era = {}, {}
    for d in order:
        for r in direct(days[d]).values():
            first_seen_all.setdefault(piece_key(r), d)
    for d in era:
        for r in direct(days[d]).values():
            first_seen_era.setdefault(piece_key(r), d)
    new_true, new_naive = collections.Counter(), collections.Counter()
    for k, d in first_seen_era.items():
        if d <= d_start:
            continue
        new_naive[k[0]] += 1
        if first_seen_all.get(k) == d:
            new_true[k[0]] += 1

    # union of every id ever seen — a lower bound on catalogue size for the
    # labels whose shelf hit the cap, where we cannot see the store's real size
    ever = collections.defaultdict(set)
    for d in era:
        for pid, r in direct(days[d]).items():
            ever[r[BRAND]].add(pid)

    # ── the tier's price distribution, by category ───────────────────────────
    cat_prices = collections.defaultdict(list)       # [(price, brand), ...]
    for r in last_direct.values():
        if r[PRICE] and r[PRICE] > 0:
            cat_prices[r[CAT]].append((r[PRICE], r[BRAND]))
    for v in cat_prices.values():
        v.sort()
    tier_cat_n = {c: len(v) for c, v in cat_prices.items()}
    tier_mix_n = collections.Counter(r[CAT] for r in last_direct.values())
    tier_total = sum(tier_mix_n.values())
    tier_prices_all = sorted(r[PRICE] for r in last_direct.values() if r[PRICE])

    # ── markdowns, from the shared runs ──────────────────────────────────────
    pr = price_runs(days, order, feed_repo)
    clean, prow = pr["clean"], pr["prow"]
    md_tot, md_cut, md_depth = collections.Counter(), collections.Counter(), \
        collections.defaultdict(list)
    tier_tracked = tier_cut = 0
    # The honesty check on the headline: are the pieces our cap DROPS marked
    # down differently from the pieces it keeps? Same voiding, same definition,
    # only the observation count differs, so the two rows are comparable.
    short_n = short_cut = 0
    for pid, seg in pr["runs"].items():
        b = prow[pid][BRAND]
        v = run_verdict(seg)
        if len(seg) >= 5:
            tier_tracked += 1
            md_tot[b] += 1
            if v == "cut":
                tier_cut += 1
                md_cut[b] += 1
                md_depth[b].append(100 * (1 - seg[-1][1] / seg[0][1]))
        elif len(seg) >= 2:
            short_n += 1
            short_cut += (v == "cut")
    md_brands = [b for b in md_tot if md_tot[b] >= MIN_N_BRAND]
    md_never = sum(1 for b in md_brands if md_cut[b] == 0)
    voided_by_brand = collections.defaultdict(list)
    for (b, d) in pr["voided"]:
        if clean[0] <= d <= clean[-1]:
            voided_by_brand[b].append(d)

    # ── tier sell-out: a prevalence AND the incidence nobody publishes ───────
    kn = [r for r in last_direct.values() if r[AVAIL] is not None]
    oos_now = sum(1 for r in kn if r[AVAIL] is False)
    if bli.AVAIL_START not in days:
        sys.exit(f"REFUSING TO BUILD: no snapshot for {bli.AVAIL_START}, the first day the "
                 "catalog carried an availability flag. Without it there is no in-stock "
                 "cohort to measure an incidence against.")
    inc_n, inc_k = flip_incidence(days, bli.AVAIL_START, d_end)

    # Days the refresh job did not run. Every comparison here is between two
    # endpoints rather than a daily rate, so a gap shortens the record without
    # biasing it — but "read every day" would still be a false sentence, and a
    # brand that checks 46 calendar days against 42 snapshots will notice.
    span = (dt.date.fromisoformat(order[-1]) - dt.date.fromisoformat(order[0])).days + 1
    have = set(order)
    gaps = [(dt.date.fromisoformat(order[0]) + dt.timedelta(i)).isoformat()
            for i in range(span)]
    gaps = [g for g in gaps if g not in have]

    tier = {
        "labels": len({r[BRAND] for r in last_direct.values()}),
        "pieces": len(last_direct),
        "snapshots": len(order),
        "span_days": span,
        "gaps": gaps,
        "window_start": order[0],
        "era_start": d_start,
        "window_end": d_end,
        "era_days": (dt.date.fromisoformat(d_end) - dt.date.fromisoformat(d_start)).days,
        "observed_cap": observed_cap,
        "at_cap": n_at_cap,
        # The share of stores that fit inside the depth we actually sampled has
        # to be computed against THAT depth, not against a 60 written down
        # somewhere, or the sentence stops being true the day the walk changes.
        "walk": (None if not walk else
                 {k: v for k, v in walk.items() if k != "el"} |
                 {"fits": round(100 * sum(1 for v in walk["el"] if v <= observed_cap)
                                / len(walk["el"]))}),
        "cat_n": tier_cat_n,
        "mix": {c: 100.0 * n / max(tier_total, 1) for c, n in tier_mix_n.items()},
        "mix_n": dict(tier_mix_n),
        "price_p10": tier_prices_all[int(.10 * (len(tier_prices_all) - 1))],
        "price_median": tier_prices_all[len(tier_prices_all) // 2],
        "price_p90": tier_prices_all[int(.90 * (len(tier_prices_all) - 1))],
        "md_window": [clean[0], clean[-1]],
        "md_tracked": tier_tracked,
        "md_cut": tier_cut,
        "md_held": pct_ci(tier_tracked - tier_cut, tier_tracked),
        "md_brands": len(md_brands),
        "md_never": md_never,
        "md_short_n": short_n,
        "md_short_cut": short_cut,
        "md_short_pct": pct_ci(short_cut, short_n) if short_n else None,
        "md_long_pct": pct_ci(tier_cut, tier_tracked),
        "oos_now": pct_ci(oos_now, len(kn)),
        "oos_n": len(kn),
        "inc": pct_ci(inc_k, inc_n),
        "inc_n": inc_n,
        "inc_days": (dt.date.fromisoformat(d_end)
                     - dt.date.fromisoformat(bli.AVAIL_START)).days,
        "inc_start": bli.AVAIL_START,
        "cadence_median": 0,      # filled once every label is measured
        "cadence_silent": 0,
        "cadence_labels": 0,
    }

    # ── per label ────────────────────────────────────────────────────────────
    by_brand = collections.defaultdict(list)
    for pid, r in last_direct.items():
        by_brand[r[BRAND]].append(r)

    briefs = []
    skipped = []
    for b, rows in sorted(by_brand.items(), key=lambda kv: kv[0].lower()):
        shelf = len(rows)
        if shelf < MIN_N_BRAND:
            skipped.append((b, shelf, "shelf under %d" % MIN_N_BRAND))
            continue

        mine_cats = collections.Counter(r[CAT] for r in rows)
        arch = []
        for c, cn in mine_cats.most_common():
            if cn < MIN_CAT_PIECES:
                continue
            mine = [r[PRICE] for r in rows if r[CAT] == c and r[PRICE]]
            # The peer set never contains the label itself. A label holding a
            # tenth of a category would otherwise be told it sits at the middle
            # of a distribution it largely IS.
            peers = [p for p, br in cat_prices.get(c, ()) if br != b]
            if len(mine) < MIN_CAT_PIECES or len(peers) < MIN_TIER_CAT:
                continue
            mine.sort()
            med = mine[len(mine) // 2]
            m_lo, m_hi = median_ci(mine)
            pct = share_below(peers, med)
            arch.append({
                "category": c,
                "pieces": len(mine),
                "median": med,
                "median_lo": m_lo,
                "median_hi": m_hi,
                "peers": len(peers),
                "peer_median": peers[len(peers) // 2],
                "peer_p25": peers[int(.25 * (len(peers) - 1))],
                "peer_p75": peers[int(.75 * (len(peers) - 1))],
                "pct": round(pct),
                "pct_lo": round(share_below(peers, m_lo)) if m_lo is not None else None,
                "pct_hi": round(share_below(peers, m_hi)) if m_hi is not None else None,
            })
        if not arch:
            skipped.append((b, shelf, "no category with %d+ pieces against a %d+ peer set"
                            % (MIN_CAT_PIECES, MIN_TIER_CAT)))
            continue

        prices = sorted(r[PRICE] for r in rows if r[PRICE])
        mix = []
        for c, cn in mine_cats.most_common():
            peers_n = tier_mix_n.get(c, 0) - cn
            peer_total = tier_total - shelf
            mix.append({
                "category": c,
                "pieces": cn,
                "share": round(100.0 * cn / shelf, 1),
                "peer_share": round(100.0 * peers_n / max(peer_total, 1), 1),
            })
        for m in mix:
            m["shift"] = round(m["share"] - m["peer_share"], 1)

        md = None
        if md_tot.get(b, 0) >= MIN_N_BRAND:
            p, lo, hi = pct_ci(md_cut[b], md_tot[b])
            md = {"n": md_tot[b], "cut": md_cut[b], "pct": p, "lo": lo, "hi": hi,
                  "depth": round(statistics.median(md_depth[b])) if md_depth[b] else None}

        at_cap = shelf_by_day.get(b, 0) >= near_cap
        all_lo, all_hi = median_ci(prices)
        briefs.append({
            "brand": b,
            "slug": file_slug(b),
            "shelf": shelf,
            "at_cap": at_cap,
            "ever": len(ever.get(b, ())),
            "price_p10": prices[int(.10 * (len(prices) - 1))] if prices else 0,
            "price_median": prices[len(prices) // 2] if prices else 0,
            "price_p90": prices[int(.90 * (len(prices) - 1))] if prices else 0,
            "median_lo": all_lo,
            "median_hi": all_hi,
            "architecture": arch,
            "mix": mix,
            "markdown": md,
            "markdown_n_seen": md_tot.get(b, 0),
            "voided": sorted(voided_by_brand.get(b, ())),
            "new_ceiling": new_true.get(b.lower(), 0),
            "new_reentries": new_naive.get(b.lower(), 0) - new_true.get(b.lower(), 0),
        })

    ceilings = [x["new_ceiling"] for x in briefs]
    tier["cadence_labels"] = len(briefs)
    tier["cadence_median"] = round(statistics.median(ceilings)) if ceilings else 0
    tier["cadence_silent"] = sum(1 for c in ceilings if c == 0)

    if verbose:
        print(f"  tier            : {tier['labels']} labels, {tier['pieces']:,} pieces, "
              f"{tier['snapshots']} snapshots {tier['window_start']} -> {tier['window_end']}",
              file=sys.stderr)
        print(f"  sampling depth  : {observed_cap} pieces/label observed, "
              f"{n_at_cap} labels reached it", file=sys.stderr)
        print(f"  briefs eligible : {len(briefs)}   skipped {len(skipped)}", file=sys.stderr)

    return tier, briefs, skipped


# ══════════════════════════════════════════════════════════════════════════════
# prose
# ══════════════════════════════════════════════════════════════════════════════

def plural_cat(c):
    """Category names read as plurals already, except one."""
    return {"outerwear": "outerwear pieces"}.get(c, c)


def headline(b):
    """The first thing on the page, and the only sentence that has to land.

    Ranked by what a founder does not already know. A label priced 40 points
    apart in two of its own categories is nearly always doing that by accident,
    and it is the single most useful thing this archive can tell anyone. When
    the intervals overlap, that claim is not available and the page says the
    other true thing instead rather than reaching for the more dramatic one.
    """
    arch = sorted(b["architecture"], key=lambda r: r["pct"])
    lo, hi = arch[0], arch[-1]
    separated = (lo is not hi
                 and lo["pct_hi"] is not None and hi["pct_lo"] is not None
                 and hi["pct"] - lo["pct"] >= HEADLINE_SPREAD_PTS
                 and hi["pct_lo"] > lo["pct_hi"])
    if separated:
        return (f"Your {plural_cat(hi['category'])} are priced above "
                f"{hi['pct']}% of the tier. Your {plural_cat(lo['category'])}, "
                f"above {lo['pct']}%.")
    big = max(b["architecture"], key=lambda r: r["pieces"])
    if len(b["architecture"]) > 1 and hi["pct"] - lo["pct"] <= 12:
        # Quoting the biggest category's number here would understate a band:
        # 20/26/26 is not "above 20%". The range is the claim.
        # A literal en dash, not &ndash;: the headline goes through html.escape()
        # on the way to the page, so an entity here ships as "&amp;ndash;".
        band = (f"{lo['pct']}%" if lo["pct"] == hi["pct"]
                else f"{lo['pct']}–{hi['pct']}%")
        return (f"Your prices sit above {band} of the tier, "
                f"and in the same place in every category we can measure.")
    return (f"Your {plural_cat(big['category'])} are priced above {big['pct']}% "
            f"of the {big['peers']:,} other {plural_cat(big['category'])} in the tier.")


def money(x):
    return "$" + format(int(round(x)), ",")


# ══════════════════════════════════════════════════════════════════════════════
# page
# ══════════════════════════════════════════════════════════════════════════════

BRIEF_CSS = """
.brief{max-width:780px;}
.headline{font-size:clamp(25px,5.4vw,40px);line-height:1.12;letter-spacing:-1.3px;
margin:12px 0 14px;max-width:20ch;}
.basis{display:inline-block;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;
font-weight:700;color:var(--muted);background:var(--white);border:1px solid var(--line);
border-radius:99px;padding:2px 9px;margin-left:8px;white-space:nowrap;vertical-align:2px;}
h2 .basis{vertical-align:5px;}
.mono{font-variant-numeric:tabular-nums;}
.figs{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:18px;}
.stamp{font-size:12px;color:var(--muted);letter-spacing:.2px;}
.said{border-left:3px solid var(--pink);padding:2px 0 2px 16px;margin:16px 0;font-size:15px;}
ul.plain{margin:8px 0 0 18px;font-size:14px;}
ul.plain li{margin-bottom:6px;}
"""


def brief_head(title, desc):
    """Same shell as every other page on the site, minus the two things a
    staged, unsent, unpublished document must not carry: a canonical URL to a
    route that does not exist, and permission to be indexed."""
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{E(title)}</title>
<meta name="description" content="{E(desc)}">
<meta name="robots" content="noindex, nofollow, noarchive">
<link rel="icon" type="image/png" href="https://useloupe.shop/icon.png">
<meta property="og:title" content="{E(title)}">
<meta property="og:description" content="{E(desc)}">
<meta property="og:type" content="article">
<meta property="og:image" content="https://useloupe.shop/og.jpg">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Beth+Ellen&family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&display=swap" rel="stylesheet">
<style>{bli.CSS}{BRIEF_CSS}</style></head><body>"""


def basis(kind):
    assert kind in BASES, kind
    return f'<span class="basis">{kind}</span>'


def render(b, tier, figs):
    """One brief. `figs` is appended to as the page is written, so the machine
    readable record and the rendered page cannot describe different numbers —
    the sidecar is built BY the renderer, not beside it."""

    def fig(fid, label, display, kind, basis_, n, ci=None, **kw):
        """Record a figure and RETURN THE MARKUP THAT RENDERS IT.

        The return value is the only way a number reaches the page, and it is
        anchored to the figure's id: <span data-f="price.tops.percentile">77%</span>.
        test_loupe_index.js then asserts that exact anchored string exists in
        that brand's file.

        An unanchored presence check is not enough, and this was measured rather
        than assumed: deleting "84%" from Paris Georgia's price table left the
        check passing, because the headline says "above 84% of the tier" and a
        bare substring search found it there. The failure that guard exists for —
        a value computed, threaded through, and rendered on zero screens with a
        green suite — is exactly the one a collision hides.

        `kind` separates a RATE (a share of a denominator — carries a 95%
        interval) from a COUNT or a RANGE (an exact property of the set we hold —
        carries its n and no interval, because inventing one would imply we had
        sampled at random from something and we did not).
        """
        assert kind in ("rate", "value", "count", "range"), kind
        assert basis_ in BASES, basis_
        if kind in ("rate", "value"):
            assert ci, fid
        assert not any(f["id"] == fid for f in figs), "duplicate figure id " + fid
        figs.append({"id": fid, "brand": b["brand"], "label": label, "kind": kind,
                     "display": display, "ci": ci, "basis": basis_, "n": n, **kw})
        return f'<span data-f="{fid}">{display}</span>'

    def cif(fid):
        """The interval belonging to a figure, anchored the same way."""
        f = next(x for x in figs if x["id"] == fid)
        return f'<span data-c="{fid}">{f["ci"]}</span>'

    date = dt.datetime.now(dt.timezone.utc).strftime("%B %d, %Y").replace(" 0", " ")
    hl = headline(b)
    peers = tier["labels"] - 1
    # For a label whose store is bigger than we sampled, every "share of your
    # shelf" figure describes the most recently published end of the catalogue.
    # Saying so once and then referring to it is better than a caveat nobody
    # reads at the bottom.
    front_note = (" Because your store is bigger than we sample, this describes your most "
                  "recently published pieces rather than your whole catalogue &mdash; the "
                  "same rule applies to every label it is compared with."
                  if b["at_cap"] else "")

    out = [brief_head(
        f"{b['brand']} against the independent tier",
        f"Where {b['brand']}'s prices sit against {peers} other independent labels, "
        f"and what the tier did on markdowns. Built from {tier['snapshots']} daily "
        f"catalogue snapshots. Nothing here is published.")]

    # ── first screen: the claim, then straight into the evidence ─────────────
    out.append(f"""
<header><div class="wrap nav">
  <a href="https://useloupe.shop" class="logo script">Loupe</a>
  <span class="muted" style="font-size:13px">Prepared for {E(b['brand'])} &middot; not published anywhere</span>
</div></header>

<div class="wrap brief"><div class="hero" style="padding:38px 0 20px">
  <div class="eyebrow">{E(b['brand'])} &middot; {E(date)}</div>
  <h1 class="serif headline">{E(hl)}</h1>
  <p class="lead">Measured against {peers} other independent labels' own storefronts on
  {E(tier['window_end'])} &mdash; {tier['pieces']:,} pieces, from {tier['snapshots']} daily
  snapshots taken since {E(tier['window_start'])}. Every label in that comparison runs its own
  store and sets its own prices: no department stores, no chains, no marketplaces. Every number
  below carries the sample it came from and says which of three things it is made of.</p>
</div></div>""")

    # ── 1. price position ────────────────────────────────────────────────────
    rows = []
    for a in b["architecture"]:
        mci = (f'{money(a["median_lo"])}&ndash;{money(a["median_hi"])}'
               if a["median_lo"] is not None else "&mdash;")
        pci = (f'{a["pct_lo"]}&ndash;{a["pct_hi"]}%'
               if a["pct_lo"] is not None else "&mdash;")
        id_pct = "price." + a["category"] + ".percentile"
        id_med = "price." + a["category"] + ".median"
        v_pct = fig(id_pct, f'{b["brand"]} {a["category"]}: percentile of tier price',
                    f'{a["pct"]}%', "rate", "descriptive", a["pieces"], ci=pci,
                    peers=a["peers"], pct=a["pct"], lo=a["pct_lo"], hi=a["pct_hi"])
        v_med = fig(id_med, f'{b["brand"]} {a["category"]}: median price',
                    money(a["median"]), "value", "descriptive", a["pieces"], ci=mci)
        rows.append(
            f'<tr><td class="cap">{E(a["category"])}</td>'
            f'<td class="n">{a["pieces"]}</td>'
            f'<td class="n"><b>{v_med}</b></td>'
            f'<td class="ci">{cif(id_med)}</td>'
            f'<td class="n">{money(a["peer_median"])}</td>'
            f'<td class="ci">{money(a["peer_p25"])}&ndash;{money(a["peer_p75"])}</td>'
            f'<td class="n"><b>{v_pct}</b></td>'
            f'<td class="ci">{cif(id_pct)}</td></tr>')
    out.append(f"""
<div class="wrap brief"><section style="border-top:none;padding-top:0">
  <div class="rule"></div>
  <h2 class="serif">Where you price{basis("descriptive")}</h2>
  <p class="muted">Your median against the tier's, category by category. <b>Above</b> is the
  share of the tier's pieces in that category priced below your median &mdash; your own pieces
  are removed from the comparison, so this is you against everyone else, not you against a
  distribution you are part of. The intervals are what the spread of your own price list does
  to its median; they are not a guess about pieces we never saw.{front_note}</p>
  <table><thead><tr><th>Category</th><th>Your pieces</th><th>Your median</th><th>95% CI</th>
  <th>Tier median</th><th>Tier 25th&ndash;75th</th><th>Above</th><th>95% CI</th></tr></thead>
  <tbody>{''.join(rows)}</tbody></table>
  <p class="muted" style="margin-top:12px;font-size:13.5px">Sitting anywhere in particular is
  not a virtue. Sitting in two different places in two of your own categories usually is not a
  decision anyone made.</p>
</section></div>""")

    # ── 2. what the tier did on price ────────────────────────────────────────
    held, hlo, hhi = tier["md_held"]
    v_held = fig("markdown.tier.held", "Tier: share of tracked pieces that held full price",
                 f"{held}%", "rate", "price-series", tier["md_tracked"],
                 ci=f"{hlo}&ndash;{hhi}%", pct=held, lo=hlo, hi=hhi)
    never_of = fig("markdown.tier.labels", "Tier: labels that cut nothing",
                   f'{tier["md_never"]} of {tier["md_brands"]}', "count",
                   "price-series", tier["md_brands"])

    if b["markdown"]:
        m = b["markdown"]
        v_md = fig("markdown.brand", f'{b["brand"]}: share of tracked pieces marked down',
                   f'{m["pct"]}%', "rate", "price-series", m["n"],
                   ci=f'{m["lo"]}&ndash;{m["hi"]}%', pct=m["pct"], lo=m["lo"], hi=m["hi"])
        depth = (f' At a median cut of {m["depth"]}%.' if m["depth"] else "")
        yours = (f"""<div class="card"><div class="eyebrow">You</div>
      <div class="big serif">{v_md}</div>
      <div class="sub">of the <b>{m["n"]}</b> pieces of yours we could follow right through
      {E(tier["md_window"][0])}&ndash;{E(tier["md_window"][1])} ended below where they
      started &mdash; {m["cut"]} of them.{E(depth)} 95% CI
      {cif("markdown.brand")}.</div></div>""")
    else:
        yours = (f"""<div class="card"><div class="eyebrow">You</div>
      <div class="big serif">&mdash;</div>
      <div class="sub">We could follow <b>{b["markdown_n_seen"]}</b> of your pieces right
      through the window, under the {MIN_N_BRAND} we require before putting a rate on anyone.
      So there is no figure for you here rather than a shaky one.</div></div>""")

    short = ""
    if tier["md_short_pct"] and tier["md_short_n"] >= MIN_N_PUBLIC:
        sp, slo, shi = tier["md_short_pct"]
        lp, llo, lhi = tier["md_long_pct"]
        v_short = fig("markdown.tier.short", "Tier: markdown rate among briefly-seen pieces",
                      f"{sp}%", "rate", "price-series", tier["md_short_n"],
                      ci=f"{slo}&ndash;{shi}", pct=sp, lo=slo, hi=shi)
        v_long = fig("markdown.tier.cut", "Tier: share of tracked pieces marked down",
                     f"{lp}%", "rate", "price-series", tier["md_tracked"],
                     ci=f"{llo}&ndash;{lhi}", pct=lp, lo=llo, hi=lhi)
        short = (f"""<p><b>The obvious objection, measured.</b> If the pieces our sampling
    drops were the discounted ones, the figure above would be flattering rather than true. So:
    pieces we could only follow for 2&ndash;4 days were cut at <b>{v_short}</b>
    (95% CI {cif("markdown.tier.short")}, n={tier['md_short_n']:,}), against <b>{v_long}</b>
    (95% CI {cif("markdown.tier.cut")}, n={tier['md_tracked']:,}) for the pieces the headline
    is built on. The set we can see is not the loyal end of the tier.</p>""")

    voided = ""
    if b["voided"]:
        voided = (f"""<p><b>Two days of your prices are not compared.</b> Your whole line moved
    by one identical multiplier on {E(', '.join(b['voided']))}, which is the signature of a
    currency correction inside our pipeline rather than a decision of yours. We do not compare
    prices across those days. If you did in fact run a sitewide sale then, tell us &mdash; the
    two look the same in catalogue data and we void both rather than guess.</p>"""
                  if len(b["voided"]) > 1 else
                  f"""<p><b>One day of your prices is not compared.</b> Your whole line moved by
    one identical multiplier on {E(b['voided'][0])}, which is the signature of a currency
    correction inside our pipeline rather than a decision of yours. We do not compare prices
    across that day. If you did in fact run a sitewide sale then, tell us &mdash; the two look
    the same in catalogue data and we void both rather than guess.</p>""")

    out.append(f"""
<div class="wrap brief"><section>
  <div class="rule"></div>
  <h2 class="serif">Almost nobody around you discounted{basis("price-series")}</h2>
  <p class="muted">Every tracked piece's own price, read on five or more comparable days
  between {E(tier['md_window'][0])} and {E(tier['md_window'][1])}.</p>
  <div class="figs">
    <div class="card lead"><div class="eyebrow">The tier</div>
      <div class="big serif">{v_held}</div>
      <div class="sub">of {tier['md_tracked']:,} tracked pieces ended the window at or above
      the price they started it at. 95% CI {cif("markdown.tier.held")}.</div></div>
    <div class="card"><div class="eyebrow">Labels that cut nothing</div>
      <div class="big serif" style="font-size:29px">{never_of}</div>
      <div class="sub">labels with {MIN_N_BRAND}+ pieces we could follow did not mark down a
      single one, all window.</div></div>
    {yours}
  </div>
  <div class="note" style="margin-top:20px">
    <p><b>This is the number most people get wrong about their own market.</b> It is also the
    easiest one on this page to check: open four labels you consider your peers, look at what
    is on sale, and come back.</p>
    {short}{voided}
    <p><b>It is a floor, not a ceiling.</b> A genuine sitewide "everything 20% off" is
    indistinguishable from a currency correction in catalogue data, so we void both. That can
    only push the measured markdown rate down. The tier discounts at least this little,
    possibly slightly more.</p>
  </div>
</section></div>""")

    # ── 3. assortment shape ──────────────────────────────────────────────────
    mrows = []
    for m in b["mix"]:
        v_mix = fig("mix." + m["category"],
                    f'{b["brand"]}: share of shelf in {m["category"]}',
                    f'{m["share"]}%', "count", "descriptive", m["pieces"])
        pill = ("up" if m["shift"] > 2 else "down" if m["shift"] < -2 else "flat")
        mrows.append(
            f'<tr><td class="cap">{E(m["category"])}</td><td class="n">{m["pieces"]}</td>'
            f'<td class="n"><b>{v_mix}</b></td><td class="n">{m["peer_share"]}%</td>'
            f'<td><span class="pill {pill}">{m["shift"]:+.1f}</span></td></tr>')

    if b["at_cap"]:
        size_line = (
            f"<b>Your store is bigger than we sampled.</b> We read up to "
            f"{tier['observed_cap']} of your pieces a day &mdash; the most recently published "
            f"ones &mdash; and saw {b['ever']} distinct pieces of yours over "
            f"{tier['era_days']} days. Treat that as a floor on your catalogue, not a count "
            f"of it, and read every share above as a share of that front.")
    else:
        size_line = (
            f"<b>Your whole store fits inside what we sample.</b> We read up to "
            f"{tier['observed_cap']} pieces a day per label and you have {b['shelf']}, so the "
            f"shares above are your catalogue rather than a slice of it.")

    spread_disp = f'{money(b["price_p10"])}&ndash;{money(b["price_p90"])}'
    med_ci = (f'{money(b["median_lo"])}&ndash;{money(b["median_hi"])}'
              if b["median_lo"] is not None else "&mdash;")
    v_spread = fig("spread.brand", f'{b["brand"]}: 10th-to-90th price range',
                   spread_disp, "range", "descriptive", b["shelf"])
    v_med_all = fig("median.brand", f'{b["brand"]}: median price across the tracked shelf',
                    money(b["price_median"]), "value", "descriptive", b["shelf"], ci=med_ci)
    out.append(f"""
<div class="wrap brief"><section>
  <div class="rule"></div>
  <h2 class="serif">What you carry{basis("descriptive")}</h2>
  <p class="muted">Your shelf on {E(tier['window_end'])} against everyone else's on the same
  day. <b>Tier</b> again excludes your own pieces. These are counts of what we hold, not
  estimates, so they carry their sample and no interval.{front_note}</p>
  <table><thead><tr><th>Category</th><th>Your pieces</th><th>Your share</th>
  <th>Tier share</th><th>Difference</th></tr></thead><tbody>{''.join(mrows)}</tbody></table>
  <p class="muted" style="margin-top:14px">Your prices run <b>{v_spread}</b> from the 10th
  to the 90th percentile across {b['shelf']} pieces, median <b>{v_med_all}</b>
  (95% CI {cif("median.brand")}). The tier runs
  {money(tier['price_p10'])}&ndash;{money(tier['price_p90'])}, median
  {money(tier['price_median'])}.</p>
  <p class="muted">{size_line}</p>
</section></div>""")

    # ── 4. cadence, as a ceiling ─────────────────────────────────────────────
    v_cad = fig("cadence.brand", f'{b["brand"]}: ceiling on new listings in the window',
                str(b["new_ceiling"]), "count", "descriptive", b["shelf"])
    v_cad_tier = fig("cadence.tier", "Tier: median ceiling on new listings",
                     str(tier["cadence_median"]), "count", "descriptive",
                     tier["cadence_labels"])
    reentry = ""
    if b["new_reentries"]:
        reentry = (f" A further {b['new_reentries']} looked new to us and were not "
                   f"&mdash; pieces we had seen before, lost, and met again.")
    cadence = (f"In the {tier['era_days']} days to {E(tier['window_end'])} we saw "
               f"<b>{v_cad}</b> pieces from you that we had not already "
               f"seen.{reentry}")
    if not b["new_ceiling"]:
        cadence += (" That direction is the reliable one: our sampling can invent an arrival "
                    "but it cannot hide a real listing, because a new piece goes to the front "
                    "of the feed we read.")
    out.append(f"""
<div class="wrap brief"><section>
  <div class="rule"></div>
  <h2 class="serif">How often you published{basis("descriptive")}</h2>
  <p class="muted">{cadence} The median label we measure showed us
  <b>{v_cad_tier}</b> over the same window, and {tier['cadence_silent']} of
  {tier['cadence_labels']} showed us none.</p>
  <div class="said">Read that as a ceiling, not a count. A piece can appear to us for the first
  time because you published it &mdash; or because something newer left and it moved into the
  part of your feed we read. We can tell those apart only for the pieces we had already seen,
  and those are removed above. We do not rank labels on this number and you should not either.</div>
</section></div>""")

    # ── 5. the tier, for context ─────────────────────────────────────────────
    op, olo, ohi = tier["oos_now"]
    ip, ilo, ihi = tier["inc"]
    v_oos = fig("soldout.tier", "Tier: share of tracked pieces currently sold out", f"{op}%",
                "rate", "flag", tier["oos_n"], ci=f"{olo}&ndash;{ohi}%",
                pct=op, lo=olo, hi=ohi)
    v_inc = fig("incidence.tier", "Tier: share of in-stock pieces that went out of stock",
                f"{ip}%", "rate", "flag", tier["inc_n"], ci=f"{ilo}&ndash;{ihi}%",
                pct=ip, lo=ilo, hi=ihi)
    out.append(f"""
<div class="wrap brief"><section>
  <div class="rule"></div>
  <h2 class="serif">Two more things about the tier{basis("flag")}</h2>
  <p class="muted">Both read straight off each store's own availability field, on pieces we
  hold in both snapshots &mdash; the one kind of movement our sampling cannot manufacture.</p>
  <div class="figs">
    <div class="card"><div class="eyebrow">Sold out right now</div>
      <div class="big serif">{v_oos}</div>
      <div class="sub">of {tier['oos_n']:,} tracked pieces have no size purchasable.
      95% CI {cif("soldout.tier")}.</div></div>
    <div class="card"><div class="eyebrow">Went out of stock in {tier['inc_days']} days</div>
      <div class="big serif">{v_inc}</div>
      <div class="sub">of the {tier['inc_n']:,} pieces that were in stock on
      {E(tier['inc_start'])}. 95% CI {cif("incidence.tier")}. A flow, not a snapshot &mdash;
      and we know of nowhere else it is published for labels this size.</div></div>
  </div>
</section></div>""")

    # ── 6. limits + method + the route to telling us we are wrong ───────────
    walk_txt = ""
    if tier["walk"]:
        w = tier["walk"]
        walk_txt = (f" On {E(w['probedAt'])} we walked all {w['stores']} storefronts that "
                    f"answered us right to the end of their catalogues: {w['eligible']:,} "
                    f"pieces, a median store of {w['median']} and a largest of "
                    f"{w['max']:,}. Only {w['fits']}% of stores fit inside "
                    f"{tier['observed_cap']}.")
    gap_txt = ""
    if tier["gaps"]:
        gap_txt = (f"; the job did not run on {len(tier['gaps'])} of them "
                   f"({E(tier['gaps'][0])}"
                   + (f" to {E(tier['gaps'][-1])}" if len(tier["gaps"]) > 1 else "")
                   + "), which shortens the record rather than tilting it, because every "
                     "comparison here is between two dates and not a daily rate")
    out.append(f"""
<div class="wrap brief"><section id="limits">
  <div class="rule"></div>
  <h2 class="serif">What this is, and four things it is not</h2>
  <div class="note">
    <p><b>What it is.</b> Your public product feed and {peers} others', read once a day and
    kept, {E(tier['window_start'])} to {E(tier['window_end'])}. That is {tier['snapshots']}
    snapshots across {tier['span_days']} days{gap_txt}. Nothing here comes from tracking
    anyone, from our app's users, or from anything that is not already on your website.</p>
    <p><b>It is not sales.</b> "Sold out" above is one flag on a Shopify variant. It is not
    units, not revenue, not margin, not demand, not traffic, not conversion, and not stock
    depth &mdash; a made-to-order piece may never show it however well it sells. We read a
    catalogue, not a till, and no amount of reading a catalogue turns into a till.</p>
    <p><b>It is not a forecast.</b> We built a model to score individual pieces by how likely
    they were to sell out. It looked good on the window it was fitted near and scored 0.519 on
    a later window it had never seen &mdash; a coin flip, with its top-scoring tenth doing
    slightly worse than average. So there is no per-piece number anywhere on this page, and
    there will not be one until one survives that test.</p>
    <p><b>It is not everything you sell.</b> Through this whole window we read each label's
    {tier['observed_cap']} most recently published pieces, and {tier['at_cap']} of the
    {tier['labels']} filled that &mdash; their stores are bigger than it, so for them our set
    is the front of the catalogue and it turns over as they publish.{walk_txt} Which means
    anything built on a piece <em>leaving</em> our set &mdash; how much of a shelf turned over,
    who is clearing fastest, who refreshed most &mdash; would be measuring our sampler roughly
    half the time. We measured that rather than guessed at it, and it is why none of those
    figures appear here in any form.</p>
    <p><b>It is not the last word on your prices.</b> Currency: we convert to USD from a fixed
    table, so a store priced in DKK or AUD can be a few percent off. Categories are ours, not
    yours &mdash; if we have filed something as a top that you sell as a dress, the row moves.
    Both are worth telling us about.</p>
    <p><b>If a number here looks wrong to you, it may well be, and I would rather hear it than
    not.</b> Reply and say which one. I will send the rows underneath it &mdash; the dates, the
    prices, the pieces &mdash; and if it is wrong I will say so and fix it. Same address if you
    would rather just have the method:
    <a href="mailto:tryloupeapp@gmail.com?subject={E(urllib.parse.quote('This number looks wrong to me: ' + b['brand']))}"
    style="text-decoration:underline">tryloupeapp@gmail.com</a>.</p>
    <p><b>Where the numbers come from, in three words.</b>
    <span class="basis">flag</span> is the store's own availability field on a piece we hold in
    both snapshots. <span class="basis">price-series</span> is the same piece's price on five or
    more comparable days. <span class="basis">descriptive</span> is a description of what we
    held on one day &mdash; no inference. Nothing on this page is any other kind of number.</p>
    <p><b>And what the intervals mean.</b> A 95% interval appears on every rate and every
    median: it is how much of that figure could be arithmetic on a small count rather than a
    real difference. Counts &mdash; how many pieces, how many first sightings, how many labels
    &mdash; are exact and carry no interval, because we are counting what we hold rather than
    estimating what we do not.</p>
  </div>
</section></div>

<div class="wrap brief"><footer>
  <b class="serif">Loupe</b> &middot; <a href="https://useloupe.shop">useloupe.shop</a><br>
  Prepared for {E(b['brand'])} on {E(date)}. It is not published, not indexed, and not shared
  with anyone else. The tier figures come from
  <a href="https://useloupe.shop/index/">the Loupe Index</a>, which is free to read and free to
  cite. Yours do not appear there.
</footer></div>
</body></html>""")
    return "".join(out)


def render_contact_sheet(tier, briefs, figs_by_brand, skipped):
    """A staging-only index, for choosing which twenty go out. This one DOES
    name every label, which is exactly why it lives beside the briefs rather
    than inside one and is never sent to anybody."""
    rows = []
    for b in sorted(briefs, key=lambda x: -x["_interest"]):
        arch = sorted(b["architecture"], key=lambda r: r["pct"])
        spread = arch[-1]["pct"] - arch[0]["pct"] if len(arch) > 1 else 0
        rows.append(
            f'<tr><td><a href="brief-{E(b["slug"])}.html">{E(b["brand"])}</a></td>'
            f'<td class="n">{b["shelf"]}</td>'
            f'<td class="n">{len(b["architecture"])}</td>'
            f'<td class="n">{spread}</td>'
            f'<td class="n">{b["markdown"]["pct"] if b["markdown"] else "&mdash;"}</td>'
            f'<td class="n">{b["new_ceiling"]}</td>'
            f'<td class="n">{len(figs_by_brand.get(b["brand"], ()))}</td>'
            f'<td class="muted" style="font-size:12.5px">{E(headline(b))}</td></tr>')
    skip = "".join(f'<tr><td>{E(s[0])}</td><td class="n">{s[1]}</td>'
                   f'<td class="muted">{E(s[2])}</td></tr>' for s in skipped)
    return brief_head("Brand briefs — staging",
                      "Staging contact sheet. Not published.") + f"""
<div class="wrap"><div class="hero">
  <div class="eyebrow">Staging &middot; not published</div>
  <h1 class="serif" style="font-size:34px">{len(briefs)} briefs</h1>
  <p class="lead">Sorted by how much a brief has to tell that label. Spread is the gap in
  percentile between its dearest and cheapest category &mdash; the wider it is, the more the
  first line of the brief says something the founder does not know. Nothing in this directory
  is live; the pages are gitignored and carry noindex.</p>
</div>
<table><thead><tr><th>Label</th><th>Shelf</th><th>Cats</th><th>Spread</th><th>Markdown %</th>
<th>New (ceiling)</th><th>Figures</th><th>Opening line</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<h2 class="serif" style="margin-top:34px">No brief ({len(skipped)})</h2>
<table><thead><tr><th>Label</th><th>Shelf</th><th>Why not</th></tr></thead>
<tbody>{skip}</tbody></table>
</div></body></html>"""


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default=str(bli.FEED_REPO))
    ap.add_argument("--ref", default=None,
                    help="git ref to read the archive from (default: the checked-out HEAD, "
                         "which is what produced the published Index)")
    ap.add_argument("--report", action="store_true", help="numbers only, writes nothing")
    ap.add_argument("--probe", default=None,
                    help="probe_results.json from the live walk of the whole roster "
                         "(default: <feed>/loupe-feed/probe_results.json). Without it the "
                         "briefs still build; they just say less about how much of a store "
                         "we can see.")
    ap.add_argument("--allow-shallow", action="store_true")
    args = ap.parse_args()

    bli.FEED_REPO = pathlib.Path(args.feed)
    if not (bli.FEED_REPO / ".git").exists():
        sys.exit(f"No git repository at {bli.FEED_REPO}. Pass --feed <path to loupe-feed>.")
    if bli.history_is_truncated() and not args.allow_shallow:
        sys.exit("REFUSING TO BUILD: the loupe-feed clone's history is truncated. Every\n"
                 "  number here is reconstructed from `git log`, so a shallow clone silently\n"
                 "  produces a shorter archive and a window that describes the clone.\n"
                 "  Fix it:  git -C " + str(bli.FEED_REPO) + " fetch --unshallow")

    # The shallow guard does not catch a checked-out branch that is simply older
    # than the remote, and that failure also produces a well-formed, shorter,
    # wrong answer. Say it out loud rather than let it pass.
    mine = [d for d, _ in bli.daily_snapshots(args.ref)]
    for other_ref in ("origin/main", "main"):
        theirs = [d for d, _ in bli.daily_snapshots(other_ref)]
        if len(theirs) > len(mine):
            print(f"  NOTE: {other_ref} carries {len(theirs)} snapshot days (to {theirs[-1]}) "
                  f"and this build is reading {len(mine)} (to {mine[-1]}). Reading "
                  f"{args.ref or 'the checked-out branch'}, which is what the published Index "
                  f"used. Pass --ref {other_ref} for the longer archive.", file=sys.stderr)
            break

    probe = args.probe or str(bli.FEED_REPO / "loupe-feed" / "probe_results.json")
    walk = read_walk(probe)
    if walk:
        print(f"  live walk {walk['probedAt']}: {walk['stores']} stores to exhaustion, "
              f"{walk['eligible']:,} eligible pieces", file=sys.stderr)
    else:
        print(f"  NOTE: no usable roster walk at {probe}. The briefs will describe the "
              f"sampling depth without saying how big the stores behind it are. "
              f"Pass --probe <probe_results.json>.", file=sys.stderr)

    print("walking the catalog's history…", file=sys.stderr)
    days = bli.load_history(verbose=False, ref=args.ref)
    tier, briefs, skipped = measure(days, bli.FEED_REPO, walk=walk)

    # Render first, into memory, so `figs` exists before anything is written and
    # a page that fails to render cannot leave half a directory behind.
    pages, figs_by_brand, all_figs = {}, {}, []
    for b in briefs:
        figs = []
        pages[b["slug"]] = render(b, tier, figs)
        figs_by_brand[b["brand"]] = figs
        all_figs += figs
        arch = sorted(b["architecture"], key=lambda r: r["pct"])
        b["_interest"] = ((arch[-1]["pct"] - arch[0]["pct"]) if len(arch) > 1 else 0) \
            + 6 * len(b["architecture"]) + (10 if b["markdown"] else 0)

    bad = [f for f in all_figs if f["basis"] not in BASES]
    if bad:
        sys.exit(f"REFUSING TO WRITE: {len(bad)} figures carry a basis outside {BASES}: "
                 + ", ".join(sorted({f['basis'] for f in bad})))

    print("=" * 78)
    print(f"BRAND BRIEFS   {tier['window_start']} -> {tier['window_end']}   "
          f"{tier['snapshots']} daily snapshots")
    print(f"  tier                : {tier['labels']} labels, {tier['pieces']:,} pieces")
    print(f"  sampling depth seen : {tier['observed_cap']}/label/day, "
          f"{tier['at_cap']} labels reached it")
    print(f"  held full price     : {tier['md_held'][0]}%  "
          f"CI {tier['md_held'][1]}-{tier['md_held'][2]}  n={tier['md_tracked']:,}   "
          f"({tier['md_never']}/{tier['md_brands']} labels cut nothing)")
    if tier["md_short_pct"]:
        print(f"    briefly-seen pieces cut at {tier['md_short_pct'][0]}% "
              f"(n={tier['md_short_n']:,}) vs {tier['md_long_pct'][0]}% for the tracked set")
    print(f"  sold out now        : {tier['oos_now'][0]}%  "
          f"CI {tier['oos_now'][1]}-{tier['oos_now'][2]}  n={tier['oos_n']:,}")
    print(f"  went out of stock   : {tier['inc'][0]}%  CI {tier['inc'][1]}-{tier['inc'][2]}  "
          f"n={tier['inc_n']:,}  over {tier['inc_days']}d from {tier['inc_start']}")
    print(f"  cadence ceiling     : median {tier['cadence_median']} new pieces, "
          f"{tier['cadence_silent']}/{tier['cadence_labels']} showed none")
    print(f"\n  briefs              : {len(briefs)}   "
          f"figures {len(all_figs)}   skipped {len(skipped)}")
    for b in sorted(briefs, key=lambda x: -x["_interest"])[:8]:
        print(f"    {b['brand'][:26]:26} {headline(b)[:96]}")
    if args.report:
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*.html"):
        old.unlink()
    for slug, page in pages.items():
        (OUT_DIR / f"brief-{slug}.html").write_text(page, encoding="utf-8")
    for b in briefs:
        b["headline"] = headline(b)
    (OUT_DIR / "_contact-sheet.html").write_text(
        render_contact_sheet(tier, briefs, figs_by_brand, skipped), encoding="utf-8")
    (OUT_DIR / "briefs.json").write_text(json.dumps({
        "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "staging": True,
        "published": False,
        "bases": list(BASES),
        "tier": tier,
        "skipped": [{"brand": s[0], "shelf": s[1], "why": s[2]} for s in skipped],
        "briefs": [{"brand": b["brand"], "slug": b["slug"],
                    "file": f"brief-{b['slug']}.html",
                    "headline": b["headline"],
                    "figures": figs_by_brand[b["brand"]]} for b in briefs],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n  wrote {len(pages)} briefs + _contact-sheet.html + briefs.json to "
          f"{OUT_DIR.relative_to(ROOT)}/")
    print("  STAGING ONLY — gitignored, noindex, not linked from anywhere.\n")


if __name__ == "__main__":
    main()
