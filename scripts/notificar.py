#!/usr/bin/env python3
"""Notificação de desktop opcional (padrão: desligada).

Backends: notify-send (Linux), osascript (macOS) e powershell (Windows ou WSL). Em nenhum
deles o texto é interpolado em código: notify-send recebe o texto como argumento depois de
`--`; o AppleScript é fixo e lê o texto de `argv`; o script do PowerShell é fixo e lê o texto
de variáveis de ambiente.

Uso: notificar.py "mensagem" [--titulo T] [--backend auto|notify-send|osascript|powershell]
"""
from __future__ import annotations

import argparse
import base64
import os
import shutil
import subprocess
import sys

LIMITE = 240
ENV_TITULO = "CLAUDE_BRAIN_NOTIF_TITULO"
ENV_MSG = "CLAUDE_BRAIN_NOTIF_MSG"

APPLESCRIPT = ("on run argv", "display notification (item 2 of argv) with title (item 1 of argv)", "end run")

# Script fixo: o texto chega por variável de ambiente, nunca concatenado no código.
POWERSHELL = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.Visible = $true
$n.ShowBalloonTip(8000, $env:{ENV_TITULO}, $env:{ENV_MSG}, [System.Windows.Forms.ToolTipIcon]::Info)
Start-Sleep -Seconds 9
$n.Dispose()
"""


def limpar(texto: str) -> str:
    """Uma linha, sem caracteres de controle, tamanho limitado e sem começar com '-'
    (para nenhum programa confundir o texto com uma opção)."""
    texto = "".join(c if c.isprintable() else " " for c in str(texto)).strip()[:LIMITE]
    return ("· " + texto) if texto.startswith("-") else (texto or "(sem mensagem)")


def eh_wsl() -> bool:
    try:
        with open("/proc/version", encoding="utf-8") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def escolher_backend(pedido: str) -> str | None:
    if pedido == "nenhum":
        return None
    if pedido != "auto":
        return pedido
    if sys.platform == "darwin":
        return "osascript"
    if sys.platform == "win32" or eh_wsl():
        return "powershell"
    return "notify-send"


def comando(backend: str, titulo: str, msg: str) -> tuple[list[str], dict[str, str] | None]:
    """argv e ambiente extra de cada backend. O texto nunca entra em código executado."""
    if backend == "notify-send":
        return ["notify-send", "--app-name=claude-brain", "--", titulo, msg], None
    if backend == "osascript":
        argv = ["osascript"]
        for linha in APPLESCRIPT:
            argv += ["-e", linha]
        return argv + [titulo, msg], None
    if backend == "powershell":
        exe = shutil.which("powershell.exe") or shutil.which("pwsh") or "powershell.exe"
        codificado = base64.b64encode(POWERSHELL.encode("utf-16-le")).decode()
        env = {ENV_TITULO: titulo, ENV_MSG: msg}
        if eh_wsl():  # repassa as duas variáveis do Linux para o processo do Windows
            env["WSLENV"] = ":".join(filter(None, [os.environ.get("WSLENV", ""), ENV_TITULO, ENV_MSG]))
        return [exe, "-NoProfile", "-NonInteractive", "-EncodedCommand", codificado], env
    raise ValueError(f"backend desconhecido: {backend!r}")


def notificar(msg: str, titulo: str = "claude-brain", backend: str = "nenhum", log=None) -> bool:
    """Mostra a notificação. Falha nunca derruba quem chamou: devolve False e registra no log."""
    escolhido = escolher_backend(backend)
    if not escolhido:
        return False
    argv, extra = comando(escolhido, limpar(titulo), limpar(msg))
    env = {**os.environ, **extra} if extra else None
    try:
        r = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        if log:
            log(f"notificacao falhou backend={escolhido} erro={type(e).__name__}")
        return False
    if r.returncode != 0 and log:
        log(f"notificacao falhou backend={escolhido} rc={r.returncode}")
    return r.returncode == 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Notificação de desktop do claude-brain.")
    ap.add_argument("mensagem")
    ap.add_argument("--titulo", default="claude-brain")
    ap.add_argument("--backend", default="auto",
                    choices=["auto", "notify-send", "osascript", "powershell"])
    ap.add_argument("--dry-run", action="store_true", help="mostra o comando sem executar")
    a = ap.parse_args(argv)
    if a.dry_run:
        argv_, extra = comando(escolher_backend(a.backend), limpar(a.titulo), limpar(a.mensagem))
        print("DRY-RUN:", argv_, "env extra:", sorted(extra) if extra else [])
        return 0
    return 0 if notificar(a.mensagem, a.titulo, a.backend) else 1


if __name__ == "__main__":
    sys.exit(main())
