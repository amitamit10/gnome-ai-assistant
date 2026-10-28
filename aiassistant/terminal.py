"""AI help for the shell: explain a failed command, turn a description into a command, answer a quick question.

Safety design:
  * Nothing is ever executed here. The bash integration shows a suggested command and asks you (destructive ones need
    you to type RUN).
  * Only the command *text*, exit status and working-directory name are sent, after obvious secrets are scrubbed
    (tokens, API keys, passwords, long random strings). Output of commands is never captured or sent.
  * Risk is judged by local rules, not by the model: the model may only make it stricter.
"""
import json
import os
import re

from .llm import gemini

# ---------------------------------------------------------------- redaction
_SECRET_PATTERNS = [
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"), "<token>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "<token>"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b"), "<api-key>"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"), "<api-key>"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"), "<token>"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "<aws-key>"),
    (re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=\-]{8,}"), r"\1 <token>"),
    (re.compile(r"(?i)(--?(?:password|passwd|pass|token|secret|api[-_]?key|auth)(?:=|\s+))(\S+)"), r"\1<redacted>"),
    (re.compile(r"(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|PRIVATE_?KEY|CREDENTIALS?)[A-Z0-9_]*=)(\S+)"), r"\1<redacted>"),
    (re.compile(r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key)=([^\s&]+)"), r"\1=<redacted>"),
    (re.compile(r"(https?://[^/\s:@]+:)([^@\s]+)(@)"), r"\1<redacted>\3"),           # user:pass@host
    (re.compile(r"\b[A-Za-z0-9+/_\-]{40,}={0,2}\b"), "<redacted>"),                    # long random-looking strings
]


def redact(text):
    """Scrub secrets from command text before it is sent anywhere."""
    for pat, rep in _SECRET_PATTERNS:
        text = pat.sub(rep, text)
    return text


# ---------------------------------------------------------------- risk
_DESTRUCTIVE = [
    r"\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*[rf][a-zA-Z]*\b", r"\brm\s+.*\s/(\s|$)", r"\bdd\s+.*\bof=", r"\bmkfs(\.\w+)?\b", r">\s*/dev/(sd|nvme|mmcblk|disk)",
    r"\bshred\b", r"\bwipefs\b", r"\bfdisk\b|\bparted\b|\bsfdisk\b", r":\(\)\s*\{", r"\bchmod\s+(-R\s+)?[0-7]*777\s+/", r"\bchown\s+-R\s+\S+\s+/(\s|$)",
    r"\bgit\s+push\s+.*(--force|-f)\b", r"\bgit\s+reset\s+--hard\b", r"\bgit\s+clean\s+-[a-z]*f", r"\bdrop\s+(table|database)\b", r"\btruncate\b",
    r"\bfind\b.*\s-delete\b", r"\bfind\b.*-exec\s+rm\b", r"\bxargs\s+.*\brm\b", r"\bmv\s+.*\s/dev/null\b", r"\bsudo\s+rm\b", r"\bnpm\s+publish\b",
    r"\bcurl\b.*\|\s*(sudo\s+)?(ba|z)?sh\b", r"\bwget\b.*\|\s*(sudo\s+)?(ba|z)?sh\b", r"\bkillall\b|\bpkill\s+-9\b",
]
_CAUTION = [r"\bsudo\b", r"\bapt(-get)?\s+(remove|purge|autoremove|install|upgrade|dist-upgrade)\b", r"\bsystemctl\s+(stop|disable|mask|restart|reboot)\b",
            r"\bkill\b", r"\breboot\b|\bshutdown\b|\bpoweroff\b", r"\bchmod\b|\bchown\b", r"\bmv\b", r"\bgit\s+(checkout|rebase|stash)\b", r"\bpip\s+uninstall\b",
            r">\s*\S+", r"\bcrontab\b", r"\bufw\b|\biptables\b", r"\bdocker\s+(rm|rmi|system\s+prune|volume\s+rm)\b"]
_RANK = {"safe": 0, "caution": 1, "destructive": 2}


def risk_of(command):
    """'destructive' | 'caution' | 'safe' by local rules (never by the model)."""
    c = command.strip()
    if any(re.search(p, c, re.I) for p in _DESTRUCTIVE):
        return "destructive"
    if any(re.search(p, c, re.I) for p in _CAUTION):
        return "caution"
    return "safe"


def _max_risk(a, b):
    return a if _RANK[a] >= _RANK.get(b, 0) else b


# ---------------------------------------------------------------- AI helpers
def suggest(description, cwd="", shell="bash"):
    """Returns {"command", "explanation", "risk"}. Raises gemini.GeminiError when the model is unavailable."""
    desc = redact(description).strip()[:600]
    r = gemini.json_call(
        f"You turn a plain-language request into ONE {shell} command for a Linux (GNOME, Ubuntu-based) desktop. "
        "Prefer standard tools, read-only/safe commands, and a single command or short pipeline; no placeholders when avoidable; "
        "never delete or overwrite anything unless the user clearly asked. "
        'Return JSON {"command": str, "explanation": str (one short sentence), "risk": "safe"|"caution"|"destructive"}. '
        f"Current directory name: {os.path.basename(cwd) or '/'}. Request: {desc!r}", timeout=40)
    if not isinstance(r, dict) or not isinstance(r.get("command"), str) or not r["command"].strip():
        raise gemini.GeminiError("the model did not return a command (quota used up, or no API key?)")
    cmd = r["command"].strip().strip("`")
    return {"command": cmd, "explanation": str(r.get("explanation", ""))[:200],
            "risk": _max_risk(risk_of(cmd), str(r.get("risk", "safe")))}


def explain(command, status, cwd=""):
    """Plain-text help about a command that failed (or just ran). Sends the redacted command text only."""
    cmd = redact(command).strip()[:800]
    if not cmd:
        return "There is no previous command to explain."
    _, r = gemini.generate(
        [{"role": "user", "parts": [{"text":
            f"A user ran this in bash and it exited with status {status}. Directory name: {os.path.basename(cwd) or '/'}.\n"
            f"Command: {cmd}\n\nIn at most 8 short lines: say what the command does, the most likely reason for exit status {status} "
            "(you cannot see its output), and 1-3 concrete things to try, as commands on their own lines. Plain text, no markdown. "
            "Only suggest harmless diagnostic or corrective commands (never create, delete or change system paths just to make an error go away), "
            "and do not mention the directory name unless the failure depends on it."}]}],
        system="You are a concise Linux shell expert. Be honest about uncertainty; do not invent output.", timeout=45)
    return gemini.text_of(r).strip()


def ask(question):
    _, r = gemini.generate([{"role": "user", "parts": [{"text": redact(question)[:2000]}]}],
                           system="Answer for a Linux terminal: concise, at most ~10 lines, plain text, commands on their own lines.", timeout=45)
    return gemini.text_of(r).strip()


# ---------------------------------------------------------------- bash integration
BASH_INIT = r'''# gnome-ai-assistant shell integration (generated by `aiassistant term init bash`; regenerate after upgrades)
# Adds: ai explain | ai cmd "..." | ai "question" | ai chat, and Ctrl+X Ctrl+A to turn the typed words into a command.
# Nothing is ever run without your confirmation. Only command text (secrets scrubbed) is sent, never output.
[[ $- == *i* || -n "${AIA_FORCE:-}" ]] || return 0

__aia_last_cmd=""; __aia_last_status=0; __aia_seen=0
# Record only the FIRST run of this hook per prompt. Starship re-runs the old PROMPT_COMMAND hooks itself after a `[[ ]]` test
# that resets $? to 0, which would overwrite the real exit status with 0. PS0 (below) clears the flag before each command.
__aia_precmd() {
  local st=$?
  [ "$__aia_seen" = 1 ] && return $st
  __aia_seen=1
  local c
  c="$(HISTTIMEFORMAT= history 1 2>/dev/null | sed 's/^ *[0-9]* *//')"
  case "$c" in ai|ai\ *|"") ;; *) __aia_last_cmd="$c"; __aia_last_status=$st ;; esac
  return $st   # keep $? intact for the next prompt hook (starship reads it)
}
case ";${PROMPT_COMMAND:-};" in *";__aia_precmd;"*|*"; __aia_precmd;"*) ;; *) PROMPT_COMMAND="__aia_precmd${PROMPT_COMMAND:+; $PROMPT_COMMAND}" ;; esac
# PS0 is expanded just before each command runs; the arithmetic trick resets the flag without printing anything.
# Prompt frameworks (starship) overwrite PS0 when initialised, so terminal.bash calls __aia_ps0 again after them.
__aia_ps0() { case "${PS0:-}" in *__aia_seen*) ;; *) PS0="${PS0:-}"'${__aia_seen:$((__aia_seen=0)):0}' ;; esac; }
__aia_ps0

__aia_c() { local code="$1"; shift; if [ -t 1 ]; then printf '\033[%sm%s\033[0m' "$code" "$*"; else printf '%s' "$*"; fi; }

# parse the JSON reply of `aiassistant term suggest`: prints three lines: command, risk, explanation
__aia_parse() { python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["command"].replace("\n"," ; ")); print(d["risk"]); print(d["explanation"])'; }

__aia_suggest() {   # $1 = description -> sets __aia_cmd __aia_risk __aia_expl
  local out parsed
  out="$(aiassistant term suggest --cwd "$PWD" --text="$1")" || { printf '%s\n' "$out" >&2; return 1; }
  parsed="$(printf '%s' "$out" | __aia_parse)" || return 1
  __aia_cmd="$(printf '%s\n' "$parsed" | sed -n 1p)"; __aia_risk="$(printf '%s\n' "$parsed" | sed -n 2p)"; __aia_expl="$(printf '%s\n' "$parsed" | sed -n 3p)"
}

ai() {
  case "${1:-}" in
    ""|-h|--help|help)
      printf 'ai explain          explain the last command (why it may have failed)\n'
      printf 'ai cmd "describe"   get a command for what you describe; you confirm before it runs\n'
      printf 'ai "question"       quick answer\n'
      printf 'ai chat             open the chat window\n'
      printf 'Ctrl+X Ctrl+A       replace the words you typed with a suggested command (not run)\n' ;;
    explain) aiassistant term explain --cmd "$__aia_last_cmd" --status "$__aia_last_status" --cwd "$PWD" ;;
    chat|open) aiassistant chat ;;
    cmd|do)
      shift; [ -n "$*" ] || { echo 'usage: ai cmd "what you want to do"' >&2; return 2; }
      __aia_suggest "$*" || return 1
      printf '\n  %s\n' "$(__aia_c '1;36' "$__aia_cmd")"; [ -n "$__aia_expl" ] && printf '  %s\n' "$__aia_expl"
      local ans typed
      if [ "$__aia_risk" = destructive ]; then
        printf '  %s\n' "$(__aia_c '1;31' 'DESTRUCTIVE: this can delete or overwrite data.')"
        read -r -p '  Type RUN to execute, anything else cancels: ' typed
        [ "$typed" = RUN ] || { echo '  cancelled'; return 0; }
      else
        [ "$__aia_risk" = caution ] && printf '  %s\n' "$(__aia_c '33' 'caution: changes something on your system')"
        read -r -n1 -p '  Run it? [y]es / [e]dit / [N]o: ' ans; echo
        case "$ans" in
          y|Y) ;;
          e|E) read -e -i "$__aia_cmd" -p '  edit> ' __aia_cmd || return 0 ;;
          *) echo '  cancelled'; return 0 ;;
        esac
      fi
      history -s "$__aia_cmd"
      eval "$__aia_cmd" ;;
    *) aiassistant term ask --text="$*" ;;
  esac
}

# Ctrl+X Ctrl+A: replace what you typed (a description) with a suggested command; you still press Enter yourself
__aia_line() {
  local desc="$READLINE_LINE"; [ -n "$desc" ] || return 0
  printf '\n%s' "$(__aia_c '2' '  thinking...')" >&2
  if __aia_suggest "$desc" 2>/dev/null; then
    printf '\r\033[K' >&2
    [ "$__aia_risk" = destructive ] && printf '%s\n' "$(__aia_c '1;31' '  DESTRUCTIVE: read it carefully before pressing Enter')" >&2
    READLINE_LINE="$__aia_cmd"; READLINE_POINT=${#READLINE_LINE}
  else
    printf '\r\033[K%s\n' "$(__aia_c '31' '  no suggestion (quota used up or no API key?)')" >&2
  fi
}
bind -x '"\C-x\C-a": __aia_line' 2>/dev/null
'''


def init_script(shell="bash"):
    if shell != "bash":
        raise ValueError("only bash is supported for now")
    return BASH_INIT
