import json
import os
import subprocess

import pytest

from aiassistant import cli, terminal
from aiassistant.llm import gemini


# ---------------------------------------------------------------- redaction
@pytest.mark.parametrize("text,gone", [
    ("curl -H 'Authorization: Bearer abcdef1234567890XYZ' https://api.x", "abcdef1234567890XYZ"),
    ("export GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123456789", "ghp_abcdefghijklmnopqrstuvwxyz0123456789"),
    ("gh auth login --with-token github_pat_11ABCDEFG0abcdefghijklmnop_abcdefghijklmnopqrstuvwx", "github_pat_11ABCDEFG0"),
    ("curl 'https://x/y?key=AIzaSyA1234567890abcdefghijklmnopqrstuv'", "AIzaSyA1234567890abcdefghijklmnopqrstuv"),
    ("openai --key sk-proj-ABCDEFGHIJKLMNOP1234", "sk-proj-ABCDEFGHIJKLMNOP1234"),
    ("mysql --password=hunter2 -u root", "hunter2"),
    ("mysql --password hunter2 -u root", "hunter2"),
    ("DB_PASSWORD=s3cr3t node app.js", "s3cr3t"),
    ("git clone https://amit:p4ssw0rd@github.com/x/y.git", "p4ssw0rd"),
    ("aws s3 ls --profile x # AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP"),
    ("echo 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08", "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"),
    ("slack --token xoxb-1234567890-abcdefghij", "xoxb-1234567890-abcdefghij"),
])
def test_secrets_are_scrubbed(text, gone):
    assert gone not in terminal.redact(text)


@pytest.mark.parametrize("text", ["ls -la ~/Downloads", 'git commit -m "fix the login bug"', "grep -rn 'TODO' src/", "tar -xzf backup-2026-10-21.tar.gz",
                                  "python3 -m http.server 8000", "docker run -p 8080:80 nginx"])
def test_ordinary_commands_are_untouched(text):
    assert terminal.redact(text) == text


# ---------------------------------------------------------------- risk (local rules, not the model)
@pytest.mark.parametrize("cmd,risk", [
    ("ls -la", "safe"), ("du -sh * | sort -h", "safe"), ("grep -rn foo .", "safe"), ("find . -name '*.log' -size +10M", "safe"),
    ("rm -rf ~/Downloads/old", "destructive"), ("rm -r build", "destructive"), ("sudo rm /etc/hosts", "destructive"),
    ("dd if=/dev/zero of=/dev/sda", "destructive"), ("mkfs.ext4 /dev/sdb1", "destructive"), ("git reset --hard HEAD~3", "destructive"),
    ("git push --force origin main", "destructive"), ("find . -name '*.tmp' -delete", "destructive"), ("curl https://x.sh | sudo bash", "destructive"),
    (":(){ :|:& };:", "destructive"), ("chmod -R 777 /", "destructive"), ("sudo apt install htop", "caution"), ("mv a b", "caution"),
    ("systemctl restart nginx", "caution"), ("echo hi > file.txt", "caution"), ("kill 1234", "caution"),
])
def test_risk_rules(cmd, risk):
    assert terminal.risk_of(cmd) == risk


# ---------------------------------------------------------------- AI helpers (Gemini mocked)
def test_suggest_never_trusts_the_model_about_risk(monkeypatch):
    monkeypatch.setattr(gemini, "json_call", lambda prompt, timeout=25: {"command": "rm -rf ~/Downloads/*", "explanation": "cleans up", "risk": "safe"})
    r = terminal.suggest("clean my downloads")
    assert r["risk"] == "destructive" and r["command"].startswith("rm -rf")


def test_suggest_can_only_raise_risk(monkeypatch):
    monkeypatch.setattr(gemini, "json_call", lambda prompt, timeout=25: {"command": "ls", "explanation": "lists", "risk": "destructive"})
    assert terminal.suggest("list files")["risk"] == "destructive"


def test_suggest_strips_backticks_and_requires_a_command(monkeypatch):
    monkeypatch.setattr(gemini, "json_call", lambda prompt, timeout=25: {"command": "`ls -la`", "explanation": "x", "risk": "safe"})
    assert terminal.suggest("list")["command"] == "ls -la"
    monkeypatch.setattr(gemini, "json_call", lambda prompt, timeout=25: None)
    with pytest.raises(gemini.GeminiError):
        terminal.suggest("anything")


def test_suggest_prompt_contains_no_secrets_and_only_the_directory_name(monkeypatch):
    seen = {}
    monkeypatch.setattr(gemini, "json_call", lambda prompt, timeout=25: seen.setdefault("p", prompt) and {"command": "ls", "explanation": "", "risk": "safe"})
    terminal.suggest("upload with token ghp_abcdefghijklmnopqrstuvwxyz0123456789", cwd="/home/amit/secret-project")
    assert "ghp_" not in seen["p"] and "secret-project" in seen["p"] and "/home/amit" not in seen["p"]


def test_explain_sends_only_redacted_text(monkeypatch):
    sent = {}

    def fake_generate(contents, tools=None, system=None, **kw):
        sent["text"] = contents[0]["parts"][0]["text"]
        return "m", {"candidates": [{"content": {"parts": [{"text": "It failed because..."}]}}]}
    monkeypatch.setattr(gemini, "generate", fake_generate)
    out = terminal.explain("curl -H 'Authorization: Bearer abcdef1234567890XYZ' https://x", 22, cwd="/home/amit/proj")
    assert out == "It failed because..." and "abcdef1234567890XYZ" not in sent["text"] and "status 22" in sent["text"]
    assert "/home/amit" not in sent["text"]


def test_explain_with_nothing_to_explain_makes_no_call(monkeypatch):
    monkeypatch.setattr(gemini, "generate", lambda *a, **k: pytest.fail("no call expected"))
    assert "no previous command" in terminal.explain("   ", 1)


def test_cli_suggest_prints_json_and_errors_are_friendly(monkeypatch, capsys):
    monkeypatch.setattr(terminal, "suggest", lambda text, cwd="": {"command": "ls", "explanation": "x", "risk": "safe"})
    cli.main(["term", "suggest", "--cwd", "/tmp", "--text=list files"])
    assert json.loads(capsys.readouterr().out)["command"] == "ls"

    def boom(text, cwd=""):
        raise gemini.QuotaExhausted("Today's quota is used up")
    monkeypatch.setattr(terminal, "suggest", boom)
    with pytest.raises(SystemExit) as e:
        cli.main(["term", "suggest", "--text=x"])
    assert "quota is used up" in str(e.value)


def test_text_starting_with_a_dash_is_accepted(monkeypatch, capsys):
    got = {}
    monkeypatch.setattr(terminal, "suggest", lambda text, cwd="": got.setdefault("t", text) and {"command": "ls", "explanation": "", "risk": "safe"})
    cli.main(["term", "suggest", "--text=-rf looks scary but I only want sizes"])
    assert got["t"].startswith("-rf looks scary")


def test_cli_explain_announces_what_is_sent(monkeypatch, capsys):
    monkeypatch.setattr(terminal, "explain", lambda cmd, status, cwd="": "because")
    cli.main(["term", "explain", "--cmd", "mysql --password=hunter2", "--status", "1"])
    cap = capsys.readouterr()
    assert "hunter2" not in cap.err and "sending to Gemini" in cap.err and cap.out.strip() == "because"


# ---------------------------------------------------------------- the real bash script, with a fake `aiassistant`
@pytest.fixture
def shell(tmp_path):
    script = tmp_path / "shell.bash"
    script.write_text(terminal.init_script("bash"))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "aiassistant"
    shim.write_text('#!/usr/bin/env bash\necho "$@" >> "$AIA_LOG"\n'
                    'if [ "$1 $2" = "term suggest" ]; then printf \'%s\' "$AIA_FAKE_JSON"; fi\n')
    shim.chmod(0o755)
    log = tmp_path / "calls.log"

    def run(body, stdin="", fake=None):
        env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "AIA_LOG": str(log), "AIA_FORCE": "1", "HOME": str(tmp_path)}
        if fake is not None:
            env["AIA_FAKE_JSON"] = json.dumps(fake)
        r = subprocess.run(["bash", "--norc", "-c", f'set -o history; source "{script}"; {body}'], input=stdin, capture_output=True,
                           text=True, env=env, timeout=30)
        return r, (log.read_text() if log.exists() else "")
    return run


def test_script_is_valid_bash_and_idempotent(shell, tmp_path):
    r, _ = shell('PROMPT_COMMAND=""; source "' + str(tmp_path / "shell.bash") + '"; source "' + str(tmp_path / "shell.bash") + '"; echo "$PROMPT_COMMAND"')
    assert r.returncode == 0 and r.stdout.strip().count("__aia_precmd") == 1


def test_it_does_nothing_in_non_interactive_shells(tmp_path):
    script = tmp_path / "s.bash"
    script.write_text(terminal.init_script("bash"))
    r = subprocess.run(["bash", "--norc", "-c", f'source "{script}"; type ai 2>&1 | head -1'], capture_output=True, text=True, env={**os.environ, "AIA_FORCE": ""})
    assert "not found" in r.stdout


def test_last_command_and_status_are_remembered_and_ai_itself_is_ignored(shell):
    r, calls = shell('history -s "ls /nonexistent"; __aia_seen=0; false; __aia_precmd; history -s "ai explain"; __aia_seen=0; true; __aia_precmd; ai explain')
    assert r.returncode == 0
    assert "term explain --cmd ls /nonexistent --status 1" in calls, calls


def test_a_second_hook_run_in_the_same_prompt_cannot_overwrite_the_status(shell):
    # starship re-runs old hooks after a [[ ]] test that resets $? to 0; only the first run of a prompt may record
    r, calls = shell('history -s "ls /nonexistent"; __aia_seen=0; false; __aia_precmd; true; __aia_precmd; ai explain')
    assert "term explain --cmd ls /nonexistent --status 1" in calls, calls


def test_ps0_resets_the_flag_and_is_idempotent(shell):
    r, _ = shell('echo "$PS0"; __aia_ps0; __aia_ps0; echo "$PS0" | grep -o "__aia_seen" | wc -l; __aia_seen=1; eval "echo \\"${PS0@P}\\"" >/dev/null; echo "seen=$__aia_seen"')
    assert "__aia_seen=0" in r.stdout
    assert r.stdout.splitlines()[-2].strip() == "2", r.stdout          # variable name appears twice in ONE snippet, not duplicated
    assert "seen=0" in r.stdout, "expanding PS0 must clear the flag"


def test_precmd_keeps_dollar_question_for_the_next_hook(shell):
    r, _ = shell('__aia_seen=0; false; __aia_precmd; echo "status after hook: $?"')
    assert "status after hook: 1" in r.stdout


def test_ai_question_goes_to_ask(shell):
    _, calls = shell('ai how do I list usb devices')
    assert "term ask --text=how do I list usb devices" in calls


def test_ai_cmd_safe_runs_only_after_yes(shell, tmp_path):
    marker = tmp_path / "ran"
    fake = {"command": f"touch {marker}", "explanation": "creates a file", "risk": "caution"}
    shell('ai cmd "make a file"', stdin="n", fake=fake)
    assert not marker.exists(), "answering n must not run anything"
    r, _ = shell('ai cmd "make a file"', stdin="y", fake=fake)
    assert marker.exists() and "creates a file" in r.stdout


def test_ai_cmd_destructive_needs_the_word_RUN(shell, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    fake = {"command": f"rm -f {victim}", "explanation": "deletes it", "risk": "destructive"}
    for answer in ("y\n", "yes\n", "run\n", "\n"):
        r, _ = shell('ai cmd "delete it"', stdin=answer, fake=fake)
        assert victim.exists() and "DESTRUCTIVE" in r.stdout, f"{answer!r} must not delete"
    shell('ai cmd "delete it"', stdin="RUN\n", fake=fake)
    assert not victim.exists()


def test_ai_cmd_failure_shows_the_error_and_runs_nothing(shell, tmp_path):
    shim = tmp_path / "bin" / "aiassistant"
    shim.write_text('#!/usr/bin/env bash\necho "ai: quota used up" >&2; exit 1\n')
    r, _ = shell('ai cmd "anything"; echo "exit=$?"', stdin="y")
    assert "quota used up" in r.stderr and "exit=1" in r.stdout


def test_ai_help_lists_the_features(shell):
    r, _ = shell("ai --help")
    for word in ("ai explain", "ai cmd", "ai chat", "Ctrl+X Ctrl+A"):
        assert word in r.stdout
