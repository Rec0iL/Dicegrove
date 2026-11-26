#!/usr/bin/env python3
"""Writes the sample SVGs in examples/d6/ (pips + a few test features).

They use several colors on purpose (white background, red, black, blue,
green stroke, a purple gradient) so that color merging, strokes, holes,
gradients and transforms all get used.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "d6")

HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 100 100" '
        'width="100" height="100">\n')
BG = '<rect x="2" y="2" width="96" height="96" rx="14" fill="#ffffff"/>\n'

P = {  # pip positions
    1: [(50, 50)],
    2: [(28, 28), (72, 72)],
    3: [(26, 26), (50, 50), (74, 74)],
    4: [(28, 28), (72, 28), (28, 72), (72, 72)],
    5: [(26, 26), (74, 26), (50, 50), (26, 74), (74, 74)],
    6: [(28, 24), (72, 24), (28, 50), (72, 50), (28, 76), (72, 76)],
}


def pips(n, color, r=9):
    return "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>\n' for x, y in P[n])


faces = {
    # 1: one big red pip with a white ring inside (evenodd hole)
    1: BG + '<path fill="#d32f2f" fill-rule="evenodd" d="M50 22a28 28 0 1 0 0.01 0Z '
            'M50 36a14 14 0 1 0 0.01 0Z"/>\n',
    # 2: black pips + a green stroked diagonal line (stroke -> area)
    2: BG + pips(2, "#212121") +
       '<path d="M30 70 L70 30" stroke="#2e7d32" stroke-width="6" '
       'stroke-linecap="round" fill="none"/>\n',
    # 3: blue pips, the middle one is a red star drawn on top (painter's order)
    3: BG + pips(3, "#1e88e5", 10) +
       '<polygon fill="#d32f2f" points="50,36 54,46 65,46 56,53 59,64 50,57 41,64 44,53 35,46 46,46"/>\n',
    # 4: black pips inside a transformed group (transform handling)
    4: BG + '<g transform="translate(50 50) rotate(45) translate(-50 -50)">' +
       pips(4, "#212121", 8) + '</g>\n',
    # 5: pips with a purple gradient fill
    5: '<defs><linearGradient id="g"><stop offset="0" stop-color="#8e24aa"/>'
       '<stop offset="1" stop-color="#5e35b1"/></linearGradient></defs>\n' +
       BG + pips(5, "url(#g)", 8),
    # 6: red pips with a black outline (fill + stroke on the same shape)
    6: BG + "".join(f'<circle cx="{x}" cy="{y}" r="8" fill="#d32f2f" stroke="#212121" '
                    f'stroke-width="3"/>\n' for x, y in P[6]),
}

os.makedirs(OUT, exist_ok=True)
for n, body in faces.items():
    with open(os.path.join(OUT, f"{n}.svg"), "w") as f:
        f.write(HEAD + body + "</svg>\n")
print("wrote", OUT)
