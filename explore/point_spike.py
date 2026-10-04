"""THROWAWAY exploration, not product code. Reads manifests/Parquet, never runs stages.
Run: TMPDIR="$PWD/explore/.cache/tmp" .venv/bin/python explore/point_spike.py
All writes are under explore/.cache except RESULTS.json; see the design memo.
"""
import hashlib
import importlib.metadata as md
import json
import math
import os
import platform
import resource
import shutil
import threading
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import h3
import numpy as np
import psutil
import pyarrow.parquet as pq
import pygeohash
from geographiclib.geodesic import Geodesic
from rapidfuzz.distance import JaroWinkler
from s2sphere import Angle, Cap, CellId, LatLng, RegionCoverer
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
ROOT = Path('/Users/ujjwal/Downloads/solo/thereabouts/data')
CACHE = HERE / '.cache'
CACHE.mkdir(exist_ok=True)
RADIUS = 10000.0
START = time.perf_counter()
SAMPLES = []
STOP = threading.Event()
INPUTS = {}


def guard():
    while not STOP.wait(.1):
        rss = psutil.Process().memory_info().rss
        free = shutil.disk_usage('/').free
        SAMPLES.append((rss, free))
        if rss > 1_800_000_000 or free < 5_500_000_000:
            os._exit(77)


threading.Thread(target=guard, daemon=True).start()


def digest(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def manifest(rel):
    p = ROOT / rel / 'manifest.json'
    INPUTS[str(p)] = {'sha256': digest(p), 'mtime_ns': p.stat().st_mtime_ns}
    return json.loads(p.read_text())


def source_files(src):
    m = manifest('normalized/' + src)
    paths = []
    for e in m['partitions']:
        if e['kind'] != 'places':
            continue
        # Rebase historical absolute manifest paths, never follow the old root.
        p = ROOT / e['path'].split('/data/', 1)[-1]
        assert p.resolve().is_relative_to(ROOT / 'normalized' / src)
        assert p.stat().st_size == e['size']
        paths.append(str(p))
    return paths, m['source_release']


def extract():
    db = duckdb.connect()
    db.execute("SET memory_limit='384MB'; SET threads=1")
    db.execute("SET preserve_insertion_order=false")
    db.execute("SET temp_directory=?", [str(CACHE / 'spill')])
    db.execute("SET max_temp_directory_size='128MB'")
    info = {}
    for src in ('geonames', 'overture'):
        t = time.perf_counter()
        paths, release = source_files(src)
        cols = ('source_id,name,name_en,latitude,longitude,feature_class,'
                'feature_code,subtype,country_code,source_release,license,provenance')
        count = 0
        writer = None
        for path in paths:
            db.read_parquet(path).create_view('src')
            rows = db.sql(f"SELECT {cols} FROM src WHERE country_code IN ('BE','JP')").to_arrow_table()
            if writer is None:
                writer = pq.ParquetWriter(CACHE / f'{src}.parquet', rows.schema)
            writer.write_table(rows)
            count += rows.num_rows
        writer.close()
        info[src] = dict(release=release, manifest_files=len(paths),
                         selected_rows=count, seconds=time.perf_counter()-t)
    db.close()
    return info


def key(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s or '').casefold()
                   if c.isalnum())


def load(src, cc):
    rows = pq.read_table(CACHE / f'{src}.parquet',
                         filters=[('country_code', '=', cc)]).to_pylist()
    result = []
    for r in rows:
        p = json.loads(r.pop('provenance'))
        up = p.get('upstream', {})
        if src == 'overture' and (r['subtype'] not in
                ('country', 'dependency', 'region', 'county', 'localadmin', 'locality')
                or (up.get('perspectives') or {}).get('includes')):
            continue
        names = [r['name'], r['name_en']]
        if src == 'geonames':
            names += [p.get('asciiname'), *p.get('alternate_names_untyped', '').split(',')]
        r['aliases'] = sorted({key(n) for n in names} - {''})
        r['qid'] = up.get('wikidata')
        result.append(r)
    return sorted(result, key=lambda r:r['source_id']), len(rows)


def ecef(rows):
    ll = np.radians([[r['latitude'], r['longitude']] for r in rows])
    lat, lon = ll.T
    a, e2 = 6378137.0, 6.6943799901413165e-3
    n = a / np.sqrt(1-e2*np.sin(lat)**2)
    return np.column_stack((n*np.cos(lat)*np.cos(lon), n*np.cos(lat)*np.sin(lon),
                            n*(1-e2)*np.sin(lat)))


def geodesic(a, b):
    return Geodesic.WGS84.Inverse(a['latitude'], a['longitude'],
                                 b['latitude'], b['longitude'])['s12']


def block(gn, ov, mode):
    t = time.perf_counter()
    if mode == 'ecef':
        tree = cKDTree(ecef(gn))
        built = time.perf_counter()
        groups = tree.query_ball_point(ecef(ov), RADIUS)
    else:
        idx = defaultdict(list)
        for j, r in enumerate(gn):
            y, x = r['latitude'], r['longitude']
            cell = (h3.latlng_to_cell(y, x, 6) if mode.startswith('h3') else
                    CellId.from_lat_lng(LatLng.from_degrees(y, x)).parent(10).id()
                    if mode == 's2' else pygeohash.encode(y, x, precision=5))
            idx[cell].append(j)
        built = time.perf_counter()
        groups = []
        cover = RegionCoverer()
        cover.min_level = cover.max_level = 10
        for r in ov:
            y, x = r['latitude'], r['longitude']
            if mode.startswith('h3'):
                cells = h3.grid_disk(h3.latlng_to_cell(y, x, 6), int(mode[-1]))
            elif mode == 's2':
                cap = Cap.from_axis_angle(LatLng.from_degrees(y, x).to_point(),
                                          Angle.from_radians(RADIUS / 6335439.0))
                cells = [c.id() for c in cover.get_covering(cap)]
            else:
                # Exact geohash-5 rectangle cover; bounded to BE/JP (no pole/dateline).
                dy = math.degrees(RADIUS / 6335439.0)
                dx = dy / math.cos(math.radians(abs(y)+dy))
                step = 180 / 4096
                cells = [pygeohash.encode((i+.5)*step-90, (j+.5)*step-180, precision=5)
                         for i in range(math.floor((y-dy+90)/step), math.floor((y+dy+90)/step)+1)
                         for j in range(math.floor((x-dx+180)/step), math.floor((x+dx+180)/step)+1)]
            groups.append([j for cell in cells for j in idx.get(cell, [])])
    pairs = {(i, int(j)) for i, group in enumerate(groups) for j in group}
    return pairs, dict(build_s=built-t, query_materialize_s=time.perf_counter()-built,
                       total_s=time.perf_counter()-t, candidates=len(pairs))


def metrics(pred, truth):
    tp = len(pred & truth)
    return dict(predicted=len(pred), reference=len(truth), true_positive=tp,
                false_positive=len(pred-truth), false_negative=len(truth-pred),
                precision=tp/len(pred) if pred else None,
                recall=tp/len(truth) if truth else None)


def country(cc, gm):
    t = time.perf_counter()
    gn, ng = load('geonames', cc)
    ov, no = load('overture', cc)
    gi = {r['source_id']: j for j, r in enumerate(gn)}
    oi = {r['source_id']: i for i, r in enumerate(ov)}
    entry = next(e for e in gm['tables'] if e['kind']=='places' and e['country']==cc)
    p = ROOT / entry['path']
    assert p.resolve().is_relative_to((ROOT/'golden').resolve())
    assert digest(p) == entry['sha256']
    INPUTS[str(p)] = {'sha256': digest(p), 'mtime_ns': p.stat().st_mtime_ns}
    gold = pq.read_table(p, columns=['geonames_id','overture_ids','link']).to_pylist()
    truth = {(oi[o], gi[g['geonames_id']]) for g in gold if g['geonames_id'] in gi
             for o in g['overture_ids'] or [] if o in oi}
    assert truth
    truth_degree = Counter(j for i,j in truth)
    blocks, bm = {}, {}
    for mode in ('ecef', 'h3_k2', 'h3_k4', 's2', 'geohash'):
        blocks[mode], bm[mode] = block(gn, ov, mode)
    # Chord <= surface geodesic: exact filter yields the complete radius baseline.
    dt = time.perf_counter()
    ds = {pair: geodesic(ov[pair[0]], gn[pair[1]]) for pair in blocks['ecef']}
    exact = {pair for pair, d in ds.items() if d <= RADIUS}
    for mode, pairs in blocks.items():
        bm[mode].update(radius_misses=len(exact-pairs),
                        radius_recall=len(pairs & exact)/len(exact),
                        golden_recall=len(pairs & truth)/len(truth))
    distance_s = time.perf_counter()-dt
    st = time.perf_counter()
    truth_evidence = {}
    by_i = defaultdict(list)
    for i, j in sorted(exact):
        a, b = ov[i], gn[j]
        compatible = b['feature_class'] == ('A' if a['subtype'] in
                                            ('country','dependency','region') else 'P')
        n = max((JaroWinkler.normalized_similarity(x,y) for x in a['aliases']
                 for y in b['aliases']), default=0)
        score = .65*n + .25*math.exp(-ds[i,j]/2000) + .1*compatible
        e = dict(i=i, j=j, distance_m=ds[i,j], name_similarity=n,
                 type_compatible=compatible, score=score, confidence=None)
        if (i,j) in truth:
            truth_evidence[i,j] = e
        if compatible:
            by_i[i].append(e)
    winners = []
    for es in by_i.values():
        es.sort(key=lambda e: (-e['score'], gn[e['j']]['source_id']))
        e = es[0]
        e['margin'] = e['score']-(es[1]['score'] if len(es)>1 else 0)
        if e['score'] >= .83 and e['name_similarity'] >= .9 and e['margin'] >= .05:
            winners.append(e)
    chosen, strict, used = [], set(), defaultdict(list)
    for e in sorted(winners, key=lambda e: (-e['score'], ov[e['i']]['source_id'])):
        i, j = e['i'], e['j']
        if not used[j]:
            strict.add((i,j))
        elif not (ov[i]['qid'] and all(ov[k]['qid']==ov[i]['qid'] for k in used[j])):
            continue
        used[j].append(i)
        chosen.append(e)
    pred = {(e['i'],e['j']) for e in chosen}
    evaluated = {i for i,j in truth}
    failure = Counter()
    for pair in truth-pred:
        e = truth_evidence.get(pair)
        i,j = pair
        reason = ('outside_radius' if e is None else 'type' if not e['type_compatible'] else
                  'score_or_name' if e['score']<.83 or e['name_similarity']<.9 else
                  'not_top_candidate' if by_i[i][0]['j']!=j else
                  'margin' if e['margin']<.05 else 'assignment')
        failure[reason] += 1
    review_ids = {'092f4136-52e3-470a-bebf-511d0b87977d':'golden_preferred: municipality versus component settlement',
                  'bd5f123a-4ed5-4679-b2a8-ff4ef55049d1':'spike_preferred_provisionally: identical names 94m versus 75km; audit Wikidata',
                  '5911dd15-7cfa-4461-b286-ae3e6e6f54b0':'unresolved: nearby spelling variant versus distant exact homonym',
                  '08e5e3e0-abc0-46ce-9dd6-faef4fa14c8e':'spike_plausible: ligature variant; no independent label',
                  'c5ee4c97-0270-424d-86a2-6449feb8591a':'golden_preferred: exact Mashiki alias versus Mamizu/pinyin Mashui',
                  '1a66a583-cf4d-4938-8670-353fc9c1e30b':'golden_preferred: Tsunagi versus distinct Kotsunagi name',
                  '01143241-d602-430a-b5d5-348ca1abb26b':'golden_preferred: Yokohama exact multilingual aliases; spike distance penalty',
                  'ea82f079-9595-4712-a528-35e027a85875':'unresolved: two same-name GeoNames records; golden selects PPLA2'}
    def describe(pair):
        i,j = pair
        a,b = ov[i],gn[j]
        return dict(overture=a['source_id'], geonames=b['source_id'],
                    names=[a['name'],a['name_en'],b['name'],b['name_en']],
                    aliases=[a['aliases'],b['aliases']],
                    types=[a['subtype'],a['feature_class'],b['feature_code']],
                    coordinates=[[a['latitude'],a['longitude']],[b['latitude'],b['longitude']]],
                    distance_m=ds.get(pair) if pair in ds else geodesic(a,b),
                    overture_qid=a['qid'])
    evidence = [dict(**describe((e['i'],e['j'])), **{k:v for k,v in e.items() if k not in ('i','j','distance_m')},
                     relation='same_as', cardinality='1:N' if len(used[e['j']])>1 else '1:1',
                     rule='shared_overture_qid' if len(used[e['j']])>1 else 'greedy',
                     releases=[gn[e['j']]['source_release'], ov[e['i']]['source_release']]) for e in chosen]
    (CACHE/f'{cc}-correspondences.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
    disagreements = {label: [describe(pair) for pair in sorted(pairs)] for label,pairs in
                     [('spike_only',pred-truth),('golden_only',truth-pred)]}
    (CACHE/f'{cc}-disagreements.json').write_text(json.dumps(disagreements,ensure_ascii=False,indent=2))
    (CACHE/f'{cc}-unmatched.json').write_text(json.dumps(dict(
        overture=[r['source_id'] for i,r in enumerate(ov) if i not in {i for i,j in pred}],
        geonames=[r['source_id'] for j,r in enumerate(gn) if j not in {j for i,j in pred}])))
    review = [dict(**describe(pair), in_spike=pair in pred, in_golden=pair in truth,
                   assessment=review_ids[ov[pair[0]]['source_id']])
              for pair in sorted((truth-pred)|(pred-truth)) if ov[pair[0]]['source_id'] in review_ids]
    return dict(review=review, golden_miss_reasons=dict(failure),
                golden_multi_groups=sum(n>1 for n in truth_degree.values()),
                golden_distinct_geonames=len(truth_degree), geonames_rows=ng, overture_rows=no, overture_eligible=len(ov),
                golden_edges=len(truth), radius_pairs=len(exact), blocking=bm,
                strict_1to1=metrics(strict,truth), rule_many=metrics(pred,truth),
                labelled_overture_domain=metrics({p for p in pred if p[0] in evaluated},truth),
                predicted_outside_labelled_domain=sum(i not in evaluated for i,j in pred),
                one_to_many_groups=sum(len(v)>1 for v in used.values()),
                unmatched_overture=len(ov)-len(pred), unmatched_geonames=len(gn)-len(used),
                distance_filter_s=distance_s, scoring_assignment_artifacts_s=time.perf_counter()-st,
                total_s=time.perf_counter()-t,
                golden_methods=dict(Counter((json.loads(g['link']) or {}).get('method','none') for g in gold)))


if __name__ == '__main__':
    result = dict(throwaway=True, timestamp=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                  machine=dict(system=platform.platform(), processor=platform.processor(),
                               logical_cpus=os.cpu_count(), physical_ram=psutil.virtual_memory().total),
                  python=platform.python_version(), versions={p:md.version(p) for p in
                  ['numpy','scipy','h3','duckdb','pyarrow','geographiclib','rapidfuzz','s2sphere','pygeohash']},
                  radius_m=RADIUS, score_weights=[.65,.25,.1], threshold=.83, margin=.05,
                  code_sha256=digest(Path(__file__)))
    result['extraction'] = extract()
    gm = manifest('golden')
    result['countries'] = {}
    for cc in ('BE','JP'):
        result['countries'][cc] = country(cc,gm)
        print(cc, json.dumps(result['countries'][cc]), flush=True)
    result['inputs'] = INPUTS
    result['input_manifests_and_golden_unchanged'] = all(
        digest(Path(p))==v['sha256'] and Path(p).stat().st_mtime_ns==v['mtime_ns']
        for p,v in INPUTS.items())
    result['coordinate_bounds_m'] = {str(s): s**3/(24*6335439.0**2) for s in (100,1000,10000,100000)}
    result['reconcile_module_lines'] = {p.name:len(p.read_text().splitlines()) for p in
                                     (HERE.parent/'pipeline/engines/reconcile').glob('*.py')}
    result['matched_micro'] = {k:sum(c['rule_many'][k] for c in result['countries'].values())
                               for k in ('predicted','reference','true_positive','false_positive','false_negative')}
    for k,den in [('precision','predicted'),('recall','reference')]:
        result['matched_micro'][k] = result['matched_micro']['true_positive']/result['matched_micro'][den]
    result['elapsed_s'] = time.perf_counter()-START
    result['max_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if platform.system()=='Darwin' else 1024)
    result['min_free_disk_bytes'] = min(f for r,f in SAMPLES)
    result['explore_bytes'] = sum(p.stat().st_size for p in HERE.rglob('*') if p.is_file())
    result['venv_bytes'] = sum(p.stat().st_size for p in (HERE.parent/'.venv').rglob('*') if p.is_file())
    STOP.set()
    (HERE/'RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
