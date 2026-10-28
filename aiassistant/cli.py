"""`aiassistant` command line."""
import argparse
import json
import os
import sys

from . import __version__, config, paths


def _search(a):
    from .search import query
    from .tools import files
    hits = query.shared().search(" ".join(a.query), per_kind=({a.type: a.n} if a.type else {"image": a.n, "text": a.n, "video": a.n}), use_llm=not a.no_llm)
    for h in hits[:a.n * (1 if a.type else 3)]:
        extra = f" @{h['label']}" if h["kind"] == "video" else ""
        print(f"{h['score']:.2f}  [{h['kind']}] {files.short(h['path'])}{extra}")
    if not hits:
        print("no results")


def _ask(a):
    from .search import ask
    got = ask.answer(" ".join(a.question))
    if not got:
        sys.exit("no answer (is the index built and the Gemini key set?)")
    text, srcs = got
    print(text)
    from .tools import files
    for s in srcs:
        print("  <-", files.short(s))


def _index(a):
    from .search import index
    if a.stats:
        for k, v in index.stats().items():
            print(f"{k:6} {v['files']} files, {v['vectors']} vectors")
    elif a.export:
        index.export_bundle()
    elif a.import_vectors:
        index.import_vectors(a.import_vectors)
    else:
        index.build()


def _chat(a):
    """Open the chat window through the D-Bus service (starting it if needed)."""
    from . import constants as C
    import subprocess
    r = subprocess.run(["gdbus", "call", "--session", "--timeout", "30", "--dest", C.BUS_NAME, "--object-path", C.CONTROL_PATH,
                        "--method", f"{C.CONTROL_IFACE}.Open"], capture_output=True, text=True)
    if r.returncode:
        sys.exit("could not reach the service over D-Bus: " + (r.stderr or r.stdout).strip()
                 + "\nIs it installed? (see README)")


def _window(a):
    """The native chat window itself (normally started by the service on Open())."""
    from .native import app
    sys.exit(app.main())


def _service(a):
    from . import service
    service.main()


def _config(a):
    cfg = config.load()
    if a.action == "show":
        print(json.dumps({k: v for k, v in cfg.items()}, indent=2))
        print(f"\nfile: {paths.config_file()}   gemini key: {'set' if config.gemini_key() else 'NOT set'}")
    elif a.action == "set":
        if not a.key or a.value is None:
            sys.exit("usage: aiassistant config set KEY VALUE (VALUE is JSON, e.g. '\"api\"' or '[\"~/Notes\"]')")
        try:
            val = json.loads(a.value)
        except ValueError:
            val = a.value
        config.save({a.key: val})
        print(f"set {a.key} = {json.dumps(val)}")
    elif a.action == "key":
        import getpass
        k = getpass.getpass("Paste your Gemini API key (input hidden): ").strip()
        if k:
            paths.ensure(paths.config_dir(), 0o700)
            fd = os.open(paths.key_file(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(k + "\n")
            print("saved to", paths.key_file())


def _widgets(a):
    from .ui import widgets
    if a.action == "list":
        for n in widgets.names():
            print(f"{n:16} {widgets.load(n).get('description', '')[:90]}")
    elif a.action == "check":
        from .native import widgets as native
        bad = 0
        for n in widgets.names():
            err = widgets.validate_data(n, widgets.load(n)["example"]) or (None if n in native.BUILDERS else "no native builder")
            print(f"{'PROBLEM' if err else 'ok':8} {n}  {err or ''}")
            bad += bool(err)
        sys.exit(1 if bad else 0)


def _term(a):
    """Shell helpers: used by the bash integration (`aiassistant term init bash > ~/.config/.../shell.bash`)."""
    from . import terminal
    from .llm import gemini
    if a.action == "init":
        sys.stdout.write(terminal.init_script(a.rest[0] if a.rest else "bash"))
        return
    text = (a.text or " ".join(a.rest)).strip()
    try:
        if a.action == "suggest":
            print(json.dumps(terminal.suggest(text, cwd=a.cwd)))
        elif a.action == "explain":
            if not a.cmd:
                print("There is no previous command to explain.")
                return
            print(f"(sending to Gemini: {terminal.redact(a.cmd)[:200]})", file=sys.stderr)
            print(terminal.explain(a.cmd, a.status, cwd=a.cwd))
        elif a.action == "ask":
            print(terminal.ask(text))
    except gemini.GeminiError as e:
        sys.exit(f"ai: {e}")


def _doctor(a):
    from . import doctor
    sys.exit(doctor.run(deep=a.deep))


def main(argv=None):
    p = argparse.ArgumentParser(prog="aiassistant", description="AI assistant for the GNOME desktop")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("chat", help="open the chat window").set_defaults(fn=_chat)
    sub.add_parser("window", help="run the native chat window (normally started by the service)").set_defaults(fn=_window)
    sub.add_parser("service", help="run the background service (normally started by D-Bus)").set_defaults(fn=_service)
    s = sub.add_parser("search", help="semantic search over your files")
    s.add_argument("query", nargs="+")
    s.add_argument("-n", type=int, default=5, help="results per kind")
    s.add_argument("-t", "--type", choices=["text", "image", "video"])
    s.add_argument("--no-llm", action="store_true", help="skip the Gemini query rewrite")
    s.set_defaults(fn=_search)
    s = sub.add_parser("ask", help="answer a question from your notes")
    s.add_argument("question", nargs="+")
    s.set_defaults(fn=_ask)
    s = sub.add_parser("index", help="build or update the search index")
    s.add_argument("--stats", action="store_true")
    s.add_argument("--export", action="store_true", help="pack unindexed files for GPU embedding on Colab")
    s.add_argument("--import", dest="import_vectors", metavar="VECTORS.NPY", help="load vectors produced by the notebook")
    s.set_defaults(fn=_index)
    s = sub.add_parser("config", help="show or change settings")
    s.add_argument("action", choices=["show", "set", "key"])
    s.add_argument("key", nargs="?")
    s.add_argument("value", nargs="?")
    s.set_defaults(fn=_config)
    s = sub.add_parser("widgets", help="manage the widget library")
    s.add_argument("action", choices=["list", "check"])
    s.set_defaults(fn=_widgets)
    s = sub.add_parser("term", help="shell helpers (explain a failed command, describe -> command, quick answers)")
    s.add_argument("action", choices=["init", "suggest", "explain", "ask"])
    s.add_argument("--cmd", default="", help="explain: the command that ran")
    s.add_argument("--status", type=int, default=1, help="explain: its exit status")
    s.add_argument("--cwd", default="", help="current directory (only its name is sent)")
    s.add_argument("--text", default="", help="the description/question (use --text=... so a leading dash is fine)")
    s.add_argument("rest", nargs="*")
    s.set_defaults(fn=_term)
    s = sub.add_parser("doctor", help="check the whole setup")
    s.add_argument("--deep", action="store_true", help="also probe Gemini quotas and the Antigravity sandbox")
    s.set_defaults(fn=_doctor)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
