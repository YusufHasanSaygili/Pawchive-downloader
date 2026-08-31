from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from collections import deque
from importlib import resources
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from rich.console import Console

from .app import RunOptions, run
from .downloader import DownloadOptions, DownloadSummary
from .history import HISTORY_FILENAME
from .urls import parse_target


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pawchive Downloader</title>
<script>try{var d=localStorage.getItem("pawchive-theme");document.documentElement.dataset.theme=d||(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light")}catch(e){document.documentElement.dataset.theme="light"}</script>
<style>
/* A coloured-sketch treatment: flat fills with ink outlines, the way the
   artwork is cel-shaded. The light palette deliberately sits AWAY from the
   mascot's own colours -- her hair is hue 0deg at 24% saturation, so the page
   is ground in a warm neutral and the accent is amber at hue 40deg. That
   leaves her the only rose-brown mass on screen, which keeps her visible.
   The theme attribute is set by a script in <head>, before first paint. */
:root{
  color-scheme:light;
  --brand:#a7492f;                 /* Korone's colour, kept for reference */
  --bg:#f5f1ea; --surface:#fffdf8; --sunken:#efe9df;
  --border:#ded5c6; --edge:#8a7f70; --outline:#3a332c;
  --text:#3a332c; --dim:#6b6153;
  --accent:#d9a441;                /* flat fills */
  --accent-deep:#a87a20;           /* anything that must carry meaning */
  --accent-text:#7d5a12;           /* amber as text */
  --on-accent:#3a332c;
  --danger:#a8321f;
  --focus:#3a332c; --focus-inner:#fffdf8;
  --mascot:none;
  --ink:.14;                       /* wallpaper strength */
  --r:8px; --r-lg:16px;
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px;
  --ui:"Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;
  --mono:"Cascadia Mono",Consolas,"Courier New",monospace;
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#140d0b; --surface:#1e1613; --sunken:#0d0807;
  --border:#362926; --edge:#76615b; --outline:#76615b;
  --text:#ece4e1; --dim:#a3938f;
  --accent:#d9a441; --accent-deep:#d9a441; --accent-text:#d9a441;
  --on-accent:#1a1206;
  --danger:#e8776b;
  /* A light ring alone sits at 1.79:1 on the amber button, so dark needs the
     dark separator ring underneath it. */
  --focus:#f0c060; --focus-inner:#140d0b;
  --mascot:brightness(.84) saturate(.94) contrast(1.04);
  --ink:.06;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 var(--ui)}
.shell{position:relative;z-index:1;max-width:1000px;margin:0 auto;padding:var(--s6) var(--s5) var(--s6)}
/* Paws and bones tiled behind everything. Inline SVG rather than a data:
   URI, so the default-src 'self' policy does not have to be widened. */
.wallpaper{position:fixed;inset:0;width:100%;height:100%;z-index:0;pointer-events:none}
.wallpaper .ink{fill:var(--accent-deep);opacity:var(--ink)}

.masthead{display:flex;justify-content:space-between;align-items:baseline;gap:var(--s4);
  padding-bottom:var(--s4);border-bottom:1.5px solid var(--border);margin-bottom:var(--s5)}
h1{margin:0;font-size:20px;font-weight:400;letter-spacing:0}
h1 b{font-weight:600}
.sub{margin:var(--s1) 0 0;color:var(--dim);font-size:13px}
.tools{display:flex;align-items:center;gap:var(--s3);flex:none}
.state{display:inline-flex;align-items:center;gap:var(--s2);color:var(--dim);font-size:13px}
.state::before{content:"";width:8px;height:8px;border-radius:50%;background:currentColor}
.state.running{color:var(--accent-text)}
.state.done{color:var(--text)}

.cols{display:grid;grid-template-columns:1fr 1fr;gap:var(--s5)}
.panel{position:relative;display:flex;flex-direction:column;border:1.5px solid var(--outline);
  border-radius:var(--r-lg);background:var(--surface);padding:var(--s4)}
h2{margin:0 0 var(--s4);font-size:14px;font-weight:600}
/* She sits just above the panel's top border, peeking over it. */
.peek{position:absolute;left:14px;bottom:100%;margin-bottom:1.3px;width:118px;
  pointer-events:none;user-select:none;z-index:2;filter:var(--mascot)}

label.field{display:block;margin-bottom:var(--s3)}
.field > span{display:block;color:var(--dim);font-size:12px;margin-bottom:var(--s1)}
textarea,input[type=text],input[type=number]{
  width:100%;font:14px/1.5 var(--ui);color:var(--text);background:var(--sunken);
  border:1.5px solid var(--edge);border-radius:var(--r);padding:var(--s2) var(--s3)}
textarea{min-height:132px;resize:vertical;font:13px/1.6 var(--mono)}
textarea:focus,input:focus{border-color:var(--text)}
::placeholder{color:var(--dim);opacity:1}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:var(--s3)}

.opts{display:grid;gap:var(--s2);margin:var(--s4) 0}
.opt{display:flex;align-items:center;gap:var(--s2);min-height:24px;cursor:pointer}
.opt input{width:16px;height:16px;margin:0;accent-color:var(--accent-deep);cursor:pointer}

.actions{display:flex;gap:var(--s2);flex-wrap:wrap}
/* Ink outline plus flat fill, the same construction as the drawing. */
button{font:600 14px/1 var(--ui);padding:var(--s3) var(--s4);border-radius:var(--r);
  border:1.5px solid var(--outline);background:var(--surface);color:var(--text);cursor:pointer}
button:hover:not(:disabled){background:var(--sunken)}
button.go{background:var(--accent);color:var(--on-accent)}
button.go:hover:not(:disabled){background:var(--accent);filter:brightness(1.08)}
button.halt{color:var(--danger);border-color:var(--danger)}
button:disabled{opacity:.4;cursor:default}
button.mini{padding:var(--s1) var(--s2);font-size:12px;font-weight:600;border-radius:var(--r)}
:focus-visible{outline:2px solid transparent;outline-offset:2px;
  box-shadow:0 0 0 2px var(--focus-inner),0 0 0 4px var(--focus)}

.figures{display:grid;grid-template-columns:repeat(4,1fr);gap:1.5px;
  background:var(--outline);border:1.5px solid var(--outline);border-radius:var(--r);overflow:hidden}
.figure{background:var(--surface);padding:var(--s3)}
.figure b{display:block;font:400 22px/1.2 var(--mono);font-variant-numeric:tabular-nums}
.figure b.hot{color:var(--danger)}
.figure span{display:block;color:var(--dim);font-size:12px;margin-top:var(--s1)}

.meter{height:10px;margin:var(--s4) 0 var(--s2);background:var(--sunken);
  border:1.5px solid var(--outline);border-radius:999px;overflow:hidden}
.meter > i{display:block;height:100%;width:0;background:var(--accent-deep);transition:width .3s}
.count{color:var(--dim);font:12px/1 var(--mono);font-variant-numeric:tabular-nums}

.log{flex:1;min-height:220px;margin-top:var(--s4);overflow:auto;white-space:pre-wrap;
  background:var(--sunken);border:1.5px solid var(--edge);border-radius:var(--r);
  padding:var(--s3);color:var(--text);font:12px/1.6 var(--mono)}
.log .line{padding-left:8ch;text-indent:-8ch}
.log .bad{color:var(--danger)}
.log .meh{color:var(--dim)}
.note{margin:var(--s3) 0 0;min-height:20px;color:var(--danger);font-size:13px}

.colophon{display:flex;justify-content:space-between;align-items:center;gap:var(--s4);
  margin-top:var(--s5);padding-top:var(--s4);border-top:1.5px solid var(--border);
  color:var(--dim);font-size:12px}

@media(max-width:760px){
  .shell{padding:var(--s5) var(--s4)}
  .cols{grid-template-columns:1fr}
  .masthead{flex-direction:column;align-items:flex-start;gap:var(--s2)}
  .colophon{flex-direction:column;align-items:flex-start}
  .peek{width:96px}
}
</style></head><body>
<svg class="wallpaper" aria-hidden="true" focusable="false"><defs><g id="paw"><path d="M0,-4C4.3,-4 8,-0.2 8.2,4C8.5,8.6 4.8,11 0,11C-4.8,11 -8.5,8.6 -8.2,4C-8,-0.2 -4.3,-4 0,-4Z"/><ellipse cx="-9.6" cy="-7.4" rx="3.1" ry="4.3" transform="rotate(-30 -9.6 -7.4)"/><ellipse cx="-3.5" cy="-12.2" rx="3.1" ry="4.5" transform="rotate(-11 -3.5 -12.2)"/><ellipse cx="3.5" cy="-12.2" rx="3.1" ry="4.5" transform="rotate(11 3.5 -12.2)"/><ellipse cx="9.6" cy="-7.4" rx="3.1" ry="4.3" transform="rotate(30 9.6 -7.4)"/></g><g id="bone"><rect x="-13" y="-2.3" width="26" height="4.6" rx="2.3"/><circle cx="-13" cy="-3.5" r="4.4"/><circle cx="-13" cy="3.5" r="4.4"/><circle cx="13" cy="-3.5" r="4.4"/><circle cx="13" cy="3.5" r="4.4"/></g><pattern id="paws" width="420" height="420" patternUnits="userSpaceOnUse"><g class="ink"><use href="#bone" transform="translate(52.6,7.6) rotate(297.6) scale(0.93)"/><use href="#bone" transform="translate(52.6,427.6) rotate(297.6) scale(0.93)"/><use href="#paw" transform="translate(110.6,50.0) rotate(-8.9) scale(1.01)"/><use href="#paw" transform="translate(138.7,29.7) rotate(6.8) scale(0.90)"/><use href="#bone" transform="translate(208.1,13.8) rotate(56.8) scale(1.04)"/><use href="#bone" transform="translate(208.1,433.8) rotate(56.8) scale(1.04)"/><use href="#paw" transform="translate(293.8,12.4) rotate(15.8) scale(0.94)"/><use href="#paw" transform="translate(293.8,432.4) rotate(15.8) scale(0.94)"/><use href="#paw" transform="translate(348.3,26.4) rotate(15.6) scale(0.91)"/><use href="#paw" transform="translate(384.6,38.6) rotate(20.9) scale(1.05)"/><use href="#paw" transform="translate(49.5,71.2) rotate(-13.4) scale(1.05)"/><use href="#paw" transform="translate(77.6,113.5) rotate(-17.5) scale(1.01)"/><use href="#bone" transform="translate(158.3,73.3) rotate(188.1) scale(0.95)"/><use href="#bone" transform="translate(232.9,99.1) rotate(289.8) scale(0.91)"/><use href="#bone" transform="translate(292.2,96.5) rotate(356.6) scale(0.95)"/><use href="#bone" transform="translate(327.6,110.5) rotate(106.4) scale(0.91)"/><use href="#paw" transform="translate(378.9,81.0) rotate(14.6) scale(1.06)"/><use href="#bone" transform="translate(22.5,174.4) rotate(59.3) scale(1.05)"/><use href="#bone" transform="translate(81.8,159.8) rotate(99.1) scale(0.91)"/><use href="#bone" transform="translate(170.0,174.3) rotate(278.6) scale(1.06)"/><use href="#paw" transform="translate(228.4,166.8) rotate(13.0) scale(0.94)"/><use href="#paw" transform="translate(265.3,138.1) rotate(20.6) scale(0.95)"/><use href="#bone" transform="translate(326.1,174.3) rotate(216.6) scale(0.92)"/><use href="#paw" transform="translate(389.2,130.7) rotate(18.6) scale(1.02)"/><use href="#bone" transform="translate(51.8,223.9) rotate(209.7) scale(1.06)"/><use href="#paw" transform="translate(91.1,204.3) rotate(-6.7) scale(0.91)"/><use href="#paw" transform="translate(137.9,191.1) rotate(23.7) scale(0.92)"/><use href="#paw" transform="translate(206.9,211.5) rotate(3.0) scale(0.91)"/><use href="#bone" transform="translate(245.7,216.5) rotate(226.9) scale(0.95)"/><use href="#paw" transform="translate(315.1,214.2) rotate(-22.0) scale(0.96)"/><use href="#bone" transform="translate(373.6,221.6) rotate(299.7) scale(1.02)"/><use href="#paw" transform="translate(31.4,263.5) rotate(-1.9) scale(0.99)"/><use href="#bone" transform="translate(75.0,290.2) rotate(247.4) scale(0.93)"/><use href="#bone" transform="translate(166.5,257.3) rotate(127.0) scale(1.07)"/><use href="#paw" transform="translate(206.5,271.3) rotate(-20.4) scale(1.04)"/><use href="#bone" transform="translate(289.4,288.6) rotate(194.3) scale(0.91)"/><use href="#paw" transform="translate(341.2,272.4) rotate(22.9) scale(1.09)"/><use href="#paw" transform="translate(402.8,294.4) rotate(7.8) scale(1.02)"/><use href="#paw" transform="translate(-17.2,294.4) rotate(7.8) scale(1.02)"/><use href="#bone" transform="translate(15.5,334.3) rotate(266.9) scale(1.04)"/><use href="#bone" transform="translate(435.5,334.3) rotate(266.9) scale(1.04)"/><use href="#bone" transform="translate(94.4,352.5) rotate(220.6) scale(0.99)"/><use href="#paw" transform="translate(133.3,314.1) rotate(20.4) scale(0.90)"/><use href="#paw" transform="translate(227.4,328.8) rotate(-21.6) scale(1.09)"/><use href="#bone" transform="translate(276.7,328.5) rotate(73.2) scale(0.95)"/><use href="#bone" transform="translate(333.1,323.3) rotate(141.0) scale(0.91)"/><use href="#bone" transform="translate(385.7,331.7) rotate(74.2) scale(0.92)"/><use href="#paw" transform="translate(17.5,391.1) rotate(14.1) scale(1.05)"/><use href="#paw" transform="translate(437.5,391.1) rotate(14.1) scale(1.05)"/><use href="#paw" transform="translate(89.3,415.1) rotate(9.9) scale(1.01)"/><use href="#paw" transform="translate(89.3,-4.9) rotate(9.9) scale(1.01)"/><use href="#bone" transform="translate(160.1,414.5) rotate(92.7) scale(0.96)"/><use href="#bone" transform="translate(160.1,-5.5) rotate(92.7) scale(0.96)"/><use href="#bone" transform="translate(214.8,375.0) rotate(106.9) scale(0.98)"/><use href="#paw" transform="translate(245.1,415.0) rotate(-24.3) scale(1.07)"/><use href="#paw" transform="translate(245.1,-5.0) rotate(-24.3) scale(1.07)"/><use href="#bone" transform="translate(334.5,402.0) rotate(353.8) scale(1.10)"/><use href="#bone" transform="translate(334.5,-18.0) rotate(353.8) scale(1.10)"/><use href="#bone" transform="translate(385.0,409.4) rotate(241.2) scale(0.93)"/><use href="#bone" transform="translate(385.0,-10.6) rotate(241.2) scale(0.93)"/></g></pattern></defs><rect width="100%" height="100%" fill="url(#paws)"/></svg>
<main class="shell">
<header class="masthead">
  <div><h1><b>Pawchive</b> Downloader</h1><p class="sub">Bulk downloader for Pawchive creators and posts.</p></div>
  <div class="tools">
    <button id="theme" class="mini" type="button">Dark</button>
    <div class="state" id="statusPill" role="status">Idle</div>
  </div>
</header>

<div class="cols">
<section class="panel">
  <h2>New download</h2>
  <form id="form">
    <label class="field" for="urls"><span>URLs</span><textarea id="urls" placeholder="One creator or post URL per line"></textarea></label>
    <label class="field" for="output"><span>Save to</span><input id="output" type="text" value="__DEFAULT_OUTPUT__"></label>
    <div class="pair">
      <label class="field" for="limit"><span>Max posts</span><input id="limit" type="number" min="1" placeholder="All"></label>
      <label class="field" for="concurrency"><span>Parallel</span><input id="concurrency" type="number" min="1" max="20" value="6"></label>
    </div>
    <div class="opts">
      <label class="opt"><input id="cover" type="checkbox" checked> Covers</label>
      <label class="opt"><input id="attachments" type="checkbox" checked> Attachments</label>
      <label class="opt"><input id="metadata" type="checkbox"> Post metadata (post.json)</label>
      <label class="opt"><input id="overwrite" type="checkbox"> Overwrite existing files</label>
      <label class="opt"><input id="postFolders" type="checkbox"> A folder per post</label>
    </div>
    <div class="actions">
      <button id="start" class="go" type="submit">Start download</button>
      <button id="stop" class="halt" type="button" disabled>Stop</button>
      <button id="open" type="button">Open folder</button>
    </div>
    <p class="note" id="error" role="alert"></p>
  </form>
</section>

<section class="panel">
  <img class="peek" id="peek" src="mascot.png" alt="">
  <h2>Activity</h2>
  <div class="figures">
    <div class="figure"><b id="done">0</b><span>done</span></div>
    <div class="figure"><b id="failed">0</b><span>failed</span></div>
    <div class="figure"><b id="skipped">0</b><span>skipped</span></div>
    <div class="figure"><b id="queued">0</b><span>queued</span></div>
  </div>
  <div class="meter" id="progress" role="progressbar" aria-label="Download progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><i id="bar"></i></div>
  <div class="count" id="progressText">0 / 0</div>
  <div class="log" id="log" tabindex="0" role="log" aria-live="off" aria-label="Download log"><div class="line">No download running.</div></div>
</section>
</div>

<footer class="colophon">
  <span>Everything runs on this PC. Only Pawchive is contacted.</span>
  <button id="close" type="button">Quit</button>
</footer>
</main>
<script>
const $=id=>document.getElementById(id);let lastLog='No download running.';let failures=0;let closed=false;
async function api(path,options={}){const r=await fetch('api/'+path,{headers:{'Content-Type':'application/json'},...options});const j=await r.json();if(!r.ok)throw new Error(j.error||'Request failed');return j}
function setError(t){$('error').textContent=t||''}
const NL=String.fromCharCode(10);
function paintLog(text){const el=$('log');const stick=el.scrollHeight-el.scrollTop-el.clientHeight<40;
const frag=document.createDocumentFragment();
for(const line of text.split(NL)){if(!line)continue;const d=document.createElement('div');
d.className='line'+(line.startsWith('FAILED')?' bad':line.startsWith('SKIPPED')?' meh':'');
d.textContent=line;frag.appendChild(d)}
el.textContent='';el.appendChild(frag);if(stick)el.scrollTop=el.scrollHeight}
function render(s){
$('done').textContent=s.done;$('failed').textContent=s.failed;$('skipped').textContent=s.skipped;$('queued').textContent=s.queued;
$('failed').classList.toggle('hot',s.failed>0);
const finished=s.done+s.failed+s.skipped;const pct=s.total?Math.round(finished/s.total*100):0;
$('bar').style.width=pct+'%';$('progressText').textContent=finished+' / '+s.total+' files';
const p=$('progress');p.setAttribute('aria-valuenow',pct);p.setAttribute('aria-valuetext',finished+' of '+s.total+' files, '+pct+'%');
$('start').disabled=s.running;$('stop').disabled=!s.running||s.stopping;
$('statusPill').textContent=s.stopping?'Stopping':s.running?(s.total?'Downloading':'Reading posts'):s.stopped?'Stopped':s.finished?'Done':'Idle';
$('statusPill').className='state '+(s.running?'running':s.finished&&!s.stopped?'done':'');
const text=s.logs.length?s.logs.join(''):'No download running.';
if(text!==lastLog){paintLog(text);lastLog=text}
setError(s.error);return s.running}
function disconnected(){$('statusPill').textContent='Disconnected';$('statusPill').className='state';$('start').disabled=true;$('stop').disabled=true;
setError('Lost contact with Pawchive Downloader. The app has closed. Restart it to download again.')}
async function poll(){if(closed)return;let running=false;
try{const s=await api('status');failures=0;try{running=render(s)}catch(e){console.error(e)}}
catch(e){if(++failures>=3)disconnected()}
setTimeout(poll,failures?5000:(running?600:2000))}
async function startDownload(){try{setError('');await api('start',{method:'POST',body:JSON.stringify({urls:$('urls').value,output:$('output').value,limit:$('limit').value,concurrency:$('concurrency').value,cover:$('cover').checked,attachments:$('attachments').checked,metadata:$('metadata').checked,overwrite:$('overwrite').checked,postFolders:$('postFolders').checked})})}catch(e){setError(e.message)}}
$('form').addEventListener('submit',e=>{e.preventDefault();startDownload()});
$('form').addEventListener('keydown',e=>{if(e.key!=='Enter')return;const t=e.target.tagName;if(t==='BUTTON')return;if(t==='TEXTAREA'&&!(e.ctrlKey||e.metaKey))return;e.preventDefault();startDownload()});
$('stop').onclick=async()=>{try{await api('stop',{method:'POST',body:'{}'})}catch(e){setError(e.message)}};
$('open').onclick=async()=>{try{await api('open',{method:'POST',body:JSON.stringify({output:$('output').value})})}catch(e){setError(e.message)}};
$('close').onclick=async()=>{if(!confirm('Quit Pawchive Downloader? This dashboard will stop working.'))return;
try{await api('close',{method:'POST',body:'{}'});closed=true;document.body.innerHTML='<main class="shell"><section class="panel"><h2>Pawchive Downloader has quit.</h2><p class="sub">You can close this tab.</p></section></main>'}catch(e){setError(e.message)}};
const peek=$('peek');if(peek)peek.addEventListener('error',()=>peek.remove());
const themeBtn=$('theme');
function paintTheme(){const dark=document.documentElement.dataset.theme==='dark';
themeBtn.textContent=dark?'Light':'Dark';
themeBtn.setAttribute('aria-label',dark?'Switch to the light theme':'Switch to the dark theme')}
themeBtn.onclick=()=>{const next=document.documentElement.dataset.theme==='dark'?'light':'dark';
document.documentElement.dataset.theme=next;
try{localStorage.setItem('pawchive-theme',next)}catch(e){}
paintTheme()};
paintTheme();
poll();
</script></body></html>"""


class DashboardState:
    def __init__(self, output: Path) -> None:
        self.lock = threading.Lock()
        self.default_output = output
        self.output = output
        self.running = self.finished = self.stopping = self.stopped = False
        self.total = self.done = self.failed = self.skipped = 0
        self.logs: deque[str] = deque(maxlen=250)
        self.error = ""
        self.last_seen = time.monotonic()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.task: asyncio.Task[DownloadSummary] | None = None

    def begin(self, output: Path) -> bool:
        """Claim the single download slot. False when one is already running."""
        with self.lock:
            if self.running:
                return False
            self.output, self.running, self.finished = output, True, False
            self.stopping = self.stopped = False
            self.total = self.done = self.failed = self.skipped = 0
            self.logs.clear(); self.error = ""
            return True

    def bind_task(self, loop: asyncio.AbstractEventLoop, task: asyncio.Task[DownloadSummary]) -> None:
        with self.lock:
            self.loop, self.task = loop, task

    def clear_task(self) -> None:
        with self.lock:
            self.loop = self.task = None

    def request_stop(self) -> bool:
        with self.lock:
            if not self.running:
                return False
            self.stopping = True
            loop, task = self.loop, self.task
        if loop and task:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass
        return True

    def progress(self, event: str, value: object) -> None:
        with self.lock:
            if event == "total": self.total = int(value)
            elif event == "downloaded": self.done += 1
            elif event == "failed": self.failed += 1
            elif event == "skipped": self.skipped += 1

    def log(self, value: str) -> None:
        if value:
            with self.lock:
                # A deque drops the oldest line on its own; re-slicing a list
                # rebuilt the whole buffer on every single log write.
                self.logs.append(value)

    def finish(self, summary: DownloadSummary | None = None, error: str = "", stopped: bool = False) -> None:
        with self.lock:
            if summary:
                self.total, self.done, self.failed, self.skipped = summary.planned, summary.downloaded, summary.failed, summary.skipped
            self.running, self.finished, self.error = False, True, error
            self.stopping, self.stopped = False, stopped

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            self.last_seen = time.monotonic()
            return {"running":self.running,"finished":self.finished,"stopping":self.stopping,"stopped":self.stopped,"total":self.total,"done":self.done,"failed":self.failed,"skipped":self.skipped,"queued":max(self.total-self.done-self.failed-self.skipped,0),"logs":list(self.logs),"error":self.error}


class StateWriter:
    def __init__(self, state: DashboardState) -> None: self.state = state
    def write(self, value: str) -> int: self.state.log(value); return len(value)
    def flush(self) -> None: pass


class PawchiveServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address: tuple[str, int], state: DashboardState, token: str) -> None:
        self.state, self.token = state, token
        super().__init__(address, PawchiveHandler)


class PawchiveHandler(BaseHTTPRequestHandler):
    server: PawchiveServer
    def log_message(self, *_: object) -> None: return

    def do_GET(self) -> None:
        if self.path == f"/{self.server.token}/" or self.path.startswith(f"/{self.server.token}/?"):
            page = PAGE.replace("__DEFAULT_OUTPUT__", _html_escape(str(self.server.state.default_output)))
            self._send(page.encode(), "text/html; charset=utf-8"); return
        if self.path == f"/{self.server.token}/api/status": self._json(HTTPStatus.OK, self.server.state.snapshot()); return
        if self.path == f"/{self.server.token}/mascot.png":
            art = _mascot()
            if art: self._send(art, "image/png", cache="public, max-age=604800, immutable"); return
            self._json(HTTPStatus.NOT_FOUND, {"error":"Not found"}); return
        self._json(HTTPStatus.NOT_FOUND, {"error":"Not found"})

    def do_POST(self) -> None:
        prefix = f"/{self.server.token}/api/"
        if not self.path.startswith(prefix): self._json(HTTPStatus.NOT_FOUND,{"error":"Not found"}); return
        try:
            length = min(int(self.headers.get("Content-Length","0")),1_000_000)
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body,dict): raise ValueError("Invalid request")
            action = self.path[len(prefix):]
            if action == "start": self._start(body)
            elif action == "stop": self._stop()
            elif action == "open": self._open(body)
            elif action == "close": self._close()
            else: self._json(HTTPStatus.NOT_FOUND,{"error":"Not found"})
        except (ValueError,OSError) as exc: self._json(HTTPStatus.BAD_REQUEST,{"error":str(exc)})

    def _start(self, body: dict[str, Any]) -> None:
        state = self.server.state
        with state.lock:
            if state.running: self._json(HTTPStatus.CONFLICT,{"error":"A download is already running"}); return
        raw_urls = [line.strip() for line in str(body.get("urls","")).splitlines() if line.strip()]
        if not raw_urls: raise ValueError("Enter at least one Pawchive URL")
        targets = list(dict.fromkeys(parse_target(value) for value in raw_urls))
        if not body.get("cover",True) and not body.get("attachments",True): raise ValueError("Enable covers or attachments")
        output = Path(str(body.get("output") or state.default_output)).expanduser().resolve()
        concurrency = _positive_int(body.get("concurrency"), 6, "Concurrent downloads")
        if concurrency is None or not 1 <= concurrency <= 20: raise ValueError("Concurrent downloads must be between 1 and 20")
        limit = _positive_int(body.get("limit"), None, "Post limit")
        if limit is not None and limit < 1: raise ValueError("Post limit must be at least 1")
        options = RunOptions(download=DownloadOptions(output=output,concurrency=concurrency,overwrite=bool(body.get("overwrite")),include_cover=bool(body.get("cover",True)),include_attachments=bool(body.get("attachments",True)),metadata=bool(body.get("metadata")),post_folders=bool(body.get("postFolders"))),history_file=output/HISTORY_FILENAME,session_cookie=os.environ.get("PAWCHIVE_SESSION"),max_posts=limit)
        # Claiming the slot and starting the worker must be one step; two
        # requests arriving together could otherwise both pass the check above.
        if not state.begin(output): self._json(HTTPStatus.CONFLICT,{"error":"A download is already running"}); return
        threading.Thread(target=_download_worker,args=(targets,options,state),daemon=True).start()
        self._json(HTTPStatus.ACCEPTED,{"ok":True})

    def _stop(self) -> None:
        if not self.server.state.request_stop():
            self._json(HTTPStatus.CONFLICT,{"error":"No download is running"}); return
        self._json(HTTPStatus.ACCEPTED,{"ok":True})

    def _open(self, body: dict[str, Any]) -> None:
        output = Path(str(body.get("output") or self.server.state.output)).expanduser().resolve(); output.mkdir(parents=True,exist_ok=True)
        os.startfile(output)  # type: ignore[attr-defined]
        self._json(HTTPStatus.OK,{"ok":True})

    def _close(self) -> None:
        with self.server.state.lock:
            if self.server.state.running: self._json(HTTPStatus.CONFLICT,{"error":"The application cannot close while downloading"}); return
        self._json(HTTPStatus.OK,{"ok":True}); threading.Thread(target=self.server.shutdown,daemon=True).start()

    def _json(self, status: HTTPStatus, value: dict[str, Any]) -> None: self._send(json.dumps(value,ensure_ascii=False).encode(),"application/json; charset=utf-8",status)
    def _send(self, data: bytes, content_type: str, status: HTTPStatus=HTTPStatus.OK, cache: str="no-store") -> None:
        self.send_response(status); self.send_header("Content-Type",content_type); self.send_header("Content-Length",str(len(data))); self.send_header("Cache-Control",cache); self.send_header("X-Content-Type-Options","nosniff"); self.send_header("Content-Security-Policy","default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'"); self.end_headers(); self.wfile.write(data)


def _download_worker(targets: list[Any], options: RunOptions, state: DashboardState) -> None:
    console = Console(file=StateWriter(state),color_system=None,force_terminal=False,width=120)
    async def execute() -> DownloadSummary:
        task = asyncio.current_task()
        assert task is not None
        state.bind_task(asyncio.get_running_loop(),task)
        try: return await run(targets,options,console,state.progress)
        finally: state.clear_task()
    try: summary = asyncio.run(execute())
    except asyncio.CancelledError: state.log("Download stopped by user. Partial files were kept for resume.\n"); state.finish(stopped=True)
    except Exception as exc: state.log(f"ERROR: {exc}\n"); state.finish(error=str(exc))
    else: state.finish(summary)


def _positive_int(value: object, default: int | None, label: str) -> int | None:
    """Read a number from the form, reporting the field name when it is junk."""
    text = str(value if value is not None else "").strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"{label} must be a number") from None


_MASCOT: bytes | None = None


def _mascot() -> bytes:
    """The peeking artwork, read once. Empty when the asset is missing, so
    a build without it simply shows no mascot instead of failing."""
    global _MASCOT
    if _MASCOT is None:
        try:
            _MASCOT = (resources.files("pawchive_downloader") / "assets" / "mascot.png").read_bytes()
        except (OSError, ModuleNotFoundError):
            _MASCOT = b""
    return _MASCOT


def _html_escape(value: str) -> str: return value.replace("&","&amp;").replace('"',"&quot;").replace("<","&lt;").replace(">","&gt;")


def _watchdog(server: PawchiveServer) -> None:
    while True:
        time.sleep(5)
        with server.state.lock: stale, running = time.monotonic()-server.state.last_seen>45, server.state.running
        if stale and not running: server.shutdown(); return


def main() -> None:
    base = Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path.cwd()
    state = DashboardState(base/"downloads"); token = secrets.token_urlsafe(24); server = PawchiveServer(("127.0.0.1",0),state,token)
    url = f"http://127.0.0.1:{server.server_port}/{token}/"
    threading.Thread(target=_watchdog,args=(server,),daemon=True).start(); threading.Timer(.5,lambda:webbrowser.open_new_tab(url)).start()
    try: server.serve_forever(poll_interval=.5)
    finally: server.server_close()


if __name__ == "__main__": main()
