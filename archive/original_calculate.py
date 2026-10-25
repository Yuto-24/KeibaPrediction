"""2026 Kikka Sho pre-race subjective scenario model.

No market odds are inputs. No fitting or backtest is claimed.
PL first-three probabilities are enumerated exactly, not Monte Carlo.
The five-place mode is enumerated from the same six-scenario mixture.
"""
import itertools
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
D = json.loads((ROOT / 'model_inputs.json').read_text())
N = len(D['names'])
NUMS = range(N)
PAIRS = list(itertools.combinations(NUMS, 2))
TRIPLES = list(itertools.combinations(NUMS, 3))
ORDERS = list(itertools.permutations(NUMS, 3))


def model(temp=None, dry=.4, pace=(.3, .5, .2), shifts=None):
    temp = D['temperature'] if temp is None else temp
    shifts = {} if shifts is None else shifts
    scenarios = []
    for wet, ground_weight in [(0, dry), (1, 1 - dry)]:
        for name, pace_weight in zip(['S', 'M', 'H'], pace):
            weight = ground_weight * pace_weight
            scores = [D['scores'][i] + D['pace' + name][i]
                      + wet * D['wet'][i] + shifts.get(i, 0) for i in NUMS]
            raw = [math.exp((x - 110) / temp) for x in scores]
            total = sum(raw)
            strengths = [x / total for x in raw]
            scenarios.append({'name': ('wet_' if wet else 'dry_') + name,
                              'weight': weight, 'strengths': strengths})

    ordered = {p: 0.0 for p in ORDERS}
    for s in scenarios:
        v = s['strengths']
        for i, j, k in ORDERS:
            p = s['weight'] * v[i] * v[j] / (1 - v[i]) * v[k] / (1 - v[i] - v[j])
            ordered[i, j, k] += p
    win = [0.0] * N
    top2 = [0.0] * N
    top3 = [0.0] * N
    quinella = {p: 0.0 for p in PAIRS}
    wide = {p: 0.0 for p in PAIRS}
    trio = {p: 0.0 for p in TRIPLES}
    for (i, j, k), p in ordered.items():
        win[i] += p
        top2[i] += p
        top2[j] += p
        for h in (i, j, k):
            top3[h] += p
        quinella[tuple(sorted((i, j)))] += p
        for pair in itertools.combinations(sorted((i, j, k)), 2):
            wide[pair] += p
        trio[tuple(sorted((i, j, k)))] += p

    checks = {'win': (sum(win), 1), 'top2': (sum(top2), 2),
              'top3': (sum(top3), 3), 'quinella': (sum(quinella.values()), 1),
              'wide': (sum(wide.values()), 3), 'trio': (sum(trio.values()), 1),
              'trifecta': (sum(ordered.values()), 1)}
    for label, (got, target) in checks.items():
        assert abs(got - target) < 1e-10, (label, got, target)
    assert all(0 <= win[i] <= top2[i] <= top3[i] <= 1 for i in NUMS)
    return {'scenarios': scenarios, 'win': win, 'top2': top2, 'top3': top3,
            'quinella': quinella, 'wide': wide, 'trio': trio,
            'trifecta': ordered, 'checks': checks}


def balanced_percent(values, total_percent):
    units = [x * 1000 for x in values]
    ints = [math.floor(x) for x in units]
    left = round(total_percent * 10) - sum(ints)
    order = sorted(NUMS, key=lambda i: units[i] - ints[i], reverse=True)
    for i in order[:left]:
        ints[i] += 1
    return [x / 10 for x in ints]


def serialize(m):
    out = dict(m)
    for kind in ['quinella', 'wide', 'trio', 'trifecta']:
        out[kind] = {'-'.join(str(i + 1) for i in k): v for k, v in m[kind].items()}
    return out


B = model()
GLOBAL_CASES = {
    'dry_only': model(dry=1), 'wet_only': model(dry=0),
    'slower': model(pace=(.6, .3, .1)), 'faster': model(pace=(.1, .4, .5)),
    'temperature_3': model(temp=3), 'temperature_4_5': model(temp=4.5)
}
LOCAL_CASES = {f'{i+1}_{delta:+d}': model(shifts={i: delta})
               for i in NUMS for delta in (-2, 2)}
ALL_CASES = [B] + list(GLOBAL_CASES.values()) + list(LOCAL_CASES.values())
ROUND = {k: balanced_percent(B[k], target) for k, target in [('win', 100), ('top2', 200), ('top3', 300)]}
ranked = sorted(NUMS, key=lambda i: B['win'][i], reverse=True)
rows = []
for i in NUMS:
    row = {'no': i + 1, 'name': D['names'][i], 'jockey': D['jockeys'][i],
           'rank': ranked.index(i) + 1, 'score': D['scores'][i]}
    for kind in ['win', 'top2', 'top3']:
        row[kind] = ROUND[kind][i]
    row['global_win_range'] = [100 * min(m['win'][i] for m in [B] + list(GLOBAL_CASES.values())),
                               100 * max(m['win'][i] for m in [B] + list(GLOBAL_CASES.values()))]
    row['local_win_range'] = [100 * LOCAL_CASES[f'{i+1}_{delta:+d}']['win'][i] for delta in (-2, 2)]
    row['fair_win_odds'] = 1 / B['win'][i]
    row['standard_buy_odds'] = 1.375 / B['win'][i]
    rows.append(row)


def ticket_probability(m, kind, numbers):
    idx = tuple(x - 1 for x in numbers)
    if kind in ['win', 'top3']:
        return m[kind][idx[0]]
    if kind != 'trifecta':
        idx = tuple(sorted(idx))
    return m[kind][idx]


CANDIDATES = [('win', [8]), ('win', [10]), ('win', [2]), ('win', [5]), ('win', [9]),
              ('win', [3]), ('win', [6]), ('win', [15]), ('win', [14]),
              ('top3', [8]), ('top3', [2]), ('top3', [10]),
              ('wide', [2, 8]), ('wide', [8, 10]), ('wide', [5, 8]), ('wide', [3, 8]),
              ('quinella', [2, 8]), ('quinella', [8, 10]), ('quinella', [5, 8]),
              ('trio', [2, 8, 10]), ('trio', [2, 5, 8]), ('trio', [3, 8, 10]),
              ('trio', [2, 8, 15]), ('trifecta', [8, 10, 2]),
              ('trifecta', [8, 2, 10]), ('trifecta', [10, 8, 2])]
tickets = []
for kind, numbers in CANDIDATES:
    p = ticket_probability(B, kind, numbers)
    all_p = [ticket_probability(m, kind, numbers) for m in ALL_CASES]
    haircut = .7 if kind in ['trio', 'trifecta'] else .8
    # Further conditions can choose the minimum over this explicitly defined
    # one-factor-at-a-time stress grid. It is NOT a confidence interval.
    q = min(haircut * p, min(all_p))
    tickets.append({'kind': kind, 'numbers': numbers, 'p': p,
                    'fair_odds': 1/p, 'standard_buy': 1.1/(haircut*p),
                    'stress_p_range': [min(all_p), max(all_p)],
                    'stress_buy': 1.1/q})

# First-five joint mode over the mixture, not the order of marginal win rates.
mode = None
mode_p = -1.0
sum_first5 = 0.0
top5 = [0.0] * N
for order in itertools.permutations(NUMS, 5):
    p = 0.0
    for s in B['scenarios']:
        part = s['weight']
        remaining = 1.0
        for i in order:
            v = s['strengths'][i]
            part *= v / remaining
            remaining -= v
        p += part
    sum_first5 += p
    for i in order:
        top5[i] += p
    if p > mode_p:
        mode, mode_p = order, p
assert abs(sum_first5 - 1) < 1e-9
assert abs(sum(top5) - 5) < 1e-9

# Independent recalculation of historical position bins supplied by researcher.
history = {
2023:[[1,1,2],[2,9,8],[3,11,8],[4,3,1],[5,15,2],[6,4,8],[7,15,12],[8,11,15],[9,6,5],[10,11,12],[11,8,11],[12,9,15],[13,15,15],[14,11,5],[15,7,12],[16,4,5],[17,2,2]],
2024:[[1,8,3],[2,17,5],[3,15,1],[4,10,4],[5,12,10],[6,8,15],[7,4,2],[8,12,14],[9,6,13],[10,12,16],[11,7,8],[12,4,10],[13,10,8],[14,16,6],[15,1,6],[16,2,10],[17,18,16],[18,3,16]],
2025:[[1,15,4],[2,17,8],[3,4,1],[4,9,8],[5,7,4],[6,18,14],[7,15,14],[8,9,16],[9,2,2],[10,11,8],[11,11,18],[12,6,8],[13,11,3],[14,4,4],[15,11,16],[16,2,8],[17,7,13],[18,1,4]]
}
historical = []
flat = list(itertools.chain.from_iterable(history.values()))
assert len(flat) == 53
for col in [1, 2]:
    for lo, hi in [(1, 4), (5, 9), (10, 99)]:
        subset = [r for r in flat if lo <= r[col] <= hi]
        historical.append({'corner': 1 if col == 1 else 4, 'range': [lo, hi],
                           'n': len(subset), 'wins': sum(r[0] == 1 for r in subset),
                           'top3': sum(r[0] <= 3 for r in subset)})


def wilson(x, n, z=1.959963984540054):
    p = x/n
    den = 1 + z*z/n
    center = (p + z*z/(2*n))/den
    half = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/den
    return [max(0, center-half), min(1, center+half)]


LAPS = {
 'derby': [12.3,10.9,12.4,12.6,12.5,12.2,12.1,11.9,11.6,11.2,11.5,11.5],
 'kobe': [12.6,11.7,13.0,12.8,11.8,12.8,12.8,12.5,11.9,11.2,11.0,11.8],
 'st_lite': [12.3,11.2,12.8,12.9,13.3,12.7,12.2,12.1,11.5,11.4,11.6],
 'kyoto_shimbun': [12.5,11.0,11.8,11.7,11.7,11.7,12.0,11.7,12.1,11.9,11.8],
 'hakodate_2600': [12.7,10.8,11.8,12.1,11.6,12.9,12.7,13.0,12.6,11.7,12.1,11.8,11.8],
 'akan_2600': [13.1,11.7,12.0,11.9,11.9,12.5,12.8,12.5,12.2,12.3,12.3,11.8,12.0]
}
lap_summary = {name: {label: round(sum(part), 1) for label, part in
                     [('total', v), ('first1000', v[:5]), ('last1000', v[-5:]), ('last800', v[-4:]), ('last600', v[-3:])]}
               for name, v in LAPS.items()}

result = {'disclaimer': 'Uncalibrated subjective forecast; sensitivity ranges are not confidence intervals.',
          'rows': rows, 'baseline': serialize(B),
          'global_sensitivity': {k: serialize(v) for k,v in GLOBAL_CASES.items()},
          'local_sensitivity': {k: serialize(v) for k,v in LOCAL_CASES.items()},
          'tickets': tickets,
          'mode_first5': [i+1 for i in mode], 'mode_first5_p': mode_p,
          'sum_first5': sum_first5, 'top5': top5,
          'historical_inputs': history, 'historical_position_bins': historical,
          'wilson': {'favourite_win_4_10': wilson(4,10), 'kyoto_gate1_0_16': wilson(0,16), 'kyoto_gate7_9_23': wilson(9,23)},
          'laps': LAPS, 'lap_summary': lap_summary}
(ROOT / 'model_results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps({'rows': rows, 'tickets': tickets,
                  'scenarios': B['scenarios'], 'checks': B['checks'],
                  'mode_first5': result['mode_first5'], 'mode_first5_p': mode_p,
                  'historical': historical, 'laps': lap_summary}, ensure_ascii=False, indent=2))

