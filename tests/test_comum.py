import datetime as dt
import stat
from zoneinfo import ZoneInfo

import pytest

from comum import RAIZ_REPO, ErroConfig, Log, gravar_atomico, ler_json, trava


def _modo(p):
    return stat.S_IMODE(p.stat().st_mode)


def test_gravacao_atomica_com_permissao_restrita(tmp_path):
    destino = tmp_path / "estado.json"
    gravar_atomico(destino, "{}")
    gravar_atomico(destino, '{"a": 1}')
    assert ler_json(destino) == {"a": 1} and _modo(destino) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["estado.json"]  # sem temporário sobrando


def test_ler_json_ilegivel_registra(tmp_path):
    (tmp_path / "x.json").write_text("{quebrado")
    eventos = []
    assert ler_json(tmp_path / "x.json", eventos.append) == {}
    assert eventos == ["estado ilegivel x.json: JSONDecodeError"]


def test_log_0600_rotacao_e_fuso(tmp_path):
    log = Log(tmp_path / "logs" / "x.log", max_bytes=100, copias=2, fuso=ZoneInfo("UTC"))
    for i in range(20):
        log(f"evento {i} status=ok")
    arquivos = sorted(p.name for p in (tmp_path / "logs").iterdir())
    assert arquivos == ["x.log", "x.log.1", "x.log.2"]
    assert all(_modo(tmp_path / "logs" / a) == 0o600 for a in arquivos)
    linha = (tmp_path / "logs" / "x.log").read_text().splitlines()[-1]
    assert dt.datetime.strptime(linha.split()[0], "%Y-%m-%dT%H:%M:%S%z").utcoffset() == dt.timedelta(0)


def test_trava_exclusiva(tmp_path):
    with trava(tmp_path / "a.lock"), pytest.raises(TimeoutError), trava(tmp_path / "a.lock", espera_s=0):
        pass
    with trava(tmp_path / "a.lock"):  # solta ao sair
        pass


@pytest.mark.parametrize("alvo, trecho", [("comum.RAIZ_REPO", "pasta do clone"),
                                           ("tempfile.gettempdir", "TMPDIR")])
def test_clone_ou_temporario_com_espaco_e_recusado(config, monkeypatch, tmp_path, alvo, trecho):
    com_espaco = tmp_path / "com espaco"
    if alvo == "comum.RAIZ_REPO":
        monkeypatch.setattr("comum.RAIZ_REPO", com_espaco)
    else:
        monkeypatch.setattr("tempfile.gettempdir", lambda: str(com_espaco))
    with pytest.raises(ErroConfig, match=trecho):
        config()


def test_vault_com_espaco_e_recusado(config, tmp_path):
    (tmp_path / "meu vault").mkdir()
    with pytest.raises(ErroConfig, match="vault"):
        config(vault=str(tmp_path / "meu vault"))


def test_config_valida(config):
    cfg = config()
    assert cfg.foco.alvo_semana_min == 700
    assert cfg.relatorio_pasta.parent == cfg.analise_pasta
    assert [p.name for p in cfg.autosave_escrita] == ["projetos", "conversas-avulsas", "Inicio.md"]


@pytest.mark.parametrize("extra, trecho", [
    ({"analise": {"pasta": "analise", "relatorios": "outros"}}, "dentro de analise.pasta"),
    ({"analise": {"pasta": "../fora"}}, "sem '..'"),
    ({"autosave": {"escrita": [".obsidian"]}}, "oculta"),
    ({"foco": {"alvo_dia_min": [1, 2]}}, "7 inteiros"),
    ({"foco": {"virada_hora": 20}}, "virada_hora"),
    ({"email": {"seguranca": "nenhuma"}}, "seguranca"),
    ({"autosave": {"pastas": ["/"]}}, "autosave.pastas"),
    ({"raizes": ["/"]}, "raizes"),
    ({"raizes": ["/etc"]}, "raizes"),
    ({"timezone": "Lugar/Inexistente"}, "timezone"),
    ({"autosave": {"escrita": ["Conversas soltas"]}}, "espaço por hífen"),
    ({"autosave": {"escrita": ["a,b"]}}, "regra de permissão"),
    ({"analise": {"pasta": "minha analise", "relatorios": "minha analise/rel"}}, "analise.pasta"),
    ({"privacidade": {"termos_arquivo": str(RAIZ_REPO / "termos.txt")}}, "dentro do repositório"),
])
def test_config_invalida(config, extra, trecho):
    with pytest.raises(ErroConfig, match=trecho):
        config(**extra)
