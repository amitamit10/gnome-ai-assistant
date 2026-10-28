"""Antigravity CLI (`agy`) as an optional fallback LLM when the Gemini API quota is spent.

`agy` is an autonomous coding agent (it can write files, run commands and drive a browser), not a plain model, so it
is ONLY ever run inside a bubblewrap sandbox: the system is read-only, the home directory is hidden except agy's own
~/.gemini state and one empty scratch directory, /run is empty (so the session bus, the system bus and ssh/gpg agent
sockets are unreachable), the environment is rebuilt from an allowlist (no API keys, no D-Bus or display variables), and the
process has its own session (no TIOCSTI keystroke injection into your terminal), a minimal /dev and dies with its parent. `aiassistant doctor --deep` verifies the isolation with a canary file and a bus probe.
Not isolated: the network (agy needs it) and abstract unix sockets, which only a network namespace would hide. It is used as a text-only brain with a JSON protocol (see agent.py).
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


# the only environment variables the sandboxed agent gets (no keys, tokens, display or bus addresses)
_ENV_ALLOW = ("PATH", "LANG", "LC_ALL", "LANGUAGE", "TERM", "USER", "LOGNAME", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR",
              "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy")


def sandbox_prefix(bus_socket=None):
    """The bubblewrap command line that confines agy (everything up to, not including, the program to run).

    `bus_socket` is a filtered session-bus proxy socket (see start_bus_proxy); without it the sandbox has no D-Bus at all."""
    work = str(paths.ensure(paths.agy_workdir(), 0o700))
    gem = os.path.join(HOME, ".gemini")
    agy = agy_path()
    bw = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", HOME,
          "--bind", gem, gem, "--bind", work, work, "--ro-bind", agy, agy,
          "--tmpfs", "/tmp", "--tmpfs", "/run", "--ro-bind-try", "/run/systemd/resolve", "/run/systemd/resolve",  # DNS only
          "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--new-session", "--die-with-parent", "--chdir", work, "--clearenv",
          "--setenv", "HOME", HOME]
    for k in _ENV_ALLOW:
        if k in os.environ:
            bw += ["--setenv", k, os.environ[k]]
    if bus_socket:
        bw += ["--setenv", "DBUS_SESSION_BUS_ADDRESS", f"unix:path={bus_socket}"]
    ag = os.path.join(HOME, ".antigravity")
    if os.path.isdir(ag):
        bw += ["--bind", ag, ag]
    return bw


def start_bus_proxy():
    """agy keeps its login in the desktop keyring (Secret Service over the session bus), so it must reach the bus, but only that:
    xdg-dbus-proxy in --filter mode lets it talk to org.freedesktop.secrets and nothing else (not GNOME Shell, not this service).
    Returns (process, socket_path), or (None, None) when the proxy or the session bus is unavailable."""
    addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    exe = shutil.which("xdg-dbus-proxy")
    if not addr or not exe:
        return None, None
    sock = os.path.join(str(paths.ensure(paths.agy_workdir(), 0o700)), f"bus-{os.getpid()}-{time.monotonic_ns()}")
    p = subprocess.Popen([exe, addr, sock, "--filter", "--talk=org.freedesktop.secrets"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        if os.path.exists(sock):
            return p, sock
        if p.poll() is not None:
            break
        time.sleep(0.05)
    p.kill()
    return None, None


class Agy:
    def __init__(self):
        self.p = None
        self.lock = threading.Lock()
        self.last_used = time.time()
        self.bus_proc, self.bus_sock = None, None

    def _argv(self):
        agy = agy_path()
        return sandbox_prefix(self.bus_sock) + [agy, "-p=", "--input-format", "stream-json", "--output-format", "stream-json",
                                   "--model", config.get("agy_model"), "--sandbox"]

    def _spawn(self):
        self.close()
        # off by default: the Secret Service has no per-application access control, so this exposes every secret in the keyring
        self.bus_proc, self.bus_sock = start_bus_proxy() if config.get("agy_keyring") else (None, None)
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
                            msg = str(res.get("error") or res.get("status"))[:150]
                            if "authentication" in msg.lower() and not self.bus_sock:
                                msg += (" (agy keeps its login in the desktop keyring, which the sandbox hides by default; to allow it, "
                                        "run: aiassistant config set agy_keyring true. Read SECURITY.md first.)")
                            raise AgyError("Antigravity error: " + msg)
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

    def _stop_bus_proxy(self):
        proc, sock, self.bus_proc, self.bus_sock = self.bus_proc, self.bus_sock, None, None
        if proc:
            proc.kill()
        if sock:
            try:
                os.remove(sock)
            except OSError:
                pass

    def close(self):
        self._stop_bus_proxy()
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
