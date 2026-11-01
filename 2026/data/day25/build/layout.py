"""Octilinear schematic layout by multicriteria hill climbing on a grid.

A simplified version of Stott, Rodgers, Martinez-Ovando & Walker, "Automatic metro map layout
using multicriteria optimization", IEEE TVCG 17(1), 2011 (doi:10.1109/TVCG.2010.24), written
for this page. Pure Python and numpy, deterministic (fixed seed).

The contracted network (interchanges, termini, branch points and a few bend stations as nodes;
the chains of ordinary stations between them as edges) is placed on an integer grid. Every edge
is drawn octilinear: straight if its two ends already line up at 0, 45 or 90 degrees, otherwise
as one straight and one 45-degree leg with a single bend (which leg comes first is part of the
search). One grid unit is a third of the target gap between two stations.

Moves are tried in turn and kept whenever they lower the total cost: a node (alone, with its
neighbours, or with the other end of an edge) to a nearby grid point, the step shrinking from 6
grid units to 1; a node jumped to where one of its edges would be ideal (true sector or the next,
target length), carrying any branch that hangs off it; a hanging branch swung a quarter or half
turn; an edge's bend flipped; and, where edges still crowd, a whole neighbourhood shifted. Cost:
  * spacing: for each edge, gaps x (drawn gap / target gap - 1)^2, so stations end up evenly spaced
  * bends inside an edge, and turns where a line passes through a node (45 deg 1, 90 deg 3, 135 deg 12)
  * direction: an edge drawn more than 22.5 deg off its true compass direction is penalised,
    heavily past 67.5 deg, so north stays north
  * clearance: two edges that share no node must stay a grid unit apart; they may cross only
    where the real lines cross too (as the Downtown Line crosses the North South Line), and then
    only cleanly;
    two edges leaving a node may not leave in the same direction.
"""
import math
import random

import numpy as np

W_LEN, W_INBEND, W_REL, W_CLOSE, W_OVER, W_CROSS = 5.0, 1.2, 6.0, 400.0, 400.0, 2.0
TURN = {0: 0.0, 1: 1.5, 2: 4.0, 3: 25.0, 4: 80.0}
SPACING = 3          # grid units per station gap
DMIN = 1.0           # grid units between edges that share no node


def _dir8(dx, dy):
    """Octilinear direction 0..7 of a vector that is octilinear (0 = east, counter-clockwise)."""
    return int(round(math.degrees(math.atan2(dy, dx)) / 45)) % 8


def edge_pts(a, b, flip):
    """The drawn polyline of an edge from grid point a to b: 2 or 3 points."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    adx, ady = abs(dx), abs(dy)
    if dx == 0 or dy == 0 or adx == ady:
        return [a, b]
    sx, sy = (1 if dx > 0 else -1), (1 if dy > 0 else -1)
    m = min(adx, ady)
    diag = (a[0] + sx * m, a[1] + sy * m)              # diagonal leg first
    if adx > ady:
        straight = (a[0] + dx - sx * m, a[1])          # straight leg first
    else:
        straight = (a[0], a[1] + dy - sy * m)
    return [a, straight if flip else diag, b]


def _proper_cross(p, q, r, s):
    """True if segments pq and rs cross at a single interior point."""
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    d1, d2, d3, d4 = cross(r, s, p), cross(r, s, q), cross(p, q, r), cross(p, q, s)
    return d1 * d2 < 0 and d3 * d4 < 0


def _seg_dist(p, q, r, s):
    """Shortest distance between segments pq and rs."""
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    d1, d2, d3, d4 = cross(r, s, p), cross(r, s, q), cross(p, q, r), cross(p, q, s)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4:
        return 0.0

    def pt(x, a, b):
        ab = (b[0] - a[0], b[1] - a[1])
        L = ab[0] ** 2 + ab[1] ** 2
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((x[0] - a[0]) * ab[0] + (x[1] - a[1]) * ab[1]) / L))
        return math.hypot(x[0] - a[0] - t * ab[0], x[1] - a[1] - t * ab[1])
    return min(pt(p, r, s), pt(q, r, s), pt(r, p, q), pt(s, p, q))


class Layout:
    def __init__(self, P0, E, turns, may_cross=(), seed=25, spread=1.2, anchor=0.0, start=None):
        """P0: true positions of the nodes, in station gaps; start: where to begin (default P0);
        E: [(a, b, hops)]; turns: [((e1, d1), (e2, d2))]."""
        self.E = E
        self.may_cross = {(min(e, f), max(e, f)) for e, f in may_cross}
        self.n = len(P0)
        self.hops = [h for (_, _, h) in E]
        self.geo = [math.atan2(P0[b][1] - P0[a][1], P0[b][0] - P0[a][0]) for (a, b, _) in E]
        self.inc = [[] for _ in range(self.n)]
        for e, (a, b, _) in enumerate(E):
            self.inc[a].append(e)
            self.inc[b].append(e)
        self.turns = list(turns)
        self.turns_of = [[] for _ in E]
        for k, ((e1, _), (e2, _)) in enumerate(self.turns):
            self.turns_of[e1].append(k)
            self.turns_of[e2].append(k)
        self.rng = random.Random(seed)
        # start: the true positions on the grid, nudged apart where two land on one point
        pos, used = [], set()
        for x, y in (P0 if start is None else start):
            p = (int(round(x * SPACING * spread)), int(round(y * SPACING * spread)))
            r = 0
            while p in used:
                r += 1
                p = (p[0] + r * (1 if r % 2 else -1), p[1])
            used.add(p)
            pos.append(p)
        self.pos = pos
        self.home = list(pos)       # where each node starts: its true position, scaled
        self.anchor = anchor
        self.flip = [False] * len(E)
        self.geom = [None] * len(E)
        for e in range(len(E)):
            self._geom(e)

    def _geom(self, e):
        a, b, _ = self.E[e]
        pts = edge_pts(self.pos[a], self.pos[b], self.flip[e])
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        self.geom[e] = (pts, (min(xs), min(ys), max(xs), max(ys)))

    # ---- cost pieces ----
    def edge_cost(self, e):
        pts, _ = self.geom[e]
        L = sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(pts, pts[1:]))
        h = self.hops[e]
        gap = L / (h * SPACING)
        c = W_LEN * h * (gap - 1) ** 2 + (60.0 * h * (0.55 - gap) if gap < 0.55 else 0)
        if len(pts) == 3:
            c += W_INBEND
        if self.anchor:   # a gentle pull back towards the true position, shared among a node's edges
            for v in self.E[e][:2]:
                p, h0 = self.pos[v], self.home[v]
                c += self.anchor * ((p[0] - h0[0]) ** 2 + (p[1] - h0[1]) ** 2) / len(self.inc[v])
        a, b = pts[0], pts[-1]
        d = abs((math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) - math.degrees(self.geo[e]) + 180) % 360 - 180)
        if d > 22.5:
            c += W_REL * ((d - 22.5) / 45) ** 2 * 4 + (40 * (d - 67.5) / 45 if d > 67.5 else 0)
        return c

    def out_dir(self, e, node_is_a):
        pts, _ = self.geom[e]
        p, q = (pts[0], pts[1]) if node_is_a else (pts[-1], pts[-2])
        return _dir8(q[0] - p[0], q[1] - p[1])

    def turn_cost(self, k):
        (e1, d1), (e2, d2) = self.turns[k]
        # arriving along e1 (direction of travel d1), leaving along e2
        m_in = (self.out_dir(e1, d1 < 0) + 4) % 8          # travel direction into the node
        m_out = self.out_dir(e2, d2 > 0)
        t = (m_out - m_in) % 8
        return TURN[min(t, 8 - t)]

    def pair_cost(self, e, f):
        if e == f:
            return 0.0
        (pe, be), (pf, bf) = self.geom[e], self.geom[f]
        if be[0] > bf[2] + DMIN or bf[0] > be[2] + DMIN or be[1] > bf[3] + DMIN or bf[1] > be[3] + DMIN:
            return 0.0
        ae, bE, _ = self.E[e]
        af, bF, _ = self.E[f]
        shared = {ae, bE} & {af, bF}
        c, vp = 0.0, None
        for v in shared:
            if self.out_dir(e, ae == v) == self.out_dir(f, af == v):
                c += W_OVER
        shared_pts = {self.pos[v] for v in shared}
        allowed = (min(e, f), max(e, f)) in self.may_cross
        for p, q in zip(pe, pe[1:]):
            for r, s in zip(pf, pf[1:]):
                if shared_pts & {p, q} & {r, s}:
                    continue   # both legs start at the shared node: handled by the direction test
                d = _seg_dist(p, q, r, s)
                if d < DMIN:
                    if allowed and _proper_cross(p, q, r, s):
                        c += W_CROSS   # the real lines cross here too: a clean crossing is fine
                    else:
                        c += W_CLOSE * (DMIN - d + (1.0 if d == 0 else 0))
        return c

    def local(self, edges):
        edges = set(edges)
        c = sum(self.edge_cost(e) for e in edges)
        ts = set()
        for e in edges:
            ts.update(self.turns_of[e])
        c += sum(self.turn_cost(k) for k in ts)
        for e in edges:
            for f in range(len(self.E)):
                if f in edges and f < e:
                    continue
                c += self.pair_cost(e, f)
        return c

    def total(self):
        return self.local(range(len(self.E)))

    # ---- search ----
    def _try_shift(self, nodes, dx, dy):
        """Move a set of nodes together by (dx, dy); keep it if the cost drops."""
        return self._try_place(nodes, [(self.pos[v][0] + dx, self.pos[v][1] + dy) for v in nodes])

    def _try_place(self, nodes, new):
        """Put nodes at new grid points; keep it if the cost drops."""
        others = set(self.pos) - {self.pos[v] for v in nodes}
        if len(set(new)) < len(new) or any(p in others for p in new):
            return False
        aff = sorted({e for v in nodes for e in self.inc[v]})
        before = self.local(aff)
        old = [self.pos[v] for v in nodes]
        for v, p in zip(nodes, new):
            self.pos[v] = p
        for e in aff:
            self._geom(e)
        if self.local(aff) < before - 1e-9:
            return True
        for v, p in zip(nodes, old):
            self.pos[v] = p
        for e in aff:
            self._geom(e)
        return False

    def _branches(self):
        """For every edge whose removal cuts the network: (edge, attach node, the cut-off side)."""
        out = []
        for e, (a, b, _) in enumerate(self.E):
            seen, todo = {b}, [b]
            while todo:
                u = todo.pop()
                for f in self.inc[u]:
                    if f == e:
                        continue
                    for w in self.E[f][:2]:
                        if w not in seen:
                            seen.add(w)
                            todo.append(w)
            if a in seen:
                continue
            side, root = (seen, a) if len(seen) <= self.n - len(seen) else (set(range(self.n)) - seen, b)
            out.append((e, root, sorted(side)))
        return out

    def _ideal_moves(self, branches):
        """Jump a node (and anything hanging off it) to where one of its edges would be ideal:
        its true compass sector, or the next one, at the target length."""
        hang = {}
        for e, root, side in branches:
            for v in side:
                if self.E[e][0] == v or self.E[e][1] == v:
                    hang.setdefault(v, side)
        moved = 0
        for v in range(self.n):
            for e in self.inc[v]:
                a, b, h = self.E[e]
                u = a if b == v else b
                ang = self.geo[e] if a == u else self.geo[e] + math.pi
                k0 = math.degrees(ang) / 45
                for k in sorted({math.floor(k0) % 8, math.ceil(k0) % 8}):
                    dx, dy = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)][k]
                    L = h * SPACING / (math.sqrt(2) if dx and dy else 1)
                    p = (self.pos[u][0] + int(round(dx * L)), self.pos[u][1] + int(round(dy * L)))
                    ddx, ddy = p[0] - self.pos[v][0], p[1] - self.pos[v][1]
                    if not (ddx or ddy):
                        continue
                    group = hang.get(v, [v])
                    if u in group:
                        group = [v]
                    if self._try_shift(group, ddx, ddy) or (len(group) > 1 and self._try_shift([v], ddx, ddy)):
                        moved += 1
                        break
        return moved

    def _branch_turns(self, branches):
        """Swing a hanging branch a quarter or half turn about the node it hangs from."""
        moved = 0
        for e, root, side in branches:
            if len(side) > self.n // 3:
                continue
            ox, oy = self.pos[root]
            for rot in ((0, -1, 1, 0), (0, 1, -1, 0), (-1, 0, 0, -1)):
                new = [(ox + rot[0] * (self.pos[v][0] - ox) + rot[1] * (self.pos[v][1] - oy),
                        oy + rot[2] * (self.pos[v][0] - ox) + rot[3] * (self.pos[v][1] - oy)) for v in side]
                if self._try_place(side, new):
                    moved += 1
                    break
        return moved

    def _try_flip(self, e):
        a, b, _ = self.E[e]
        if len(self.geom[e][0]) == 2:
            return False
        before = self.local([e])
        self.flip[e] = not self.flip[e]
        self._geom(e)
        if self.local([e]) < before - 1e-9:
            return True
        self.flip[e] = not self.flip[e]
        self._geom(e)
        return False

    def run(self, log=None):
        steps = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
        nb = [sorted({v} | {x for e in self.inc[v] for x in self.E[e][:2]}) for v in range(self.n)]
        branches = self._branches()
        for r in (6, 4, 2, 1, 1):
            for it in range(30):
                moved = self._ideal_moves(branches) + self._branch_turns(branches)
                order = list(range(self.n))
                self.rng.shuffle(order)
                for v in order:                       # one node
                    for dx, dy in steps:
                        if self._try_shift([v], dx * r, dy * r):
                            moved += 1
                            break
                for v in order:                       # a node with its neighbours
                    for dx, dy in steps:
                        if self._try_shift(nb[v], dx * r, dy * r):
                            moved += 1
                            break
                for e in range(len(self.E)):          # both ends of an edge
                    a, b, _ = self.E[e]
                    for dx, dy in steps:
                        if self._try_shift([a, b], dx * r, dy * r):
                            moved += 1
                            break
                for e in range(len(self.E)):
                    if self._try_flip(e):
                        moved += 1
                moved += self._unknot(steps)
                if log:
                    log(f'radius {r} pass {it}: {moved} moves, cost {self.total():.1f}')
                if not moved:
                    break
        return self

    def _unknot(self, steps):
        """Where edges still crowd, shift whole neighbourhoods around them at once."""
        bad = set()
        for e in range(len(self.E)):
            for f in range(e + 1, len(self.E)):
                if self.pair_cost(e, f) >= W_CLOSE:
                    bad.update(self.E[e][:2])
                    bad.update(self.E[f][:2])
        moved = 0
        for v in sorted(bad):
            for rad in (2, 4, 6, 9):
                cl = [u for u in range(self.n) if max(abs(self.pos[u][0] - self.pos[v][0]), abs(self.pos[u][1] - self.pos[v][1])) <= rad]
                done = False
                for k in (1, 2):
                    for dx, dy in steps:
                        if self._try_shift(cl, dx * k, dy * k):
                            moved += 1
                            done = True
                            break
                    if done:
                        break
                if done:
                    break
        return moved

    def report(self):
        """Counts that describe the finished drawing."""
        cross = 0
        self.conflicts = []
        for e in range(len(self.E)):
            for f in range(e + 1, len(self.E)):
                if self.pair_cost(e, f) >= W_CLOSE:
                    cross += 1
                    self.conflicts.append((e, f))
        turns = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
        for (e1, d1), (e2, d2) in self.turns:
            m_in = (self.out_dir(e1, d1 < 0) + 4) % 8
            m_out = self.out_dir(e2, d2 > 0)
            t = (m_out - m_in) % 8
            turns[min(t, 8 - t)] += 1
        inbend = sum(1 for g in self.geom if len(g[0]) == 3)
        return {'conflicts': cross, 'turns_by_45': turns, 'edges_with_a_bend': inbend}
