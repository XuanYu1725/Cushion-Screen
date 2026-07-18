#!/usr/bin/env python3
"""
Cushion Screen Web UI
  python web_app.py
  浏览器打开 http://127.0.0.1:8765
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cushion_screen as cs

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
UPLOAD_DIR = ROOT / "web_uploads"
DAT_PATH = ROOT / "data" / "cs" / "command_storage.dat"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
WEB_DIR.mkdir(parents=True, exist_ok=True)

# 全局任务状态（单任务队列，避免多进程写同一 dat 互踩）
_lock = threading.Lock()
_job = {
    "id": None,
    "status": "idle",  # idle|running|done|error|cancelled
    "created": None,
    "started": None,
    "finished": None,
    "params": {},
    "progress": {
        "phase": "idle",
        "current": 0,
        "total": None,
        "percent": 0.0,
        "elapsed": 0.0,
        "eta_seconds": None,
        "message": "待命",
    },
    "result": None,
    "error": None,
}
_worker_thread = None


def _set_progress(p: dict):
    with _lock:
        prev = _job.get("progress") or {}
        merged = {**prev, **p}
        # 保底 percent
        if merged.get("percent") is None and merged.get("total"):
            cur = float(merged.get("current") or 0)
            tot = float(merged["total"])
            merged["percent"] = max(0.0, min(100.0, 100.0 * cur / tot)) if tot else 0.0
        _job["progress"] = merged


def _snapshot():
    with _lock:
        return json.loads(json.dumps(_job, default=str))


def _run_job(job_id: str, input_path: Path, params: dict):
    def on_progress(p):
        with _lock:
            if _job.get("id") != job_id:
                return
        _set_progress(p)

    try:
        cs.clear_cancel()
        with _lock:
            _job["status"] = "running"
            _job["started"] = time.time()
            _job["error"] = None
            _job["result"] = None
        _set_progress(
            {
                "phase": "start",
                "current": 0,
                "total": None,
                "percent": 0.0,
                "elapsed": 0.0,
                "eta_seconds": None,
                "message": "任务启动…",
            }
        )

        preview = None
        kind = cs.detect_media_kind(input_path)
        if kind == "image":
            preview = str(ROOT / f"{params['source_name']}_web_preview.png")
        else:
            # 默认不写海量预览图；需要可改 True
            preview = None

        result = cs.process_media(
            str(input_path),
            source_name=params["source_name"],
            target_height=int(params["target_height"]),
            target_fps=float(params["target_fps"]) if params.get("target_fps") is not None else None,
            dat_path=DAT_PATH,
            preview_path_or_dir=preview,
            data_version=int(params.get("data_version") or 5003),
            max_frames=params.get("max_frames"),
            dither=bool(params.get("dither", True)),
            dither_matrix_size=params.get("dither_matrix_size") or "auto",
            dither_strength=params.get("dither_strength"),
            progress_callback=on_progress,
        )

        with _lock:
            if _job.get("id") == job_id:
                _job["status"] = "done"
                _job["finished"] = time.time()
                _job["result"] = result if isinstance(result, dict) else {"ok": True}
        _set_progress(
            {
                "phase": "done",
                "percent": 100.0,
                "eta_seconds": 0.0,
                "message": "完成",
            }
        )
    except cs.ProcessingCancelled as e:
        print(f"[web] cancelled: {e}")
        with _lock:
            if _job.get("id") == job_id:
                _job["status"] = "cancelled"
                _job["finished"] = time.time()
                _job["error"] = None
                _job["result"] = {"cancelled": True, "message": str(e)}
        _set_progress(
            {
                "phase": "cancelled",
                "message": str(e),
                "eta_seconds": None,
            }
        )
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        with _lock:
            if _job.get("id") == job_id:
                _job["status"] = "error"
                _job["finished"] = time.time()
                _job["error"] = f"{type(e).__name__}: {e}"
        _set_progress({"phase": "error", "message": str(e), "eta_seconds": None})
    finally:
        cs.clear_cancel()


def _parse_multipart(handler):
    """极简 multipart 解析：返回 (fields:dict, files:dict[name->(filename, bytes)])"""
    ctype = handler.headers.get("Content-Type", "")
    length = int(handler.headers.get("Content-Length", "0"))
    body = handler.rfile.read(length)
    if "multipart/form-data" not in ctype:
        raise ValueError("需要 multipart/form-data")
    boundary = None
    for part in ctype.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part.split("=", 1)[1].strip().strip('"')
            break
    if not boundary:
        raise ValueError("缺少 boundary")
    delim = ("--" + boundary).encode()
    fields = {}
    files = {}
    for chunk in body.split(delim):
        if not chunk or chunk in (b"--\r\n", b"--", b"--\r\n"):
            continue
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        if chunk.endswith(b"\r\n"):
            chunk = chunk[:-2]
        if chunk == b"--":
            continue
        try:
            header_blob, data = chunk.split(b"\r\n\r\n", 1)
        except ValueError:
            continue
        if data.endswith(b"\r\n"):
            data = data[:-2]
        headers = header_blob.decode("utf-8", errors="replace").split("\r\n")
        disp = ""
        for h in headers:
            if h.lower().startswith("content-disposition:"):
                disp = h
        # name=
        name = None
        filename = None
        for token in disp.split(";"):
            token = token.strip()
            if token.startswith("name="):
                name = token.split("=", 1)[1].strip().strip('"')
            elif token.startswith("filename="):
                filename = token.split("=", 1)[1].strip().strip('"')
        if not name:
            continue
        if filename is not None and filename != "":
            files[name] = (filename, data)
        else:
            fields[name] = data.decode("utf-8", errors="replace")
    return fields, files


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, fmt, *args):
        print(f"[web] {self.address_string()} {fmt % args}")

    def _json(self, code, obj):
        raw = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self):
        n = int(self.headers.get("Content-Length", "0"))
        if n <= 0:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/status":
            return self._json(HTTPStatus.OK, _snapshot())
        if path == "/api/defaults":
            return self._json(
                HTTPStatus.OK,
                {
                    "target_height": 64,
                    "target_fps": 5,
                    "dither": True,
                    "dither_matrix_size": "auto",
                    "max_frames": None,
                    "dat_path": str(DAT_PATH),
                    "backup_path": str(cs.storage_backup_path(DAT_PATH)),
                    "mp_workers": cs.MP_WORKERS,
                    "pixel_budget": cs.MP_VIDEO_PIXEL_BUDGET,
                },
            )
        if path in ("/", "/index.html"):
            self.path = "/index.html"
            return super().do_GET()
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/restore":
            try:
                out = cs.restore_storage_from_backup(DAT_PATH)
                return self._json(HTTPStatus.OK, {"ok": True, "dat_path": str(out)})
            except Exception as e:
                return self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(e)})

        if path == "/api/stop":
            with _lock:
                st = _job.get("status")
                jid = _job.get("id")
            if st not in ("running", "queued"):
                return self._json(
                    HTTPStatus.OK,
                    {"ok": False, "error": f"当前无运行中任务（status={st}）"},
                )
            cs.request_cancel()
            _set_progress(
                {
                    "phase": "cancelling",
                    "message": "正在停止（当前批结束后生效）…",
                }
            )
            print(f"[web] stop requested job={jid}")
            return self._json(HTTPStatus.OK, {"ok": True, "job_id": jid})

        if path == "/api/start":
            with _lock:
                if _job["status"] == "running":
                    return self._json(
                        HTTPStatus.CONFLICT,
                        {"ok": False, "error": "已有任务在运行"},
                    )
            cs.clear_cancel()

            try:
                fields, files = _parse_multipart(self)
            except Exception as e:
                return self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(e)})

            if "file" not in files:
                return self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "缺少 file"})

            filename, data = files["file"]
            if not filename or not data:
                return self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "空文件"})

            safe_name = Path(filename).name
            job_id = uuid.uuid4().hex[:12]
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            dest = UPLOAD_DIR / f"{job_id}_{safe_name}"
            dest.write_bytes(data)

            def _bool(v, default=False):
                if v is None:
                    return default
                return str(v).lower() in ("1", "true", "yes", "on")

            def _int_or_none(v):
                if v is None or str(v).strip() == "":
                    return None
                return int(v)

            def _float_or_none(v):
                if v is None or str(v).strip() == "":
                    return None
                return float(v)

            source_name = (fields.get("source_name") or Path(safe_name).stem).strip()
            params = {
                "source_name": source_name,
                "target_height": int(fields.get("target_height") or 64),
                "target_fps": _float_or_none(fields.get("target_fps")) or 5.0,
                "dither": _bool(fields.get("dither"), True),
                "dither_matrix_size": fields.get("dither_matrix_size") or "auto",
                "dither_strength": _float_or_none(fields.get("dither_strength")),
                "max_frames": _int_or_none(fields.get("max_frames")),
                "data_version": int(fields.get("data_version") or 5003),
                "filename": safe_name,
                "upload_path": str(dest),
            }

            # 可选覆盖全局预算
            if fields.get("pixel_budget"):
                try:
                    cs.MP_VIDEO_PIXEL_BUDGET = int(fields["pixel_budget"])
                except ValueError:
                    pass

            with _lock:
                _job.update(
                    {
                        "id": job_id,
                        "status": "queued",
                        "created": time.time(),
                        "started": None,
                        "finished": None,
                        "params": params,
                        "result": None,
                        "error": None,
                        "progress": {
                            "phase": "queued",
                            "current": 0,
                            "total": None,
                            "percent": 0.0,
                            "elapsed": 0.0,
                            "eta_seconds": None,
                            "message": "排队中…",
                        },
                    }
                )

            global _worker_thread
            th = threading.Thread(
                target=_run_job, args=(job_id, dest, params), daemon=True
            )
            _worker_thread = th
            th.start()
            return self._json(HTTPStatus.OK, {"ok": True, "job_id": job_id})

        return self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})


def _watch_mtimes():
    """监视会热更新的源文件 mtime。"""
    paths = [ROOT / "web_app.py", ROOT / "cushion_screen.py"]
    if WEB_DIR.is_dir():
        for p in WEB_DIR.rglob("*"):
            if p.is_file() and p.suffix.lower() in {".html", ".js", ".css"}:
                paths.append(p)
    out = {}
    for p in paths:
        try:
            out[str(p)] = p.stat().st_mtime_ns
        except OSError:
            pass
    return out


def _run_server(host: str, port: int):
    index = WEB_DIR / "index.html"
    if not index.is_file():
        raise SystemExit(f"缺少前端页面: {index}")

    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Cushion Screen Web UI → http://{host}:{port}")
    print(f"DAT: {DAT_PATH}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        httpd.server_close()


def _run_with_reload(host: str, port: int):
    """
    父进程监视文件变更，子进程跑真正的 HTTP 服务。
    改 web_app.py / cushion_screen.py / web/* 会自动重启子进程。
    注意：运行中的处理任务会随重启中断。
    """
    print(f"[reload] 热重载已开启，监视 web_app.py / cushion_screen.py / web/")
    print(f"[reload] UI → http://{host}:{port}")
    child_env = os.environ.copy()
    child_env["CS_WEB_CHILD"] = "1"
    # 子进程不要再套一层 reload
    cmd = [sys.executable, str(Path(__file__).resolve()), "--host", host, "--port", str(port)]

    proc = None
    try:
        while True:
            mtimes = _watch_mtimes()
            proc = subprocess.Popen(cmd, env=child_env, cwd=str(ROOT))
            while True:
                time.sleep(0.6)
                code = proc.poll()
                if code is not None:
                    # 子进程异常退出：稍等再拉起
                    print(f"[reload] 子进程退出 code={code}，1s 后重启…")
                    time.sleep(1.0)
                    break
                now = _watch_mtimes()
                if now != mtimes:
                    changed = [p for p in now if now.get(p) != mtimes.get(p)]
                    print("[reload] 检测到变更:")
                    for p in changed[:8]:
                        print(f"  · {Path(p).name}")
                    print("[reload] 正在重启服务…")
                    proc.terminate()
                    try:
                        proc.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=3)
                    break
    except KeyboardInterrupt:
        print("\n[reload] 停止")
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def main():
    parser = argparse.ArgumentParser(description="Cushion Screen Web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="监视代码/前端变更并自动重启（开发用）",
    )
    args = parser.parse_args()

    # 子进程或未开 reload：直接跑 server
    if args.reload and os.environ.get("CS_WEB_CHILD") != "1":
        _run_with_reload(args.host, args.port)
    else:
        if os.environ.get("CS_WEB_CHILD") == "1":
            print("[reload] child server process")
        _run_server(args.host, args.port)


if __name__ == "__main__":
    main()
