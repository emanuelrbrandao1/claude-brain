import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import claude_cmd
from claude_cmd import ErroComando, Permissoes, interpretar_saida, montar_comando


def _valores(cmd, flag):
    """Valores de uma opção variádica: tudo depois dela até a próxima opção."""
    i = cmd.index(flag) + 1
    fim = next((j for j in range(i, len(cmd)) if cmd[j].startswith("--")), len(cmd))
    return cmd[i:fim]


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    (v / "projetos").mkdir(parents=True)
    (v / "Inicio.md").write_text("# início\n")
    return v


@pytest.fixture
def cmd(tmp_path, vault):
    perm = Permissoes(escrita=(vault / "projetos", vault / "Inicio.md"), leitura=(vault, tmp_path / "skill"))
    return montar_comando("claude", perm, vault, resume="id-da-sessao")


def test_so_read_edit_write(cmd):
    assert _valores(cmd, "--tools") == ["Read,Edit,Write"]
    for r in _valores(cmd, "--allowedTools"):
        assert re.match(r"^(Read|Edit)\(//.+\)$", r), r


def test_escrita_so_nos_caminhos_previstos(cmd, vault):
    edicao = [r for r in _valores(cmd, "--allowedTools") if r.startswith("Edit(")]
    assert edicao == [f"Edit(/{vault}/projetos/**)", f"Edit(/{vault}/Inicio.md)"]
    assert f"Edit(/{vault}/**)" not in _valores(cmd, "--allowedTools")


def test_pastas_ocultas_e_instrucoes_de_agente_negadas(cmd, vault):
    negadas = _valores(cmd, "--disallowedTools")
    for padrao in (".*/**", "**/.*", "**/.*/**", "**/CLAUDE.md", "**/CLAUDE.local.md", "**/AGENTS.md",
                   "**/.claude/**"):
        assert f"Edit(/{vault}/{padrao})" in negadas
    assert f"Read(/{vault}/.obsidian/**)" in negadas and f"Read(/{vault}/.git/**)" in negadas


def test_credenciais_negadas_em_cada_pasta_liberada(cmd, tmp_path, vault):
    negadas = _valores(cmd, "--disallowedTools")
    for pasta in (vault, vault / "projetos", tmp_path / "skill"):
        for padrao in ("**/.env*", "**/.envrc", "**/.netrc", "**/.pgpass", "**/id_*", "**/*.pem", "**/*.key"):
            assert f"Read(/{pasta}/{padrao})" in negadas
    assert not any(n.startswith("Read(**") for n in negadas)  # nada relativo
    assert "Read(~/.config/**)" in negadas and "Read(~/.claude/**)" in negadas


def test_bash_e_rede_negados(cmd):
    negadas = _valores(cmd, "--disallowedTools")
    for ferramenta in ("Bash", "WebFetch", "WebSearch", "Agent", "NotebookEdit"):
        assert ferramenta in negadas
    assert not any("Bash" in r for r in _valores(cmd, "--allowedTools"))


def test_isolamento_e_modo_sem_pergunta(cmd):
    for flag in ("--restricted", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert json.loads(cmd[cmd.index("--settings") + 1]) == {"disableAllHooks": True}
    assert not any("dangerously" in a or "bypass" in a for a in cmd)


def test_resume_cria_copia_sem_snapshot_e_pedido_nao_vai_no_argv(cmd):
    assert cmd[cmd.index("--resume") + 1] == "id-da-sessao" and "--fork-session" in cmd
    assert cmd[cmd.index("--system-prompt-snapshot") + 1] == "off"
    assert claude_cmd.SENTINELA not in " ".join(cmd)


def test_pedido_repete_o_aviso():
    pedido = claude_cmd.pedido_com_aviso("faça X")
    assert pedido.startswith(claude_cmd.SENTINELA) and claude_cmd.AVISO in pedido and pedido.endswith("faça X")


def test_add_dir_so_para_pastas_fora_do_cwd(tmp_path, vault):
    perm = Permissoes(escrita=(vault / "projetos",), leitura=(vault, tmp_path / "fonte"))
    assert _valores(montar_comando("claude", perm, vault), "--add-dir") == [str(tmp_path / "fonte")]


@pytest.mark.parametrize("pasta", ["relativa/pasta", "/curta", "/tmp/com*glob", "/tmp/com(parentese)",
                                   "/tmp/barra\\invertida", "/tmp/com espaco", "/tmp/com,virgula"])
def test_recusa_caminho_que_a_sintaxe_de_permissao_nao_aceita(pasta):
    with pytest.raises(ErroComando):
        montar_comando("claude", Permissoes(escrita=(Path(pasta),)), Path("/tmp/x/y"))


def test_interpreta_saida_json():
    ok = interpretar_saida(0, json.dumps({"type": "result", "subtype": "success", "is_error": False,
                                          "result": "feito\nRESULTADO: nada a salvar", "num_turns": 3}))
    assert ok.ok and ok.nada_a_salvar and ok.turnos == 3
    erro = interpretar_saida(0, json.dumps({"subtype": "error_max_turns", "is_error": True}))
    assert not erro.ok and erro.subtipo == "error_max_turns"
    assert interpretar_saida(1, "lixo").subtipo == "saida-ilegivel"


REMOVIDAS = ("CLAUDECODE", "MINHA_SMTP_SENHA", "GITHUB_TOKEN", "QUALQUER_SECRET", "VAR_ESCOLHIDA",
             "DB_PASS", "GITLAB_PAT", "SERVICO_CREDENTIAL", "DATABASE_URL", "APP_DATABASE_URL", "OPENAI_APIKEY",
             "MY_PASSWORD", "GITHUB_TOKENS", "NPM_TOKENS")
MANTIDAS = ("ANTHROPIC_API_KEY", "ANTHROPIC_FOUNDRY_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "PATH", "MANPATH",
            "PYTHON_KEYRING_BACKEND", "HOME", "LANG", "GOOGLE_APPLICATION_CREDENTIALS", "MAX_THINKING_TOKENS",
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS", "MAX_MCP_OUTPUT_TOKENS", "CLAUDE_CODE_CLIENT_CERT",
            "CLAUDE_CODE_CLIENT_KEY",
            "CLAUDE_CODE_CLIENT_KEY_PASSPHRASE")


def test_ambiente_sem_segredos_mas_com_autenticacao(monkeypatch):
    for nome in REMOVIDAS + MANTIDAS:
        monkeypatch.setenv(nome, "x")
    env = claude_cmd.ambiente_automatico(remover=("VAR_ESCOLHIDA",))
    for nome in REMOVIDAS:
        assert nome not in env, nome
    for nome in MANTIDAS:
        assert env.get(nome) == "x", nome
    assert env["CLAUDE_BRAIN_SEM_AUTOSAVE"] == "1" and env["CLAUDE_BRAIN_SEM_RETOMADA"] == "1"


@pytest.mark.skipif(not shutil.which("claude"), reason="Claude Code não instalado")
def test_flags_existem_no_help(cmd):
    ajuda = subprocess.run(["claude", "--help"], capture_output=True, text=True, timeout=60).stdout
    for flag in (a for a in cmd if a.startswith("--")):
        assert flag in ajuda, f"{flag} não aparece em `claude --help`"


# ---------------------------------------------------------------- grupo de processos no tempo esgotado

FILHO_COM_NETO = """
import subprocess, sys, time
neto = subprocess.Popen(["sleep", "30"])
with open(sys.argv[1], "w") as f:
    f.write(str(neto.pid))
time.sleep(30)
"""


def _vivo(pid: int) -> bool:
    try:
        estado = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, IndexError):
        return False
    return estado != "Z"


def _esperar_morrer(pid: int, limite_s: float = 5) -> bool:
    import time
    fim = time.monotonic() + limite_s
    while time.monotonic() < fim:
        if not _vivo(pid):
            return True
        time.sleep(0.05)
    return False


def _neto(tmp_path):
    import sys
    script = tmp_path / "filho.py"
    script.write_text(FILHO_COM_NETO)
    return [sys.executable, str(script), str(tmp_path / "neto.pid")], tmp_path / "neto.pid"


@pytest.mark.skipif(not Path("/proc/self/stat").exists() or not shutil.which("sleep"), reason="precisa de /proc")
def test_tempo_esgotado_mata_o_neto_tambem(tmp_path):
    cmd, arq_pid = _neto(tmp_path)
    with pytest.raises(subprocess.TimeoutExpired):
        claude_cmd.rodar_em_grupo(cmd, tempo_max_s=1.5)
    assert _esperar_morrer(int(arq_pid.read_text()))


@pytest.mark.skipif(not Path("/proc/self/stat").exists() or not shutil.which("sleep"), reason="precisa de /proc")
def test_rodar_com_tempo_esgotado_nao_deixa_claude_orfao(tmp_path):
    cmd, arq_pid = _neto(tmp_path)
    r = claude_cmd.rodar(cmd, "pedido", cwd=tmp_path, tempo_max_s=1.5)
    assert r.subtipo == "tempo-esgotado" and not r.ok
    assert _esperar_morrer(int(arq_pid.read_text()))


@pytest.mark.skipif(not Path("/proc/self/stat").exists() or not shutil.which("sleep"), reason="precisa de /proc")
def test_excecao_durante_a_espera_tambem_mata_o_grupo(tmp_path, monkeypatch):
    """Ex.: o SIGTERM da rotina vira exceção enquanto o claude roda."""
    import time
    cmd, arq_pid = _neto(tmp_path)
    original = subprocess.Popen.communicate

    def interrompida(self, *args, **kwargs):
        if kwargs.get("timeout") != 30:          # só a espera principal é interrompida
            return original(self, *args, **kwargs)
        while not arq_pid.exists():
            time.sleep(0.05)
        raise KeyboardInterrupt
    monkeypatch.setattr(subprocess.Popen, "communicate", interrompida)
    with pytest.raises(KeyboardInterrupt):
        claude_cmd.rodar_em_grupo(cmd, tempo_max_s=30)
    assert _esperar_morrer(int(arq_pid.read_text()))


# ---------------------------------------------------------------- dois níveis: rotina → autosave.py → claude

NETO = "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(47)"
MEIO = """
import sys
sys.path.insert(0, {scripts!r})
import claude_cmd
if {com_handler}:
    claude_cmd.instalar_sigterm()
claude_cmd.rodar_em_grupo([sys.executable, "-c", {neto!r}, sys.argv[1]], entrada="x", tempo_max_s=100)
"""
FORA = """
import sys
sys.path.insert(0, {scripts!r})
import claude_cmd
claude_cmd.instalar_sigterm()
claude_cmd.rodar_em_grupo([sys.executable, sys.argv[1], sys.argv[2]], tempo_max_s=100)
"""
PRECISA_PROC = pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="precisa de /proc")


def _meio(tmp_path, com_handler=True):
    import sys

    from conftest import RAIZ
    script = tmp_path / "meio.py"
    script.write_text(MEIO.format(scripts=str(RAIZ / "scripts"), neto=NETO, com_handler=com_handler))
    return [sys.executable, str(script), str(tmp_path / "neto.pid")], tmp_path / "neto.pid"


def _esperar_arquivo(p: Path, limite_s: float = 10) -> None:
    import time
    fim = time.monotonic() + limite_s
    while not p.exists() or not p.read_text():
        assert time.monotonic() < fim, "o neto não começou"
        time.sleep(0.05)


@pytest.fixture
def espera_curta(monkeypatch):
    monkeypatch.setattr(claude_cmd, "ESPERA_TERM_S", 1.0)
    monkeypatch.setenv("CLAUDE_BRAIN_ESPERA_TERM_S", "1")   # para os processos filhos


@PRECISA_PROC
def test_dois_niveis_tempo_esgotado_externo_mata_o_neto(tmp_path, espera_curta):
    cmd, arq_pid = _meio(tmp_path)
    with pytest.raises(subprocess.TimeoutExpired):
        claude_cmd.rodar_em_grupo(cmd, tempo_max_s=2)
    assert _esperar_morrer(int(arq_pid.read_text()))


@PRECISA_PROC
def test_dois_niveis_sigterm_no_externo_mata_o_neto(tmp_path, espera_curta):
    import os
    import signal
    import sys

    from conftest import RAIZ
    meio, arq_pid = _meio(tmp_path)
    fora = tmp_path / "fora.py"
    fora.write_text(FORA.format(scripts=str(RAIZ / "scripts")))
    proc = subprocess.Popen([sys.executable, str(fora), meio[1], meio[2]], start_new_session=True)
    _esperar_arquivo(arq_pid)
    os.kill(proc.pid, signal.SIGTERM)                      # o `timeout` do rotina.sh faz isto
    assert proc.wait(timeout=15) != 0
    assert _esperar_morrer(int(arq_pid.read_text()))


@PRECISA_PROC
def test_sem_o_handler_no_meio_o_neto_sobraria(tmp_path, espera_curta):
    """Controle: é o handler de SIGTERM do nível do meio que alcança o neto (que está em outro grupo)."""
    import os
    import signal
    cmd, arq_pid = _meio(tmp_path, com_handler=False)
    with pytest.raises(subprocess.TimeoutExpired):
        claude_cmd.rodar_em_grupo(cmd, tempo_max_s=2)
    pid = int(arq_pid.read_text())
    try:
        assert not _esperar_morrer(pid, limite_s=1.5)
    finally:
        os.kill(pid, signal.SIGKILL)


def test_encerrado_nao_e_engolido_por_except_exception():
    assert not issubclass(claude_cmd.Encerrado, Exception)


FOLHA_TEIMOSA = "trap '' TERM; echo $$ > {pid}; exec sleep 47"   # ignora SIGTERM (o exec herda o ignore)
MEIO_COM_RODAR = """
import sys
sys.path.insert(0, {scripts!r})
import claude_cmd
claude_cmd.instalar_sigterm()
claude_cmd.rodar(["bash", "-c", {folha!r}], "pedido", cwd={cwd!r}, tempo_max_s=100)
"""


@PRECISA_PROC
@pytest.mark.skipif(not shutil.which("bash"), reason="precisa de bash")
def test_tres_niveis_por_sigterm_com_folha_que_ignora_sigterm(tmp_path, espera_curta):
    """fora (rotina) → meio (autosave.py, via claude_cmd.rodar) → folha (claude) que ignora SIGTERM:
    a espera da folha é menor que a do meio, então o SIGKILL dela chega antes do de cima."""
    import os
    import signal
    import sys

    from conftest import RAIZ
    arq_pid = tmp_path / "folha.pid"
    meio = tmp_path / "meio.py"
    meio.write_text(MEIO_COM_RODAR.format(scripts=str(RAIZ / "scripts"), cwd=str(tmp_path),
                                          folha=FOLHA_TEIMOSA.format(pid=arq_pid)))
    fora = tmp_path / "fora.py"
    fora.write_text(FORA.format(scripts=str(RAIZ / "scripts")))
    proc = subprocess.Popen([sys.executable, str(fora), str(meio), "nada"], start_new_session=True)
    _esperar_arquivo(arq_pid)
    os.kill(proc.pid, signal.SIGTERM)
    assert proc.wait(timeout=15) != 0
    assert _esperar_morrer(int(arq_pid.read_text()))


def test_espera_da_folha_e_menor_que_a_de_qualquer_nivel_acima():
    assert claude_cmd.ESPERA_FOLHA_S < claude_cmd.ESPERA_TERM_S / 2
