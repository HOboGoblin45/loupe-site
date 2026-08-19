import json, os

new = json.load(open('index/data.json', encoding='utf-8'))
old = json.load(open(os.environ['TEMP'] + '/prev_index_data.json', encoding='utf-8'))


def walk(o, n, path=""):
    if isinstance(n, dict) and isinstance(o, dict):
        for k in n:
            walk(o.get(k), n[k], path + "." + k)
    elif isinstance(n, (int, float)) and isinstance(o, (int, float)):
        if o != n:
            delta = n - o
            print(f"{path:52s} {o:>10} -> {n:>10}   ({delta:+.4g})")
    elif isinstance(n, str) and isinstance(o, str) and o != n and len(n) < 60:
        print(f"{path:52s} {o!r} -> {n!r}")


for k in ['generatedAt', 'eraStart', 'windowEnd', 'eraDays']:
    print(f"{k:14s} {old.get(k)}  ->  {new.get(k)}")
print()
for sec in ['coverage', 'headline', 'soldOut', 'priceDiscipline', 'refresh']:
    if sec in new:
        print("-- " + sec)
        walk(old.get(sec, {}), new[sec], sec)
        print()
