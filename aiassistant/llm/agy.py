"""Antigravity CLI (`agy`) as an optional fallback LLM when the Gemini API quota is spent.

`agy` is an autonomous coding agent (it can write files, run commands and drive a browser), not a plain model, so it
is ONLY ever run inside a bubblewrap sandbox: the system is read-only, the home directory is hidden except agy's own
~/.gemini state and one empty scratch directory, and the process dies with its parent. `aiassistant doctor --deep`
verifies that isolation with a canary file. It is used as a text-only brain with a JSON protocol (see agent.py).
Never pass --dangerously-skip-permissions here. This backend never reads agy's credentials.

Check Google's terms for the Antigravity CLI before enabling it: set "provider": "api" to disable it.
"""
import json
import os
import select
import shutil
import subprocess
import threading
import time

from .. import config, paths

HOME = os.path.expanduser("~")


def agy_path():
    return shutil.which("agy") or os.path.join(HOME, ".local/bin/agy")


def available():
    return os.path.exists(agy_path()) and shutil.which("bwrap") is not None


class AgyError(RuntimeError):
    pass


class Agy:
    def __init__(self):
        self.p = None
        self.lock = threading.Lock()
        self.last_used = time.time()

    def _argv(self):
        work = str(paths.ensure(paths.agy_workdir(), 0o700))
        gem = os.path.join(HOME, ".gemini")
        agy = agy_path()
        bw = ["bwrap", "--ro-bind", "/", "/", "--dev-bind", "/dev", "/dev", "--proc", "/proc", "--tmpfs", HOME,
              "--bind", gem, gem, "--bind", work, work, "--ro-bind", agy, agy,
              "--tmpfs", "/tmp", "--unshare-pid", "--die-with-parent", "--chdir", work]
        ag = os.path.join(HOME, ".antigravity")
        if os.path.isdir(ag):
            bw += ["--bind", ag, ag]
        return bw + [agy, "-p=", "--input-format", "stream-json", "--output-format", "stream-json",
                     "--model", config.get("agy_model"), "--sandbox"]

    def _spawn(self):
        self.close()
        self.p = subprocess.Popen(self._argv(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, bufsize=1)

    def turn(self, message, timeout=150):
        """Send one user message, return the final response text. Raises AgyError on failure."""
        if not available():
            raise AgyError("Antigravity CLI (agy) or bubblewrap (bwrap) is not installed")
        with self.lock:
            for _attempt in (1, 2):  # one respawn if the process died
                if self.p is None or self.p.poll() is not None:
                    self._spawn()
                try:
                    self.p.stdin.write(json.dumps({"event": "user", "message": {"content": message}}) + "\n")
                    self.p.stdin.flush()
                except (BrokenPipeError, OSError):
                    self.p = None
                    continue
                t0 = time.time()
                while time.time() - t0 < timeout:
                    r, _, _ = select.select([self.p.stdout], [], [], 1)
                    if not r:
                        continue
                    line = self.p.stdout.readline()
                    if not line:
                        break
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("event") == "result":
                        res = ev["result"]
                        self.last_used = time.time()
                        if res.get("status") != "SUCCESS":
                            raise AgyError("Antigravity error: " + str(res.get("error") or res.get("status"))[:150])
                        return res.get("response", "")
                self.close()
                if time.time() - t0 >= timeout:
                    raise AgyError("Antigravity timed out")
            raise AgyError("Antigravity process keeps exiting")

    def idle_close(self, after=600):
        if self.p is not None and time.time() - self.last_used > after and self.lock.acquire(blocking=False):
            try:
                self.close()
            finally:
                self.lock.release()

    def close(self):
        p, self.p = self.p, None
        if p and p.poll() is None:
            try:
                p.stdin.close()
            except OSError:
                pass
            try:
                p.terminate()
                p.wait(timeout=3)
            except Exception:
                p.kill()
