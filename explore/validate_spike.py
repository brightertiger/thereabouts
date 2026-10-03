"""THROWAWAY: validate measured artifacts and a few coordinate invariants locally."""
import hashlib
import json
import runpy
from collections import defaultdict
from pathlib import Path

import numpy as np

here = Path(__file__).resolve().parent
r = json.loads((here / 'RESULTS.json').read_text())
assert hashlib.sha256((here / 'point_spike.py').read_bytes()).hexdigest() == r['code_sha256']
assert r['input_manifests_and_golden_unchanged']
assert r['max_rss_bytes'] < 2_000_000_000 and r['min_free_disk_bytes'] > 5_000_000_000
assert r['explore_bytes'] + r['venv_bytes'] < 2_000_000_000
for cc, c in r['countries'].items():
    es = json.loads((here / '.cache' / f'{cc}-correspondences.json').read_text())
    groups = defaultdict(list)
    assert len(es) == c['rule_many']['predicted'] == len({e['overture'] for e in es})
    for e in es:
        assert e['score'] >= .83 and e['margin'] >= .05 and e['type_compatible']
        assert e['confidence'] is None and 0 <= e['distance_m'] <= r['radius_m']
        groups[e['geonames']].append(e)
    for es in groups.values():
        if len(es) > 1:
            assert es[0]['overture_qid'] and len({e['overture_qid'] for e in es}) == 1
    assert sum(len(es) > 1 for es in groups.values()) == c['one_to_many_groups']
    assert sum(c['golden_miss_reasons'].values()) == c['rule_many']['false_negative']
    assert all(c['blocking'][m]['radius_recall'] == 1 for m in ('ecef','h3_k4','s2','geohash'))
ns = runpy.run_path(str(here / 'point_spike.py'))
anchors = [{'latitude': y, 'longitude': x} for y,x in [(0,0),(0,90),(90,0)]]
xyz = ns['ecef'](anchors)
assert np.allclose(xyz, [[6378137,0,0],[0,6378137,0],[0,0,6356752.314245]], atol=1e-5, rtol=0)
for a,b in [({'latitude':0,'longitude':179.99},{'latitude':0,'longitude':-179.99}),
            ({'latitude':89.99,'longitude':0},{'latitude':89.99,'longitude':180})]:
    chord = np.linalg.norm(np.diff(ns['ecef']([a,b]),axis=0))
    d = ns['geodesic'](a,b)
    assert chord <= d+1e-8 and d-chord <= d**3/(24*6335439**2)+1e-8
ns['STOP'].set()
assert sum(len(p.read_text().splitlines()) for p in here.glob('*.py')) < 400
memo = here.parent / 'docs/explorations/2026-10-04-point-conflation.md'
assert 300 <= len(memo.read_text().splitlines()) <= 500
print('PASS: resource budgets, metrics, evidence, cardinality, coordinates and deliverable sizes')
