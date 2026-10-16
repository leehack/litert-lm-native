"""Generators from the independent #673 audit adv/adv.py."""
FUNC = "the of and to in a is that it for on with as at by from I you we he they this".split()
CONTENT = ("people time year way day man thing woman life child world school state family student group "
           "country problem hand part place case week company system program question work government number "
           "night point home water room mother area money story fact month lot right study book eye job word "
           "said went made know think see come take want look use find give tell work call try ask need feel").split()
PHRASES = [["I","think"],["you","know"],["of","the"],["in","the"],["the","people"],["and","then"],
           ["one","two","three"],["I'm","sorry"],["we","will"],["at","the","end"],["no"],["where"],["very"]]
def natural(rng, n):
    out = []
    while len(out) < n:
        r = rng.random()
        if r < 0.45: out.append(rng.choice(FUNC))
        elif r < 0.85: out.append(rng.choice(CONTENT))
        else: out.extend(rng.choice(PHRASES))
    return out[:n]
def repeat_phrases(rng, n):
    # Speech dominated by repeated n-grams (period 1..4), e.g. "you know you know", "one two three one two three".
    out = []
    while len(out) < n:
        r = rng.random()
        if r < 0.5:
            p = rng.choice(PHRASES); out.extend(p * rng.randint(2, 3))
        else:
            out.append(rng.choice(FUNC + CONTENT))
    return out[:n]
def periodic_bigram(rng, n):
    # Phrase-level repetition at distance 2..5: "by the people for the people" pattern.
    out = []
    while len(out) < n:
        a, b = rng.choice(FUNC), rng.choice(CONTENT)
        gap = [rng.choice(FUNC + CONTENT) for _ in range(rng.randint(0, 3))]
        out += [a, b] + gap + [a, b] if rng.random() < 0.5 else [rng.choice(FUNC + CONTENT)]
    return out[:n]
def timed(rng, toks, pause_p):
    t = 0.2; words = []
    for w in toks:
        d = rng.uniform(0.18, 0.6); words.append((w, t, t + d))
        t += d + (rng.uniform(0.4, 1.6) if rng.random() < pause_p else rng.uniform(0.0, 0.15))
    return words, t + 0.3
