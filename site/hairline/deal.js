/**
 * Deal: a loose stack of eight cards. The pointer's height picks one card; it
 * slides out of the pile while the cards above it lift to let it through,
 * staggered outwards from the one chosen, on the 700ms lift curve. Each card
 * carries its place in the stack as one lit pip in a 4 x 2 grid. The slider is
 * the stagger, in ms.
 *
 * The pattern: scrub and pick. A tween per card, a stagger by distance, and a
 * hit test on the cards' RESTING heights, so a card sliding out cannot change
 * which one is chosen. With nobody pointing, it deals on its own, one model at
 * a time, and the read-out names the card that is out.
 */
const { Cam, fit, lerp, mk, place, pointer, poly, proj, rad, register, reducedMotion, disposer, rrect, tdone, tset, tval, tween } = HL;

// the models of the pile, bottom card first: the names the read-out gives (all of them models Clyde can be pointed at)
const NAMES = ["qwen3-0.6b", "haiku", "qwen3:8b", "codestral", "gemini-flash", "muse-glimmer", "glm-4.5", "gpt-5.4"];
// the order the dealer works through on its own, a shuffle that visits every card
const ORDER = [5, 2, 7, 0, 3, 6, 1, 4], DWELL = 2100, START = 3200, RESUME = 1200;

const N = 8, CW = 56, CH = 78, GAP = 8, TK = 1.4, SLIDE = 46, UP = 18;
// each card rests a little off the one below it: turn in degrees, then x and y in world units
const REST = [[-7, -2, 2], [4, 3, -3], [-3, -3, 1], [8, 2, -2], [-5, -1, 3], [2, 4, -1], [-9, -4, 2], [5, 1, -2]];
const SHAPE = rrect(-CW / 2, -CH / 2, CW / 2, CH / 2, 4.5, 5).map((q) => [q.u, q.v]);

function mount({ stage, svg, read }, value) {
  const bag = disposer();
  let stag = value;

  // fitted to the pile with its far corners, the dealt card at full slide and the lifted cards, so no pose leaves the frame
  const C = Cam(45, 0.5, 2.0);
  const pts = [];
  for (const x of [-CW, CW + SLIDE]) for (const y of [-CH, CH]) for (const z of [-TK, N * GAP + UP]) pts.push([x, y, z]);
  fit(C, pts, 200, 168);
  const P = proj(C);

  const g = mk("g", {}, svg);
  const cards = [];
  for (let i = 0; i < N; i++) {
    const grp = mk("g", {}, g);
    const back = mk("path", { class: "lo" }, grp), face = mk("path", { class: "sil" }, grp);
    const pips = [];
    for (let k = 0; k < 8; k++) pips.push(mk("circle", { r: 1.05, class: "dot " + (k === i ? "m" : "off") }, grp));
    cards.push({ back, face, pips, s: tween(0), u: tween(0) });
  }

  /** A point in card i's own plane, turned, slid and lifted: its screen position. */
  const at = (i, lx, ly, s, z) => {
    const [t, jx, jy] = REST[i], a = rad(lerp(t, t * 0.2, s)), c = Math.cos(a), n = Math.sin(a);
    return P(jx + lx * c - ly * n + s * SLIDE, jy + lx * n + ly * c - s * 7, z);
  };
  const draw = (i, s, u) => {
    const cd = cards[i], z = i * GAP + u * UP;
    cd.face.setAttribute("d", poly(SHAPE.map((q) => at(i, q[0], q[1], s, z))));
    cd.back.setAttribute("d", poly(SHAPE.map((q) => at(i, q[0], q[1], s, z - TK))));
    cd.pips.forEach((el, k) => place(el, at(i, -CW / 2 + 7 + (k % 4) * 3.6, -CH / 2 + 7 + Math.floor(k / 4) * 3.6, s, z)));
  };

  // autoplay, ambient and the only motion without input: deal on a schedule while nobody is pointing; the pointer takes over
  let held = false, step = 0, nextAt = 0;
  const B = register(stage, (_dt, now) => {
    let moving = false;
    const auto = !held && !reducedMotion();
    if (auto) {
      if (!nextAt) nextAt = now + START;
      if (now >= nextAt) { setActive(ORDER[step++ % ORDER.length]); nextAt = now + DWELL; }
    }
    cards.forEach((cd, i) => {
      draw(i, tval(cd.s, now), tval(cd.u, now));
      if (!tdone(cd.s, now) || !tdone(cd.u, now)) moving = true;
    });
    return moving || auto;
  });
  bag.add(B.unregister);

  // hit test: the RESTING screen height of each card. The band runs from the pile to where a dealt card lands, so the
  // pointer can follow a card out without losing it, and nothing that moves is ever tested.
  const rest = cards.map((_, i) => at(i, 0, 0, 0, i * GAP)[1]);
  const x0 = at(0, -CW, 0, 0, 0)[0] - 10, x1 = at(0, CW, 0, 1, 0)[0] + 10;
  const hit = ([x, y]) => {
    if (x < x0 || x > x1 || y < rest[N - 1] - 46 || y > rest[0] + 46) return -1;
    return rest.reduce((best, v, i) => (Math.abs(y - v) < Math.abs(y - rest[best]) ? i : best), 0);
  };

  let act = -1;
  const mark = (a) => cards.forEach((cd, i) => {
    cd.face.classList.toggle("hi", a < 0 ? i === N - 1 : i === a);   // at rest the top card is the bright one; a choice takes it
    cd.pips[i].classList.toggle("m", i !== a);
  });
  mark(-1);

  /** Deals card a (-1 puts the pile back). The stagger spreads out from the card dealt, or the one let go. */
  function setActive(a) {
    if (a === act) return;
    const now = performance.now(), from = a >= 0 ? a : act;
    act = a;
    cards.forEach((cd, i) => {
      const delay = Math.abs(i - from) * stag;
      tset(cd.s, i === a ? 1 : 0, now, delay);
      tset(cd.u, a >= 0 && i > a ? 1 : 0, now, delay);
    });
    mark(a);
    read.textContent = a < 0 ? "rest" : NAMES[a];
    B.wake();
  }

  cards.forEach((_, i) => draw(i, 0, 0));
  bag.add(pointer(stage, {
    move: (p) => { held = true; setActive(hit(p)); },
    leave: () => { held = false; nextAt = performance.now() + RESUME; setActive(-1); },
  }));
  bag.add(() => svg.replaceChildren());

  return { set: (v) => { stag = v; }, destroy: bag.dispose };
}

hairline({
  name: "deal",
  means: "A pile of eight cards, one per model, dealt in turn: the one at the pointer's height slides out and names itself.",
  rules: [1, 2, 5, 7, 8],
  range: [0, 40, 90],
  mount,
});
