from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from rich.console import Console

from .app import RunOptions, run
from .downloader import DownloadOptions, DownloadSummary
from .urls import parse_target


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pawchy Downloader</title>
<style>
:root{color-scheme:dark;--bg:#0a0c12;--panel:#121620;--line:#262d3c;--text:#f5f7fb;--muted:#8c96aa;--green:#45d483;--red:#ff667a;--yellow:#ffc857;--purple:#9b7bff;--blue:#56a8ff}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0,#19213a 0,transparent 32%),var(--bg);font:15px/1.45 Inter,Segoe UI,Arial,sans-serif;color:var(--text);min-height:100vh}.shell{max-width:1080px;margin:auto;padding:34px 24px 60px}.top{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-bottom:24px}.brand{display:flex;align-items:center;gap:14px}.logo{width:50px;height:50px;border-radius:15px;background:linear-gradient(145deg,#a67cff,#5b8cff);display:grid;place-items:center;font-size:26px;box-shadow:0 12px 34px #765bff4d}.brand h1{font-size:25px;margin:0}.brand p{margin:3px 0 0;color:var(--muted)}.pill{padding:8px 13px;border:1px solid var(--line);border-radius:99px;color:var(--muted);background:#0e121a}.pill.running{color:var(--blue);border-color:#56a8ff55}.pill.done{color:var(--green);border-color:#45d48355}.grid{display:grid;grid-template-columns:1.2fr .8fr;gap:18px}.panel{background:linear-gradient(160deg,#151a25,#10141d);border:1px solid var(--line);border-radius:18px;padding:20px;box-shadow:0 18px 50px #0005}.panel h2{font-size:16px;margin:0 0 14px}.label{display:block;color:var(--muted);font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;margin:14px 0 7px}textarea,input{width:100%;border:1px solid var(--line);border-radius:11px;background:#090c12;color:var(--text);padding:12px;outline:none}textarea{min-height:144px;resize:vertical;font:13px/1.5 Consolas,monospace}textarea:focus,input:focus{border-color:#816cff}.row{display:grid;grid-template-columns:1fr 130px;gap:12px}.checks{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:15px}.check{display:flex;gap:9px;align-items:center;color:#cbd2df}.check input{width:auto;accent-color:#8a72ff}.buttons{display:flex;gap:10px;margin-top:18px}button{border:0;border-radius:11px;padding:11px 16px;font-weight:750;cursor:pointer;color:white;background:#242b3a}button.primary{flex:1;background:linear-gradient(135deg,#8c6dff,#596eff);box-shadow:0 9px 24px #725eff48}button.stop{background:#5b2630;color:#ff9cab}button:disabled{opacity:.45;cursor:not-allowed}.stats{display:grid;grid-template-columns:1fr 1fr;gap:10px}.stat{border:1px solid var(--line);background:#0b0e15;border-radius:14px;padding:15px}.stat span{display:block;color:var(--muted);font-size:12px}.stat b{display:block;font-size:27px;margin-top:2px}.stat.done b{color:var(--green)}.stat.fail b{color:var(--red)}.stat.skip b{color:var(--yellow)}.stat.queue b{color:var(--purple)}.progress{height:9px;background:#090c12;border-radius:99px;overflow:hidden;margin:18px 0 7px;border:1px solid var(--line)}.bar{height:100%;width:0;background:linear-gradient(90deg,#725eff,#45d483);transition:width .35s}.progress-text{color:var(--muted);font-size:12px;text-align:right}.log{height:230px;overflow:auto;white-space:pre-wrap;background:#080a0f;border:1px solid var(--line);border-radius:12px;padding:12px;color:#aeb7c9;font:12px/1.5 Consolas,monospace;margin-top:14px}.error{color:var(--red);min-height:21px;margin-top:9px}.foot{display:flex;justify-content:space-between;align-items:center;color:var(--muted);font-size:12px;margin-top:18px}@media(max-width:820px){.grid{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}.checks{grid-template-columns:1fr}.row{grid-template-columns:1fr}}
</style></head><body><main class="shell">
<header class="top"><div class="brand"><div class="logo">🐾</div><div><h1>Pawchy Downloader</h1><p>Download Pawchive profiles quickly and neatly.</p></div></div><div id="statusPill" class="pill">Ready</div></header>
<section class="grid"><div class="panel"><h2>New download</h2><label class="label" for="urls">Pawchive URLs</label><textarea id="urls" placeholder="Enter one creator or post URL per line…"></textarea><label class="label" for="output">Download folder</label><input id="output" value="__DEFAULT_OUTPUT__"><div class="row"><div><label class="label" for="limit">Post limit</label><input id="limit" type="number" min="1" placeholder="All"></div><div><label class="label" for="concurrency">Concurrent</label><input id="concurrency" type="number" min="1" max="20" value="6"></div></div><div class="checks"><label class="check"><input id="cover" type="checkbox" checked> Thumbnail / cover</label><label class="check"><input id="attachments" type="checkbox" checked> All attachments</label><label class="check"><input id="metadata" type="checkbox"> Save post.json</label><label class="check"><input id="overwrite" type="checkbox"> Overwrite existing files</label></div><div id="error" class="error"></div><div class="buttons"><button id="start" class="primary">Start download</button><button id="stop" class="stop" disabled>Stop download</button><button id="open">Open folder</button></div></div>
<div class="panel"><h2>Live status</h2><div class="stats"><div class="stat done"><span>COMPLETED</span><b id="done">0</b></div><div class="stat fail"><span>FAILED</span><b id="failed">0</b></div><div class="stat skip"><span>SKIPPED</span><b id="skipped">0</b></div><div class="stat queue"><span>QUEUED</span><b id="queued">0</b></div></div><div class="progress"><div id="bar" class="bar"></div></div><div id="progressText" class="progress-text">0 / 0</div><div id="log" class="log">Waiting for a download…</div></div></section><div class="foot"><span>Files are stored in one folder per creator.</span><button id="close">Close application</button></div></main>
<script>
const $=id=>document.getElementById(id);let lastLog='';async function api(path,options={}){const r=await fetch('api/'+path,{headers:{'Content-Type':'application/json'},...options});const j=await r.json();if(!r.ok)throw new Error(j.error||'Request failed');return j}function render(s){$('done').textContent=s.done;$('failed').textContent=s.failed;$('skipped').textContent=s.skipped;$('queued').textContent=s.queued;const finished=s.done+s.failed+s.skipped;const pct=s.total?Math.round(finished/s.total*100):0;$('bar').style.width=pct+'%';$('progressText').textContent=finished+' / '+s.total+'  ·  '+pct+'%';$('start').disabled=s.running;$('stop').disabled=!s.running||s.stopping;$('statusPill').textContent=s.stopping?'Stopping…':s.running?(s.total?'Downloading':'Scanning posts'):s.stopped?'Stopped':s.finished?'Completed':'Ready';$('statusPill').className='pill '+(s.running?'running':s.finished&&!s.stopped?'done':'');const text=s.logs.length?s.logs.join(''):'Waiting for a download…';if(text!==lastLog){$('log').textContent=text;$('log').scrollTop=$('log').scrollHeight;lastLog=text}if(s.error)$('error').textContent=s.error}async function poll(){try{render(await api('status'))}catch(e){}setTimeout(poll,600)}$('start').onclick=async()=>{try{$('error').textContent='';await api('start',{method:'POST',body:JSON.stringify({urls:$('urls').value,output:$('output').value,limit:$('limit').value,concurrency:$('concurrency').value,cover:$('cover').checked,attachments:$('attachments').checked,metadata:$('metadata').checked,overwrite:$('overwrite').checked})})}catch(e){$('error').textContent=e.message}};$('stop').onclick=async()=>{try{await api('stop',{method:'POST',body:'{}'})}catch(e){$('error').textContent=e.message}};$('open').onclick=async()=>{try{await api('open',{method:'POST',body:JSON.stringify({output:$('output').value})})}catch(e){$('error').textContent=e.message}};$('close').onclick=async()=>{try{await api('close',{method:'POST',body:'{}'});document.body.innerHTML='<main class="shell"><div class="panel"><h2>Pawchy Downloader has closed.</h2><p>You can close this tab.</p></div></main>'}catch(e){$('error').textContent=e.message}};poll();
</script></body></html>"""


class DashboardState:
    def __init__(self, output: Path) -> None:
        self.lock = threading.Lock()
        self.default_output = output
        self.output = output
        self.running = self.finished = self.stopping = self.stopped = False
        self.total = self.done = self.failed = self.skipped = 0
        self.logs: list[str] = []
        self.error = ""
        self.last_seen = time.monotonic()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.task: asyncio.Task[DownloadSummary] | None = None

    def begin(self, output: Path) -> None:
        with self.lock:
            self.output, self.running, self.finished = output, True, False
            self.stopping = self.stopped = False
            self.total = self.done = self.failed = self.skipped = 0
            self.logs, self.error = [], ""

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
                self.logs.append(value)
                self.logs = self.logs[-250:]

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


class PawchyServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address: tuple[str, int], state: DashboardState, token: str) -> None:
        self.state, self.token = state, token
        super().__init__(address, PawchyHandler)


class PawchyHandler(BaseHTTPRequestHandler):
    server: PawchyServer
    def log_message(self, *_: object) -> None: return

    def do_GET(self) -> None:
        if self.path == f"/{self.server.token}/" or self.path.startswith(f"/{self.server.token}/?"):
            page = PAGE.replace("__DEFAULT_OUTPUT__", _html_escape(str(self.server.state.default_output)))
            self._send(page.encode(), "text/html; charset=utf-8"); return
        if self.path == f"/{self.server.token}/api/status": self._json(HTTPStatus.OK, self.server.state.snapshot()); return
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
        concurrency = int(body.get("concurrency") or 6)
        if not 1 <= concurrency <= 20: raise ValueError("Concurrent downloads must be between 1 and 20")
        limit_text = str(body.get("limit") or "").strip(); limit = int(limit_text) if limit_text else None
        if limit is not None and limit < 1: raise ValueError("Post limit must be at least 1")
        options = RunOptions(download=DownloadOptions(output=output,concurrency=concurrency,overwrite=bool(body.get("overwrite")),include_cover=bool(body.get("cover",True)),include_attachments=bool(body.get("attachments",True)),metadata=bool(body.get("metadata"))),history_file=output/".pawchy-history.sqlite3",session_cookie=os.environ.get("PAWCHIVE_SESSION"),max_posts=limit)
        state.begin(output)
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
    def _send(self, data: bytes, content_type: str, status: HTTPStatus=HTTPStatus.OK) -> None:
        self.send_response(status); self.send_header("Content-Type",content_type); self.send_header("Content-Length",str(len(data))); self.send_header("Cache-Control","no-store"); self.send_header("X-Content-Type-Options","nosniff"); self.send_header("Content-Security-Policy","default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'"); self.end_headers(); self.wfile.write(data)


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


def _html_escape(value: str) -> str: return value.replace("&","&amp;").replace('"',"&quot;").replace("<","&lt;").replace(">","&gt;")


def _watchdog(server: PawchyServer) -> None:
    while True:
        time.sleep(5)
        with server.state.lock: stale, running = time.monotonic()-server.state.last_seen>45, server.state.running
        if stale and not running: server.shutdown(); return


def main() -> None:
    base = Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path.cwd()
    state = DashboardState(base/"downloads"); token = secrets.token_urlsafe(24); server = PawchyServer(("127.0.0.1",0),state,token)
    url = f"http://127.0.0.1:{server.server_port}/{token}/"
    threading.Thread(target=_watchdog,args=(server,),daemon=True).start(); threading.Timer(.5,lambda:webbrowser.open_new_tab(url)).start()
    try: server.serve_forever(poll_interval=.5)
    finally: server.server_close()


if __name__ == "__main__": main()
