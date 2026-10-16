#!/usr/bin/env python3
"""Reproduce/extend audit adv.py, real.py and mono.py on real merger binaries."""
import argparse
import json
import random
import sys
from pathlib import Path
from qualify_asr_untimed_overlap import replay
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests/asr_overlap'))
import sim
from adversarial import natural, repeat_phrases, periodic_bigram, timed


def distance(a, b):
    # Myers bit-vector Levenshtein distance, checked against sim.ops in tests.
    if not a: return len(b)
    masks = {}
    for i, w in enumerate(a): masks[w] = masks.get(w, 0) | (1 << i)
    vp, vn, score, high = ~0, 0, len(a), 1 << (len(a)-1)
    for w in b:
        eq = masks.get(w, 0)
        x = eq | vn
        d = (((eq & vp) + vp) ^ vp) | eq
        hp, hn = vn | ~(d | vp), vp & d
        score += bool(hp & high) - bool(hn & high)
        hp = (hp << 1) | 1
        vn, vp = hp & x, (hn << 1) | ~(x | hp)
    return score


def evaluate(upstream, fixed, count=400, corpora=None):
    prose = (Path(__file__).resolve().parents[1] / 'tests/asr_overlap/prose.txt').read_text().split()
    rows = []
    for win in (5, 30):
      sim.W = win
      for corpus in (corpora or ('ordinary', 'adjacent', 'natural', 'repeat_phrases', 'periodic_bigram', 'prose', 'periodic')):
       for garble in (False, True):
        refs, chunks = [], []
        seeds = (5, 17, 29, 41) if corpus == 'prose' else (101, 202, 303)
        for pause in ((0.12,) if corpus in ('ordinary', 'adjacent') else (0.12, 0.35)):
         for seed in seeds:
          rng = random.Random(seed if corpus == 'prose' else seed * 7 + win)
          cases = []
          for i in range(count):
            # Scale length at 30s to keep multi-window boundary exposure.
            n = rng.randint(20, 45) * (win // 5)
            if corpus in ('ordinary', 'adjacent'):
                ws, total = sim.utter(rng, n)
                if corpus == 'adjacent':
                    for j in range(1, len(ws)):
                        if rng.random() < .3: ws[j] = (ws[j-1][0], *ws[j][1:])
                cases.append((ws,total)); continue
            if corpus == 'prose':
                start = rng.randrange(0, len(prose)-n); words = prose[start:start+n]
            elif corpus == 'periodic':
                phrase = (['no'], ['la']*4+['hey'], ['one','two','three'])[i % 3]
                words = (phrase * (n//len(phrase)+1))[:n]
            else: words = {'natural':natural, 'repeat_phrases':repeat_phrases, 'periodic_bigram':periodic_bigram}[corpus](rng,n)
            cases.append(timed(rng, words, pause))
          r = random.Random(seed+1)
          chunks.extend(sim.windows(ws,t,.4,r,garble) for ws,t in cases)
          refs.extend([w for w,_,_ in ws] for ws,t in cases)
        outputs = [replay(d,chunks,.4) for d in (upstream,fixed)]
        edits = [[distance(ref,hyp.split()) for ref,hyp in zip(refs,out)] for out in outputs]
        a,b=edits
        row=dict(corpus=corpus, seconds=win, garbled=garble, cases=len(refs),
                 upstream_exact=sum(x==0 for x in a), patched_exact=sum(x==0 for x in b),
                 regressed=sum(x==0 and y>0 for x,y in zip(a,b)),
                 fixed=sum(x>0 and y==0 for x,y in zip(a,b)),
                 edit_worse=sum(y>x for x,y in zip(a,b)), edit_better=sum(y<x for x,y in zip(a,b)))
        row['examples'] = [dict(ref=' '.join(refs[i]), chunks=chunks[i], upstream=outputs[0][i], patched=outputs[1][i])
                           for i in [j for j,(x,y) in enumerate(zip(a,b)) if y>x][:2]]
        rows.append(row); print(json.dumps(row), flush=True)
    return rows

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('upstream',type=Path); p.add_argument('fixed',type=Path)
    p.add_argument('--corpora', nargs='+'); p.add_argument('--count',type=int,default=400); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); a.output.write_text(json.dumps(evaluate(a.upstream,a.fixed,a.count,a.corpora),indent=2)+'\n')
