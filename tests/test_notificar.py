import base64
from unittest import mock

import pytest

import notificar

MALICIOSA = "'; rm -rf ~; echo \"$(id)\" `whoami` & end tell -- fim"


def _executado(backend, msg, titulo="t"):
    with mock.patch("notificar.subprocess.run") as run:
        run.return_value.returncode = 0
        assert notificar.notificar(msg, titulo, backend=backend)
    (argv,), kwargs = run.call_args
    assert "shell" not in kwargs
    return argv, kwargs.get("env")


def test_desligado_por_padrao_nao_executa_nada():
    with mock.patch("notificar.subprocess.run") as run:
        assert notificar.notificar("oi") is False
    run.assert_not_called()


def test_notify_send_texto_depois_de_duplo_traco():
    argv, _ = _executado("notify-send", MALICIOSA)
    assert argv[0] == "notify-send" and argv[-3] == "--"
    assert argv[-1] == notificar.limpar(MALICIOSA)


def test_osascript_script_fixo_e_texto_em_argv():
    argv, _ = _executado("osascript", MALICIOSA)
    scripts = [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]
    assert tuple(scripts) == notificar.APPLESCRIPT
    assert argv[-1] == notificar.limpar(MALICIOSA)
    assert not any(MALICIOSA in s for s in scripts)


def test_powershell_le_texto_do_ambiente():
    argv1, env1 = _executado("powershell", MALICIOSA)
    argv2, _ = _executado("powershell", "outra mensagem")
    assert argv1 == argv2  # o código executado não depende do texto
    script = base64.b64decode(argv1[argv1.index("-EncodedCommand") + 1]).decode("utf-16-le")
    assert "rm -rf" not in script and "$env:CLAUDE_BRAIN_NOTIF_MSG" in script
    assert env1["CLAUDE_BRAIN_NOTIF_MSG"] == notificar.limpar(MALICIOSA)


@pytest.mark.parametrize("bruto, esperado", [
    ("-e do shell script", "· -e do shell script"),
    ("linha1\nlinha2\x07", "linha1 linha2"),
    ("", "(sem mensagem)"),
])
def test_limpar(bruto, esperado):
    assert notificar.limpar(bruto) == esperado


def test_falha_do_backend_nao_propaga():
    log = mock.Mock()
    with mock.patch("notificar.subprocess.run", side_effect=FileNotFoundError):
        assert notificar.notificar("x", backend="notify-send", log=log) is False
    assert "falhou" in log.call_args.args[0]
