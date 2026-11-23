"""The phone remote's web app: one page, its script and style, a service worker and manifest (installable), icons."""
import json

REMOTE_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#111317" media="(prefers-color-scheme: dark)">
<meta name="theme-color" content="#f3f4f7" media="(prefers-color-scheme: light)">
<meta name="mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="CM Remote"><meta name="format-detection" content="telephone=no">
<link rel="manifest" href="/manifest.webmanifest"><link rel="apple-touch-icon" href="/icon-180.png">
<link rel="icon" href="/icon-192.png"><link rel="stylesheet" href="/app.css"><title>Channel Mirror Remote</title>
</head><body>
<header class="top"><div class="brand"><span class="logo"></span><span id="pcname">Channel Mirror</span></div>
<button id="conn" class="pill" type="button"><i></i><span>Starting</span></button></header>
<main>
<section id="v-pair" class="view" hidden>
 <h1>Pair this phone</h1>
 <p class="muted">On the PC: Channel Mirror &rsaquo; <b>Phone remote</b> &rsaquo; <b>Pair a phone</b>. Scan the code it
 shows with the camera, or type its 8 digits here.</p>
 <label class="field">Pairing code<input id="code" inputmode="numeric" autocomplete="one-time-code" maxlength="9"
  placeholder="1234 5678"></label>
 <label class="field">This phone's name<input id="devname" maxlength="40" autocomplete="off"></label>
 <button id="pairbtn" class="primary big" type="button">Pair</button>
 <p id="pairmsg" class="msg" role="status"></p>
 <p class="muted small">iPhone / iPad: to use it as an app, tap Share &rsaquo; <b>Add to Home Screen</b> first, open it
 from the Home Screen and pair there - the Home Screen app keeps its own storage. Android: menu &rsaquo; <b>Install app</b>
 / <b>Add to Home screen</b>.</p>
 <p class="muted small">Always open the remote at the same address (best: the PC's Tailscale one) - the pairing is kept
 for that address.</p>
</section>
<section id="v-deck" class="view" hidden>
 <div class="bar"><div class="seg" id="to" role="group" aria-label="Where sounds play">
  <button type="button" data-to="feed">OBS feed</button><button type="button" data-to="here">This PC</button>
  <button type="button" data-to="both">Both</button></div>
  <button id="stopall" class="ghost" type="button">Stop all</button></div>
 <p id="decknote" class="note" hidden></p><div id="grid" class="grid"></div>
</section>
<section id="v-obs" class="view" hidden>
 <p id="obsnote" class="note" hidden></p>
 <div id="obsbody"><h2>Live</h2><div id="outs" class="outs"></div>
 <h2>Scenes</h2><div id="scenes" class="chips"></div>
 <h2>Sources</h2><div id="items" class="list"></div>
 <h2>Audio</h2><div id="mixer" class="list"></div>
 <h2 id="mediah">Media</h2><div id="media" class="list"></div></div>
</section>
<section id="v-music" class="view" hidden>
 <div class="card now"><div id="mtitle" class="title">Nothing playing</div><div id="mfrom" class="muted"></div>
  <input id="mseek" type="range" min="0" max="1" step="1" value="0" aria-label="Position">
  <div class="times"><span id="mpos">0:00</span><span id="mlen">0:00</span></div>
  <div class="transport">
   <button id="mprev" class="icon" type="button" aria-label="Previous"><svg viewBox="0 0 24 24"><path d="M6 5h2v14H6zM20 5v14L9 12z"/></svg></button>
   <button id="mplay" class="primary round" type="button" aria-label="Play"><svg viewBox="0 0 24 24"><path id="mplayi" d="M8 5v14l11-7z"/></svg></button>
   <button id="mnext" class="icon" type="button" aria-label="Next"><svg viewBox="0 0 24 24"><path d="M16 5h2v14h-2zM4 5v14l11-7z"/></svg></button>
   <button id="mstop" class="icon" type="button" aria-label="Stop"><svg viewBox="0 0 24 24"><path d="M6 6h12v12H6z"/></svg></button>
  </div>
  <label class="vol"><svg viewBox="0 0 24 24"><path d="M4 9h4l5-4v14l-5-4H4zM16 8a5 5 0 0 1 0 8"/></svg>
   <input id="mvol" type="range" min="0" max="100" value="80" aria-label="Volume"></label></div>
 <label class="field">Playlist<select id="mlists"></select></label><div id="songs" class="list"></div>
</section>
<section id="v-capture" class="view" hidden>
 <h2>Screen recorder</h2>
 <div class="card rec"><div><div id="recstate" class="title">Not recording</div><div id="recnote" class="muted"></div>
 </div><button id="recbtn" class="primary" type="button">Record</button></div>
 <h2>VTube Studio backgrounds</h2><p id="vtsnote" class="note" hidden></p><div id="vtsmodel" class="muted"></div>
 <div id="bgs" class="grid"></div>
</section>
</main>
<nav class="tabs" id="tabs" hidden>
 <button type="button" data-v="deck"><svg viewBox="0 0 24 24"><path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/></svg>Deck</button>
 <button type="button" data-v="obs"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/></svg>OBS</button>
 <button type="button" data-v="music"><svg viewBox="0 0 24 24"><path d="M9 18V6l11-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/></svg>Music</button>
 <button type="button" data-v="capture"><svg viewBox="0 0 24 24"><rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3z"/></svg>Capture</button>
</nav>
<div id="toast" class="toast" role="status" hidden></div>
<script src="/app.js"></script></body></html>"""

REMOTE_CSS = """:root{--bg:#111317;--card:#1b1e24;--card2:#242830;--line:#2e333c;--text:#eceef2;--muted:#9aa1ad;
--accent:#3b8eea;--accent2:#2f7ad0;--on:#fff;--good:#4cc76a;--bad:#ff6b6b;--warn:#f0b429;--live:#e5484d;
color-scheme:dark}
@media (prefers-color-scheme:light){:root{--bg:#f3f4f7;--card:#fff;--card2:#eceef2;--line:#dcdfe5;--text:#15171b;
--muted:#5b6270;--accent:#0f6cbd;--accent2:#115ea3;--good:#0f7b0f;--bad:#c42b1c;--warn:#9d5d00;--live:#d13438;
color-scheme:light}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--text);font:16px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",
Roboto,sans-serif;-webkit-text-size-adjust:100%}
body{padding:calc(env(safe-area-inset-top) + 56px) 0 calc(env(safe-area-inset-bottom) + 72px);min-height:100vh}
.top{position:fixed;top:0;left:0;right:0;z-index:5;display:flex;align-items:center;justify-content:space-between;
gap:8px;padding:calc(env(safe-area-inset-top) + 8px) 16px 8px;background:var(--bg);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:10px;font-weight:600;min-width:0}
.brand span:last-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.logo{width:26px;height:26px;border-radius:7px;background:var(--accent) url(/icon-192.png) center/cover;flex:none}
.pill{display:flex;align-items:center;gap:6px;border:1px solid var(--line);background:var(--card);color:var(--text);
border-radius:999px;padding:6px 12px;font:inherit;font-size:14px;min-height:36px}
.pill i{width:9px;height:9px;border-radius:50%;background:var(--muted)}
.pill.ok i{background:var(--good)}.pill.retry i{background:var(--warn)}.pill.off i{background:var(--bad)}
main{max-width:760px;margin:0 auto;padding:12px 16px}
h1{font-size:24px;margin:8px 0}h2{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);
margin:22px 2px 8px;font-weight:600}
.muted{color:var(--muted)}.small{font-size:14px}
.field{display:block;margin:14px 0;font-size:14px;color:var(--muted)}
.field input,.field select{display:block;width:100%;margin-top:6px;font:inherit;font-size:17px;color:var(--text);
background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;min-height:48px}
#code{font-size:26px;letter-spacing:.2em;text-align:center}
button{font:inherit;color:inherit;cursor:pointer;touch-action:manipulation}
button:disabled{opacity:.5}
.primary{background:var(--accent);color:var(--on);border:0;border-radius:12px;padding:12px 20px;min-height:48px;
font-weight:600}.primary:active{background:var(--accent2)}
.big{width:100%;font-size:18px;min-height:54px}
.ghost{background:transparent;border:1px solid var(--line);border-radius:12px;padding:10px 14px;min-height:44px}
.msg{min-height:1.4em;font-weight:500}.msg.bad{color:var(--bad)}.msg.good{color:var(--good)}
.note{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:10px;
padding:10px 12px;font-size:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px}
.bar{display:flex;gap:8px;align-items:center;justify-content:space-between;margin-bottom:12px}
.seg{display:flex;background:var(--card2);border-radius:12px;padding:3px;flex:1;max-width:360px}
.seg button{flex:1;border:0;background:transparent;border-radius:9px;padding:9px 6px;min-height:40px;font-size:14px}
.seg button[aria-pressed=true]{background:var(--accent);color:var(--on);font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:10px}
.tile{position:relative;min-height:88px;border-radius:16px;border:1px solid var(--line);background:var(--card);
padding:10px;font-size:15px;font-weight:600;text-align:center;word-break:break-word;display:flex;align-items:center;
justify-content:center;transition:transform .08s}
.tile:active,.tile.hit{transform:scale(.95);background:var(--accent);color:var(--on);border-color:var(--accent)}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{border:1px solid var(--line);background:var(--card);border-radius:12px;padding:10px 14px;min-height:46px;
font-weight:500}.chip.on{background:var(--accent);color:var(--on);border-color:var(--accent)}
.outs{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.out{border:1px solid var(--line);background:var(--card);border-radius:14px;padding:12px 6px;min-height:64px;
font-weight:600;font-size:14px}.out small{display:block;font-weight:400;color:var(--muted);margin-top:2px}
.out.on{background:var(--live);border-color:var(--live);color:#fff}.out.on small{color:#fff}
.list{display:flex;flex-direction:column;gap:1px;border-radius:14px;overflow:hidden;border:1px solid var(--line);
background:var(--line)}.list:empty{display:none}
.row{display:flex;align-items:center;gap:10px;background:var(--card);padding:10px 12px;min-height:56px}
.row .name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row.now{color:var(--accent);font-weight:600}
button.row{border:0;width:100%;text-align:left}
.row input[type=range]{flex:1.3;min-width:80px}
.sw{width:52px;height:32px;border-radius:16px;border:0;background:var(--card2);position:relative;flex:none}
.sw::after{content:"";position:absolute;top:3px;left:3px;width:26px;height:26px;border-radius:50%;background:#fff;
box-shadow:0 1px 2px rgba(0,0,0,.4);transition:left .15s}.sw[aria-checked=true]{background:var(--accent)}
.sw[aria-checked=true]::after{left:23px}
.mini{border:1px solid var(--line);background:var(--card2);border-radius:10px;min-width:44px;min-height:40px;
padding:6px 8px;font-size:13px}.mini.on{background:var(--bad);color:#fff;border-color:var(--bad)}
input[type=range]{width:100%;accent-color:var(--accent);height:32px}
.now .title{font-size:20px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.times{display:flex;justify-content:space-between;font-size:13px;color:var(--muted)}
.transport{display:flex;align-items:center;justify-content:center;gap:18px;margin:8px 0}
.icon{width:52px;height:52px;border-radius:50%;border:0;background:var(--card2);display:flex;align-items:center;
justify-content:center}.round{width:68px;height:68px;border-radius:50%;padding:0;display:flex;align-items:center;
justify-content:center}
svg{width:26px;height:26px;fill:currentColor}
.vol{display:flex;align-items:center;gap:10px;color:var(--muted)}
.vol svg{fill:none;stroke:currentColor;stroke-width:2}
.rec{display:flex;align-items:center;justify-content:space-between;gap:12px}
.rec .title{font-size:18px;font-weight:700}.rec.on .title{color:var(--live)}.rec.on .primary{background:var(--live)}
.tabs{position:fixed;left:0;right:0;bottom:0;z-index:5;display:flex;background:var(--bg);border-top:1px solid var(--line);
padding:4px 4px calc(env(safe-area-inset-bottom) + 4px)}
.tabs button{flex:1;border:0;background:transparent;color:var(--muted);display:flex;flex-direction:column;
align-items:center;gap:2px;font-size:12px;font-weight:600;padding:6px 0;min-height:56px}
.tabs svg{width:24px;height:24px;fill:none;stroke:currentColor;stroke-width:1.8}
.tabs button[aria-current=page]{color:var(--accent)}
.toast{position:fixed;left:16px;right:16px;bottom:calc(env(safe-area-inset-bottom) + 84px);z-index:6;
max-width:520px;margin:0 auto;background:var(--text);color:var(--bg);border-radius:12px;padding:12px 14px;
font-size:15px;box-shadow:0 6px 20px rgba(0,0,0,.35)}
[hidden]{display:none!important}"""

REMOTE_JS = r""""use strict";
(function () {
const $ = id => document.getElementById(id);
// ---- SHA-256 and HMAC in plain JavaScript (WebCrypto's crypto.subtle only exists on https pages) ----
const KS = new Uint32Array([0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,
0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,
0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,
0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,
0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]);
function sha256(m) {
  const n = ((m.length + 9 + 63) >> 6) << 6, b = new Uint8Array(n);
  b.set(m); b[m.length] = 0x80;
  const dv = new DataView(b.buffer), bits = m.length * 8;
  dv.setUint32(n - 8, Math.floor(bits / 0x100000000)); dv.setUint32(n - 4, bits >>> 0);
  const h = new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);
  const w = new Uint32Array(64), r = (x, k) => (x >>> k) | (x << (32 - k));
  for (let o = 0; o < n; o += 64) {
    for (let i = 0; i < 16; i++) w[i] = dv.getUint32(o + i * 4);
    for (let i = 16; i < 64; i++) {
      const a = w[i - 15], c = w[i - 2];
      w[i] = w[i - 16] + (r(a, 7) ^ r(a, 18) ^ (a >>> 3)) + w[i - 7] + (r(c, 17) ^ r(c, 19) ^ (c >>> 10));
    }
    let [A, B, C, D, E, F, G, H] = h;
    for (let i = 0; i < 64; i++) {
      const t1 = (H + (r(E, 6) ^ r(E, 11) ^ r(E, 25)) + ((E & F) ^ (~E & G)) + KS[i] + w[i]) >>> 0;
      const t2 = ((r(A, 2) ^ r(A, 13) ^ r(A, 22)) + ((A & B) ^ (A & C) ^ (B & C))) >>> 0;
      H = G; G = F; F = E; E = (D + t1) >>> 0; D = C; C = B; B = A; A = (t1 + t2) >>> 0;
    }
    h[0] += A; h[1] += B; h[2] += C; h[3] += D; h[4] += E; h[5] += F; h[6] += G; h[7] += H;
  }
  const out = new Uint8Array(32), ov = new DataView(out.buffer);
  for (let i = 0; i < 8; i++) ov.setUint32(i * 4, h[i]);
  return out;
}
const enc = s => new TextEncoder().encode(s), dec = b => new TextDecoder().decode(b);
const hex = b => Array.from(b, x => x.toString(16).padStart(2, "0")).join("");
function cat(...parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0; for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
}
function hmac(key, msg) {
  if (key.length > 64) key = sha256(key);
  const k = new Uint8Array(64); k.set(key);
  return sha256(cat(k.map(x => x ^ 0x5c), sha256(cat(k.map(x => x ^ 0x36), msg))));
}
const rand = n => crypto.getRandomValues(new Uint8Array(n));  // (allowed on plain http pages too)
const sign = (key, method, target, t, nonce, bh) =>
  hex(hmac(enc(key), enc(method + "\n" + target + "\n" + t + "\n" + nonce + "\n" + bh)));
// ---- SPAKE2 pairing, the same as two Channel Mirrors linking (the code is proved, never sent) ----
const P = BigInt("0x__P__"), Q = (P - 1n) / 2n;
function modpow(b, e, m) { let r = 1n; b %= m; while (e > 0n) { if (e & 1n) r = r * b % m; e >>= 1n; b = b * b % m; } return r; }
const big = b => BigInt("0x" + (hex(b) || "0"));
const points = {};
function pairPoint(role) {
  if (!points[role]) {
    const parts = []; for (let i = 0; i < 8; i++) parts.push(sha256(enc("channel-mirror pair point " + role + " " + i)));
    points[role] = modpow(big(cat(...parts)) % P, 2n, P);
  }
  return points[role];
}
const pairCode = code => big(sha256(enc("channel-mirror pair code\n" + code))) % Q;
const pairPub = (code, role, x) => modpow(2n, x, P) * modpow(pairPoint(role), pairCode(code), P) % P;
function pairSecret(code, role, x, pubA, pubB, idA) {
  const other = role === "A" ? pubB : pubA, w = pairCode(code);
  if (!(other > 1n && other < P - 1n) || modpow(other, Q, P) !== 1n) throw new Error("That isn't a pairing answer");
  const n = modpow(pairPoint(role === "A" ? "B" : "A"), w, P);
  const k = modpow(other * modpow(n, P - 2n, P) % P, x, P);
  if (k === 1n) throw new Error("That isn't a pairing answer");
  const seen = sha256(enc([idA, pubA.toString(16), pubB.toString(16), k.toString(16), w.toString(16)].join("\n")));
  const prk = hmac(enc("channel-mirror pair v2"), seen);
  return ["secret", "A", "B"].map(s => hex(hmac(prk, cat(enc(s), new Uint8Array([1])))));
}
// for the drive test: the same answers as remote.remote_vectors() in Python
window.CMRemote = {vectors(v) {
  const xa = BigInt("0x" + v.x_a), xb = BigInt("0x" + v.x_b), pa = pairPub(v.code, "A", xa), pb = pairPub(v.code, "B", xb);
  const [secret, proofA, proofB] = pairSecret(v.code, "A", xa, pa, pb, v.id_a);
  const back = pairSecret(v.code, "B", xb, pa, pb, v.id_a);
  return {sha_abc: hex(sha256(enc("abc"))), sha_long: hex(sha256(enc("a".repeat(200)))),
    hmac_fox: hex(hmac(enc("key"), enc("The quick brown fox jumps over the lazy dog"))),
    sign: sign("0f".repeat(32), "POST", "/api", 1700000000, "ab".repeat(16), hex(sha256(enc("{}")))),
    point_a: pairPoint("A").toString(16), code_w: pairCode(v.code).toString(16), pub_a: pa.toString(16),
    pub_b: pb.toString(16), secret, proof_a: proofA, proof_b: proofB, same: back.join() === [secret, proofA, proofB].join()};
}};
// ---- this phone's pairing: kept by the browser for this address only ----
const KEY = "cm.remote.device";
const store = {
  get() { try { const d = JSON.parse(localStorage.getItem(KEY) || "null"); return d && /^[0-9a-f]{32}$/.test(d.id) && /^[0-9a-f]{64}$/.test(d.key) ? d : null; } catch (e) { return null; } },
  set(d) { try { localStorage.setItem(KEY, JSON.stringify(d)); return true; } catch (e) { return false; } },
  clear() { try { localStorage.removeItem(KEY); } catch (e) { /* nothing kept */ } },
  pref(k, v) { try { if (v === undefined) return localStorage.getItem("cm.remote." + k); localStorage.setItem("cm.remote." + k, v); } catch (e) { return null; } }
};
let dev = store.get(), offset = dev && dev.offset || 0, polling = null, fails = 0, deckRev = null, deck = [];
let last = {}, view = "deck", toastTimer = null, state = {};
const now = () => Math.floor(Date.now() / 1000);
class Unpaired extends Error {}
async function post(path, body, nonce) {
  const data = enc(JSON.stringify(body)), ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 150000);
  const headers = {"Content-Type": "application/json"};
  if (nonce) headers["X-Nonce"] = nonce;
  try {
    const r = await fetch(path, {method: "POST", headers, body: data, cache: "no-store", signal: ctl.signal});
    const out = new Uint8Array(await r.arrayBuffer());
    if (!r.ok) throw new Error(dec(out) || r.statusText);
    return {data: out, sig: r.headers.get("X-Sig") || ""};
  } catch (e) {
    throw e.name === "AbortError" ? new Error("The PC didn't answer in time.") : e.name === "TypeError" ? new Error("Can't reach the PC - is the remote on, and is this the right address?") : e;
  } finally { clearTimeout(timer); }
}
async function api(cmd, args, again) {
  if (!dev) throw new Unpaired("Not paired");
  const body = enc(JSON.stringify({cmd, args: args || {}})), bh = hex(sha256(body));
  const t = now() + offset, nonce = hex(rand(16)), ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 15000);
  let r, data;
  try {
    r = await fetch("/api", {method: "POST", cache: "no-store", signal: ctl.signal, body, headers: {
      "Content-Type": "application/json", "X-Dev": dev.id, "X-Time": String(t), "X-Nonce": nonce, "X-Body": bh,
      "X-Sig": sign(dev.key, "POST", "/api", t, nonce, bh)}});
    data = new Uint8Array(await r.arrayBuffer());
  } catch (e) {
    throw new Error(e.name === "AbortError" ? "The PC didn't answer in time" : "Can't reach the PC");
  } finally { clearTimeout(timer); }
  if (r.status === 409 && !again && (r.headers.get("X-Sig") || "") === sign(dev.key, "REPLY", "/api", 0, nonce, hex(sha256(data)))) {
    const pc = parseInt(JSON.parse(dec(data)).now, 10);  // this phone's clock is off: the PC's time (signed by it)
    if (pc) { offset = pc - now(); return api(cmd, args, true); }
  }
  if (r.status === 401) { unpaired(); throw new Unpaired("This phone isn't paired any more"); }
  if (!r.ok) throw new Error(dec(data) || ("Refused (" + r.status + ")"));
  if ((r.headers.get("X-Sig") || "") !== sign(dev.key, "REPLY", "/api", 0, nonce, hex(sha256(data))))
    throw new Error("The answer wasn't signed by your PC");
  const out = JSON.parse(dec(data));
  if (out.now) offset = out.now - now();
  if (!out.ok) throw new Error(out.error || "Refused");
  return out;
}
// ---- the screens ----
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
function toast(text) {
  const t = $("toast"); t.textContent = text; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 3500);
}
function setConn(kind, text) {
  const c = $("conn"); c.className = "pill " + kind; c.lastChild.textContent = text;
  c.title = kind === "ok" ? "Connected" : "Tap to reconnect";
}
async function act(cmd, args, done) {
  try { const r = await api(cmd, args); if (done) done(r); poll(400); return r; }
  catch (e) { if (!(e instanceof Unpaired)) toast(e.message); return null; }
}
function show(v) {
  view = v; store.pref("view", v);
  for (const s of document.querySelectorAll(".view")) s.hidden = s.id !== "v-" + v;
  for (const b of $("tabs").children) b.setAttribute("aria-current", b.dataset.v === v ? "page" : "false");
  if (v === "music" && dev) loadSongs();
}
function same(k, v) { const s = JSON.stringify(v); if (last[k] === s) return true; last[k] = s; return false; }
function fmt(s) { s = Math.max(0, Math.floor(s || 0)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); }
const dragging = new Set();
function slider(input, send) {
  input.addEventListener("pointerdown", () => dragging.add(input));
  input.addEventListener("touchstart", () => dragging.add(input), {passive: true});
  input.addEventListener("change", () => { dragging.delete(input); send(parseInt(input.value, 10)); });
}
function renderDeck() {
  const g = $("grid"); g.textContent = "";
  for (const s of deck) {
    const b = el("button", "tile", s.name); b.type = "button";
    b.addEventListener("click", () => {
      b.classList.add("hit"); setTimeout(() => b.classList.remove("hit"), 180);
      act("deck.play", {id: s.id, rev: deckRev, to: store.pref("to") || "feed"});
    });
    g.appendChild(b);
  }
  if (!deck.length) g.appendChild(el("p", "muted", "No sounds yet - add them in Channel Mirror's Stream Deck soundboard, or pick a Stream Deck page on the PC's Phone remote page."));
}
function renderTo() { const to = store.pref("to") || "feed"; for (const b of $("to").children) b.setAttribute("aria-pressed", b.dataset.to === to); }
async function loadDeck() {
  try { const r = await api("deck"); deck = r.sounds || []; deckRev = r.rev; renderDeck(); } catch (e) { /* the next poll tries again */ }
}
function renderObs(o) {
  $("obsnote").hidden = !o.error; $("obsnote").textContent = o.error || ""; $("obsbody").hidden = !!o.error;
  if (o.error || same("obs", o)) return;
  const outs = $("outs"); outs.textContent = "";
  for (const [k, name, on, off] of [["stream", "Stream", "LIVE", "off"], ["record", "Record", "recording", "off"], ["vcam", "Virtual cam", "on", "off"]]) {
    const b = el("button", "out" + (o[k] ? " on" : ""), name); b.type = "button";
    b.appendChild(el("small", null, o[k] ? on : off));
    b.addEventListener("click", () => {
      const action = o[k] ? "stop" : "start";
      if (k === "stream" && !confirm(action === "start" ? "Start streaming now?" : "Stop the stream?")) return;
      act("obs", {cmd: "output", args: {output: k, action}});
    });
    outs.appendChild(b);
  }
  const sc = $("scenes"); sc.textContent = "";
  for (const s of o.scenes || []) {
    const b = el("button", "chip" + (s === o.scene ? " on" : ""), s); b.type = "button";
    b.addEventListener("click", () => act("obs", {cmd: "scene", args: {scene: s}}));
    sc.appendChild(b);
  }
  const it = $("items"); it.textContent = "";
  for (const i of o.items || []) {
    const r = el("div", "row"); r.appendChild(el("span", "name", i.name));
    const s = el("button", "sw"); s.type = "button"; s.setAttribute("role", "switch"); s.setAttribute("aria-checked", i.on);
    s.setAttribute("aria-label", "Show " + i.name);
    s.addEventListener("click", () => act("obs", {cmd: "item", args: {scene: o.scene, id: i.id, on: !i.on}}));
    r.appendChild(s); it.appendChild(r);
  }
  const mx = $("mixer"); mx.textContent = "";
  for (const i of o.inputs || []) {
    const r = el("div", "row"); r.appendChild(el("span", "name", i.name));
    const v = el("input"); v.type = "range"; v.min = 0; v.max = 100; v.value = i.volume; v.setAttribute("aria-label", i.name + " volume");
    slider(v, p => act("obs", {cmd: "volume", args: {input: i.name, percent: p}}));
    const m = el("button", "mini" + (i.muted ? " on" : ""), i.muted ? "Muted" : "Mute"); m.type = "button";
    m.addEventListener("click", () => act("obs", {cmd: "mute", args: {input: i.name, muted: !i.muted}}));
    r.appendChild(v); r.appendChild(m); mx.appendChild(r);
  }
  const md = $("media"); md.textContent = "";
  const media = (o.media || []).filter(m => m.kind !== "image_source");
  $("mediah").hidden = !media.length;
  for (const m of media) {
    const r = el("div", "row"); r.appendChild(el("span", "name", m.name + (m.state ? " - " + m.state : "")));
    for (const [a, label] of [["play", "Play"], ["pause", "Pause"], ["restart", "Restart"], ["stop", "Stop"]]) {
      const b = el("button", "mini", label); b.type = "button";
      b.addEventListener("click", () => act("obs", {cmd: "media", args: {input: m.name, action: a}}));
      r.appendChild(b);
    }
    md.appendChild(r);
  }
}
let songsOf = null;
async function loadSongs(list) {
  const sel = $("mlists"); const i = list != null ? list : parseInt(sel.value || "0", 10) || 0;
  try { const r = await api("music.list", {list: i}); songsOf = i; renderSongs(r.songs || []); } catch (e) { /* shown by the next poll */ }
}
function renderSongs(songs) {
  const box = $("songs"); box.textContent = "";
  songs.forEach((s, j) => {
    const b = el("button", "row" + (state.music && state.music.list === songsOf && state.music.song === j ? " now" : ""));
    b.type = "button"; b.appendChild(el("span", "name", (j + 1) + ".  " + s));
    b.addEventListener("click", () => act("music.play", {list: songsOf, song: j}, () => setTimeout(() => loadSongs(songsOf), 300)));
    box.appendChild(b);
  });
  if (!songs.length) box.appendChild(el("div", "row muted", "This playlist is empty."));
}
function renderMusic(m) {
  $("mtitle").textContent = m.title || "Nothing playing";
  $("mfrom").textContent = m.title ? m.playlist + (m.paused ? "  -  paused" : "") : "";
  const seek = $("mseek");
  if (!dragging.has(seek)) { seek.max = Math.max(1, Math.round(m.len)); seek.value = Math.round(m.pos); }
  $("mpos").textContent = fmt(m.pos); $("mlen").textContent = fmt(m.len);
  const vol = $("mvol"); if (!dragging.has(vol)) vol.value = m.volume;
  const playing = m.title && !m.paused;
  $("mplay").setAttribute("aria-label", playing ? "Pause" : "Play");
  $("mplayi").setAttribute("d", playing ? "M7 5h4v14H7zM13 5h4v14h-4z" : "M8 5v14l11-7z");
  if (!same("lists", m.lists)) {
    const sel = $("mlists"), keep = sel.value; sel.textContent = "";
    m.lists.forEach((l, i) => { const o = el("option", null, l.name + "  (" + l.n + ")"); o.value = i; sel.appendChild(o); });
    sel.value = keep && keep < m.lists.length ? keep : String(m.current);
    if (view === "music") loadSongs();
  }
  if (!same("nowsong", [m.list, m.song]) && view === "music" && songsOf != null) loadSongs(songsOf);
}
function renderCapture(c) {
  const r = c.rec || {}, card = $("recbtn").parentElement;
  card.classList.toggle("on", !!r.recording);
  $("recstate").textContent = r.recording ? "Recording  " + fmt(r.secs) : "Not recording";
  $("recnote").textContent = r.note || "";
  $("recbtn").textContent = r.recording ? "Stop" : "Record";
  const v = c.vts || {};
  $("vtsnote").hidden = !v.error; $("vtsnote").textContent = v.error || "";
  $("vtsmodel").textContent = v.model ? "Model: " + v.model : "";
  if (same("vts", v.backgrounds)) return;
  const g = $("bgs"); g.textContent = "";
  for (const b of v.backgrounds || []) {
    const t = el("button", "tile", b.name); t.type = "button";
    t.addEventListener("click", () => { t.classList.add("hit"); setTimeout(() => t.classList.remove("hit"), 180); act("vts.bg", {id: b.id}); });
    g.appendChild(t);
  }
}
function render(s) {
  state = s;
  if (s.pc) $("pcname").textContent = s.pc;
  $("decknote").hidden = !s.deck_note; $("decknote").textContent = s.deck_note || "";
  renderObs(s.obs || {}); if (s.music) renderMusic(s.music); renderCapture(s);
  if (s.deck_rev !== deckRev) loadDeck();
}
async function poll(soon) {
  clearTimeout(polling);
  if (!dev) return;
  if (soon) { polling = setTimeout(() => poll(), soon); return; }
  if (document.hidden) { polling = setTimeout(() => poll(), 5000); return; }
  try {
    render(await api("state")); fails = 0; setConn("ok", "Connected");
    polling = setTimeout(() => poll(), 1500);
  } catch (e) {
    if (e instanceof Unpaired) return;
    fails++; setConn(fails > 2 ? "off" : "retry", fails > 2 ? "Offline - tap to retry" : "Reconnecting");
    polling = setTimeout(() => poll(), Math.min(15000, 1000 * 2 ** Math.min(fails, 4)));
  }
}
function unpaired() {
  clearTimeout(polling); setConn("off", "Not paired");
  $("tabs").hidden = true; for (const s of document.querySelectorAll(".view")) s.hidden = s.id !== "v-pair";
  $("pairmsg").className = "msg bad";
  $("pairmsg").textContent = "This phone isn't paired with this PC any more (it was removed there, or paired again). Pair it again.";
}
function started() {
  $("tabs").hidden = false; $("pcname").textContent = dev.pc || "Channel Mirror";
  show(store.pref("view") || "deck"); renderTo(); poll();
}
async function pair() {
  const code = $("code").value.replace(/\D/g, ""), name = $("devname").value.trim().slice(0, 40) || defaultName();
  const msg = (t, k) => { $("pairmsg").className = "msg " + (k || ""); $("pairmsg").textContent = t; };
  if (code.length !== 8) return msg("Type the 8 digits the PC shows.", "bad");
  $("pairbtn").disabled = true; msg("Working...");
  await new Promise(r => setTimeout(r, 30));
  try {
    const id = hex(rand(16)), x = big(rand(256)) % (Q - 1n) + 1n, pubA = pairPub(code, "A", x);
    const r1 = JSON.parse(dec((await post("/pair/start", {id, name, pub: pubA.toString(16)})).data));
    if (!/^[0-9a-f]{1,512}$/.test(r1.pub || "") || !/^[0-9a-f]{32}$/.test(r1.session || "")) throw new Error("That isn't Channel Mirror's answer");
    const [secret, proofA, proofB] = pairSecret(code, "A", x, pubA, BigInt("0x" + r1.pub), id);
    if (r1.proof !== proofB) throw new Error("Wrong code - check the 8 digits on the PC.");
    msg("Now allow it on the PC: Channel Mirror asks there.");
    const nonce = hex(rand(16)), r2 = await post("/pair/finish", {session: r1.session, proof: proofA}, nonce);
    if (r2.sig !== sign(secret, "REPLY", "/pair/finish", 0, nonce, hex(sha256(r2.data)))) throw new Error("The answer wasn't from your PC");
    const d = JSON.parse(dec(r2.data));
    dev = {id, key: secret, name, pc: String(d.name || "Channel Mirror").slice(0, 60), offset: (d.now || now()) - now()};
    offset = dev.offset;
    if (!store.set(dev)) throw new Error("This browser won't keep the pairing (a private window?) - open it normally.");
    history.replaceState(null, "", "/");
    msg("Paired.", "good"); $("code").value = ""; started();
  } catch (e) { msg(e.message, "bad"); } finally { $("pairbtn").disabled = false; }
}
function defaultName() {
  const u = navigator.userAgent;
  return /iPad/.test(u) ? "iPad" : /iPhone/.test(u) ? "iPhone" : /Android/.test(u) ? "Android phone" : "Browser";
}
// ---- wiring ----
for (const b of $("tabs").children) b.addEventListener("click", () => show(b.dataset.v));
for (const b of $("to").children) b.addEventListener("click", () => { store.pref("to", b.dataset.to); renderTo(); });
$("stopall").addEventListener("click", () => act("deck.stop"));
$("conn").addEventListener("click", () => { fails = 0; if (dev) { setConn("retry", "Reconnecting"); poll(); } });
$("pairbtn").addEventListener("click", pair);
$("code").addEventListener("keydown", e => { if (e.key === "Enter") pair(); });
$("mplay").addEventListener("click", () => {  // shown at once: a second tap before the next poll toggles back
  const m = state.music || {}, pausing = !!(m.title && !m.paused);
  act(pausing ? "music.pause" : "music.resume");
  if (m.title) { m.paused = pausing; renderMusic(m); }
});
$("mprev").addEventListener("click", () => act("music.prev"));
$("mnext").addEventListener("click", () => act("music.next"));
$("mstop").addEventListener("click", () => act("music.stop"));
slider($("mseek"), v => act("music.seek", {secs: v}));
slider($("mvol"), v => act("music.volume", {percent: v}));
$("mlists").addEventListener("change", () => loadSongs());
$("recbtn").addEventListener("click", () => {
  const on = state.rec && state.rec.recording;
  if (on || confirm("Start recording the screen on the PC?")) act(on ? "rec.stop" : "rec.start");
});
document.addEventListener("visibilitychange", () => { if (!document.hidden && dev) poll(); });
if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/sw.js").catch(() => {});
$("devname").value = defaultName();
const m = /[#&]pair=(\d{8})/.exec(location.hash);
if (m) { $("code").value = m[1]; history.replaceState(null, "", "/"); }
if (dev && !m) started();
else { setConn("off", "Not paired"); for (const s of document.querySelectorAll(".view")) s.hidden = s.id !== "v-pair"; }
})();
"""

REMOTE_SW = """const C = "cm-remote-v1", SHELL = ["/", "/app.js", "/app.css", "/manifest.webmanifest", "/icon-192.png"];
self.addEventListener("install", e => e.waitUntil(caches.open(C).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== C)
  .map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {  // the app's own files: fresh when the PC answers, kept for when it doesn't
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || !SHELL.includes(u.pathname)) return;
  e.respondWith(fetch(e.request).then(r => { const c = r.clone(); caches.open(C).then(x => x.put(e.request, c)); return r; })
    .catch(() => caches.match(e.request)));
});"""

_FILES: dict = {}


def remote_files():
    """{path: (content type, bytes)}: every file the web app has (built once; the icons are painted here)."""
    if not _FILES:
        from .peers import PAIR_P
        from .remote import remote_icon
        manifest = {"name": "Channel Mirror Remote", "short_name": "CM Remote", "start_url": "/", "scope": "/",
                    "display": "standalone", "background_color": "#111317", "theme_color": "#111317",
                    "description": "Soundboard, OBS, music, recorder and VTube Studio from your phone",
                    "icons": [{"src": f"/icon-{n}.png", "sizes": f"{n}x{n}", "type": "image/png", "purpose": "any"}
                              for n in (192, 512)]}
        _FILES.update({
            "/": ("text/html; charset=utf-8", REMOTE_HTML.encode()),
            "/app.css": ("text/css; charset=utf-8", REMOTE_CSS.encode()),
            "/app.js": ("text/javascript; charset=utf-8", REMOTE_JS.replace("__P__", f"{PAIR_P:x}").encode()),
            "/sw.js": ("text/javascript; charset=utf-8", REMOTE_SW.encode()),
            "/manifest.webmanifest": ("application/manifest+json", json.dumps(manifest).encode()),
            **{f"/icon-{n}.png": ("image/png", remote_icon(n)) for n in (180, 192, 512)}})
    return _FILES
