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
