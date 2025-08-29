import subprocess
import threading
import time
import json
import queue
from pathlib import Path
from typing import Dict, Any

from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import uvicorn

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

SCRIPTS_DB = Path("scripts.json")

# -------------------- Persistence --------------------

def load_scripts() -> Dict[str, Any]:
    if not SCRIPTS_DB.exists():
        return {}
    try:
        return json.loads(SCRIPTS_DB.read_text())
    except Exception:
        return {}


def save_scripts(data: Dict[str, Any]):
    SCRIPTS_DB.write_text(json.dumps(data, indent=2))


# -------------------- Runtime State --------------------
# processes[name] = {
#   process, thread, status, start_time, output (str), returncode,
#   policy, should_stop (bool), subscribers (set of Queue[str])
# }
processes: Dict[str, Dict[str, Any]] = {}
lock = threading.Lock()


def _broadcast_line(name: str, line: str):
    with lock:
        subs = processes.get(name, {}).get("subscribers", set()).copy()
    for q in subs:
        try:
            q.put_nowait(line)
        except queue.Full:
            # drop if subscriber is slow
            pass


def monitor_script(name: str, cmd: list, policy: str):
    """Run and monitor a script, restart based on policy, and stream output."""
    while True:
        with lock:
            should_stop = processes[name].get("should_stop", False)
        if should_stop:
            with lock:
                processes[name]["status"] = "stopped"
            break

        start_time = time.time()
        # Merge stdout/stderr; decode as text
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        with lock:
            processes[name]["process"] = proc
            processes[name]["status"] = "running"
            processes[name]["start_time"] = start_time
            processes[name].setdefault("output", "")

        # Read live output line-by-line
        assert proc.stdout is not None
        for line in proc.stdout:
            with lock:
                processes[name]["output"] = (processes[name]["output"] + line)[-20000:]  # keep last 20k chars
            _broadcast_line(name, line)

        proc.wait()
        code = proc.returncode
        with lock:
            processes[name]["returncode"] = code

        with lock:
            should_stop = processes[name].get("should_stop", False)

        if should_stop:
            with lock:
                processes[name]["status"] = "stopped"
            break

        if code != 0:
            with lock:
                processes[name]["status"] = "error"
            if policy in ("on-failure", "always"):
                time.sleep(2)
                continue  # restart
        else:
            with lock:
                processes[name]["status"] = "stopped"
        if policy == "always":
            time.sleep(2)
            continue
        break


# -------------------- Pages & API --------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    scripts = load_scripts()
    # initialize runtime entries for known scripts
    with lock:
        for name, meta in scripts.items():
            processes.setdefault(name, {"status": "stopped", "policy": meta.get("policy", "on-failure"), "subscribers": set(), "should_stop": False})
    statuses = {}
    with lock:
        for name in scripts:
            statuses[name] = processes.get(name, {}).get("status", "stopped")
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "scripts": scripts, "statuses": statuses},
    )


@app.get("/script/{name}", response_class=HTMLResponse)
async def script_detail(request: Request, name: str):
    scripts = load_scripts()
    if name not in scripts:
        return HTMLResponse("Script not found", status_code=404)
    with lock:
        pinfo = processes.get(name, {})
        runtime = {
            "status": pinfo.get("status", "stopped"),
            "start_time": pinfo.get("start_time"),
            "running_time": time.time() - pinfo["start_time"] if pinfo.get("start_time") else None,
            "returncode": pinfo.get("returncode"),
            "output": pinfo.get("output", "")[-2000:],
        }
    return templates.TemplateResponse(
        "detail.html",
        {"request": request, "name": name, "script": scripts[name], "runtime": runtime},
    )


@app.get("/start/{name}")
async def start_script(name: str):
    scripts = load_scripts()
    if name not in scripts:
        return HTMLResponse("Script not found", status_code=404)
    with lock:
        if processes.get(name, {}).get("status") == "running":
            return RedirectResponse("/script/" + name, status_code=303)
        # reset stop flag, output buffer
        processes.setdefault(name, {}).update({
            "should_stop": False,
            "output": "",
            "policy": scripts[name].get("policy", "on-failure"),
            "subscribers": processes.get(name, {}).get("subscribers", set())
        })
    path = scripts[name]["path"]
    args = scripts[name].get("args", [])
    policy = scripts[name].get("policy", "on-failure")
    t = threading.Thread(target=monitor_script, args=(name, ["python3", path] + args, policy), daemon=True)
    with lock:
        processes[name]["thread"] = t
    t.start()
    return RedirectResponse("/script/" + name, status_code=303)


@app.get("/stop/{name}")
async def stop_script(name: str):
    with lock:
        if name not in processes:
            return RedirectResponse("/", status_code=303)
        processes[name]["should_stop"] = True
        proc = processes[name].get("process")
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    with lock:
        processes[name]["status"] = "stopped"
    return RedirectResponse("/script/" + name, status_code=303)


@app.get("/add", response_class=HTMLResponse)
async def add_form(request: Request):
    return templates.TemplateResponse("add.html", {"request": request})


@app.post("/add")
async def add_script(path: str = Form(...), args: str = Form(""), policy: str = Form("on-failure")):
    scripts = load_scripts()
    name = Path(path).name
    scripts[name] = {"path": path, "args": args.split() if args else [], "policy": policy}
    save_scripts(scripts)
    return RedirectResponse("/", status_code=303)


# -------------------- WebSockets --------------------
@app.websocket("/ws/logs/{name}")
async def ws_logs(websocket: WebSocket, name: str):
    await websocket.accept()
    # Subscribe this client to live lines
    q: queue.Queue[str] = queue.Queue(maxsize=1000)
    with lock:
        processes.setdefault(name, {}).setdefault("subscribers", set()).add(q)
        # send recent tail for context
        tail = processes.get(name, {}).get("output", "")[-2000:]
    if tail:
        await websocket.send_text(tail)
    try:
        while True:
            # Block until a new line arrives from the producer thread
            line = await websocket.loop.run_in_executor(None, q.get)
            await websocket.send_text(line)
    except WebSocketDisconnect:
        pass
    finally:
        with lock:
            subs = processes.get(name, {}).get("subscribers", set())
            if q in subs:
                subs.remove(q)


@app.websocket("/ws/status")
async def ws_status(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            scripts = load_scripts()
            snapshot = {}
            with lock:
                for name in scripts:
                    snapshot[name] = processes.get(name, {}).get("status", "stopped")
            await websocket.send_json(snapshot)
            await websocket.receive_text()  # optional ping from client to keep alive
    except Exception:
        # Client disconnected or error; nothing to do
        pass


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)