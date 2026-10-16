import random, subprocess, sys
VOCAB = ("the a of to and in is it you that he was for on are with as his they be at one have this from or "
         "had by word but what some we can out other were all there when up use your how said an each she which do "
         "their time if will way about many then them write would like so these her long make thing see him two has "
         "look more day could go come did number sound no most people my over know water than call first who may down "
         "side been now find any new work part take get place made live where after back little only round man year "
         "came show every good me give our under name very through just form sentence great think say help low line").split()
GARB = "um tree one uh eh oh ah".split()
W = 5.0
def utter(rng, n):
    t = 0.2; words = []
    for _ in range(n):
        d = rng.uniform(0.18, 0.6); words.append((rng.choice(VOCAB), t, t + d))
        t += d + (rng.uniform(0.4, 1.2) if rng.random() < 0.12 else rng.uniform(0.0, 0.15))
    return words, t + 0.3
def windows(words, total, r, rng, garble):
    hop = W * (1 - r); out = []; s = 0.0
    while True:
        e = s + W; win = []
        for (w, a, b) in words:
            if b <= s or a >= e: continue
            if a >= s and b <= e: win.append(w); continue
            frac = (min(b, e) - max(a, s)) / (b - a)
            if a < s:   # cut at window start
                if frac > 0.6: win.append(w)
                elif frac > 0.25 and garble: win.extend(rng.sample(GARB, rng.choice([1, 2])))
            else:       # cut at window end
                if frac > 0.6: win.append(w)
                elif frac > 0.25 and garble: win.append(rng.choice(GARB))
        out.append(" ".join(win))
        if e >= total: break
        s += hop
    return out
def ops(ref, hyp):
    n, m = len(ref), len(hyp)
    D = [[0]*(m+1) for _ in range(n+1)]
    for i in range(n+1): D[i][0] = i
    for j in range(m+1): D[0][j] = j
    for i in range(1, n+1):
        for j in range(1, m+1):
            D[i][j] = min(D[i-1][j]+1, D[i][j-1]+1, D[i-1][j-1] + (ref[i-1] != hyp[j-1]))
    i, j, ins, dele, sub = n, m, 0, 0, 0
    while i or j:
        if i and j and D[i][j] == D[i-1][j-1] + (ref[i-1] != hyp[j-1]):
            sub += ref[i-1] != hyp[j-1]; i -= 1; j -= 1
        elif j and D[i][j] == D[i][j-1] + 1: ins += 1; j -= 1
        else: dele += 1; i -= 1
    return ins, dele, sub
def run(ratios, garble, N, nwords, seed):
    rng0 = random.Random(seed); cases = [utter(rng0, rng0.randint(*nwords)) for _ in range(N)]
    for r in ratios:
        rng = random.Random(seed + 1)
        wins = [windows(w, t, r, rng, garble) for (w, t) in cases]
        inp = "\n===\n".join("\n".join(x) for x in wins) + "\n"
        outs = subprocess.run(["./driver", str(r)], input=inp, capture_output=True, text=True, check=True).stdout.split("\n")[:N]
        I = D = S = refw = bad = 0; nwin = 0; dupcases = dropcases = 0
        for (w, t), o, x in zip(cases, outs, wins):
            ref = [a for a, _, _ in w]; hyp = o.split(); i, d, s = ops(ref, hyp)
            I += i; D += d; S += s; refw += len(ref); nwin += len(x)
            bad += (i + d + s) > 0; dupcases += i > 0; dropcases += d > 0
        print(f"garble={garble} r={r}: WER={(I+D+S)/refw:.3f} ins={I/refw:.3f} del={D/refw:.3f} sub={S/refw:.3f} "
              f"cases_with_err={bad}/{N} with_ins={dupcases} with_del={dropcases} windows={nwin}")
if __name__ == "__main__":
    for g in (False, True):
        run([0.0, 0.2, 0.4, 0.6], g, int(sys.argv[1]), (20, 40), 7)
