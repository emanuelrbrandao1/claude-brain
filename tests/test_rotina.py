import datetime as dt
import json
from unittest import mock

import pytest

import claude_cmd
import rotina

OK = claude_cmd.Resultado(True, 0, "success", "RESULTADO: salvo")
SEGUNDA = dt.datetime(2030, 4, 15, 21, 0)


@pytest.fixture
def execucao(config, tmp_path):
    fonte = tmp_path / "diarios"
    fonte.mkdir()
    (fonte / "d1.md").write_text("# dia 1\n")

    def fabrica(dry_run=False, **extra):
        cfg = config(fontes=[{"nome": "diarios", "caminho": str(fonte)}], **extra)
        return rotina.Execucao(cfg, cfg.log("rotina"), SEGUNDA, dry_run)
    return fabrica


RELATORIO = "analise/relatorios/Relatorio 2030-W15 semanal.md"


def _modelo_escreve(*arquivos, texto="novo\n"):
    """Simula o modelo: o ingest grava os arquivos pedidos (menos o relatório); o pedido de
    relatório grava o relatório, se ele estiver na lista."""
    def falso(cmd, pedido, *, cwd, tempo_max_s, remover_env=()):
        e_relatorio = "relatório semanal" in pedido
        for rel in arquivos:
            if (rel == RELATORIO) == e_relatorio:
                (cwd / rel).parent.mkdir(parents=True, exist_ok=True)
                (cwd / rel).write_text(texto)
        return OK
    return falso


def _pendencias(ex):
    return json.loads((ex.cfg.estado_dir / "rotina-pendencias.json").read_text())


def test_semana_fechada():
    assert rotina.semana_fechada(dt.date(2030, 4, 15)) == dt.date(2030, 4, 8)   # segunda
    assert rotina.semana_fechada(dt.date(2030, 4, 14)) == dt.date(2030, 4, 1)   # domingo: semana ainda aberta


def test_ingest_falha_se_registro_nao_muda(execucao):
    ex = execucao()
    with mock.patch("claude_cmd.rodar", return_value=OK):
        rotina.ingest(ex, [])
    assert ex.falhas == ["ingest: Registro analise.md não mudou"]
    assert not (ex.cfg.estado_dir / "ingest-estado.json").exists()


def test_ingest_ok_grava_estado_e_depois_nao_chama_o_modelo(execucao):
    ex = execucao()
    with mock.patch("claude_cmd.rodar", _modelo_escreve("analise/Registro analise.md")):
        rotina.ingest(ex, [])
    assert ex.falhas == [] and (ex.cfg.estado_dir / "ingest-estado.json").exists()
    with mock.patch("claude_cmd.rodar") as rodar:
        rotina.ingest(ex, [])
    rodar.assert_not_called()


def test_commit_so_dos_arquivos_gerados(execucao):
    ex = execucao(rotina={"commit": True})
    with mock.patch("rotina.subprocess.run") as run:
        run.return_value.returncode = 0
        assert rotina.commitar(ex, ["analise/Registro analise.md"], "msg")
    chamadas = [c.args[0] for c in run.call_args_list]
    add = next(c for c in chamadas if "add" in c)
    commit = next(c for c in chamadas if "commit" in c)
    assert add[-2:] == ["--", "analise/Registro analise.md"]
    assert commit[-2:] == ["--", "analise/Registro analise.md"]
    assert not any("-A" in c for c in chamadas)


def test_fluxo_completo_commit_e_email_do_relatorio(execucao):
    ex = execucao(rotina={"commit": True, "dia_relatorio": 1}, email={"ativo": True})
    modelo = _modelo_escreve("analise/Registro analise.md", RELATORIO)
    with mock.patch("claude_cmd.rodar", modelo), mock.patch("rotina.commitar", return_value=True) as commitar, \
            mock.patch("rotina.enviar", return_value=True) as enviar, mock.patch("rotina.notificar"):
        assert rotina.executar(ex, False, False, False) == 0
    arquivos = commitar.call_args.args[1]
    assert "analise/Registro analise.md" in arquivos and RELATORIO in arquivos
    assert all(a.startswith("analise/") for a in arquivos)
    assert enviar.call_args.args[1] == ex.cfg.vault / RELATORIO
    assert _pendencias(ex) == {"commit": [], "email": []}


def test_segredo_bloqueia_e_deixa_pendente(execucao):
    ex = execucao(rotina={"commit": True}, email={"ativo": True})
    vazamento = "senha: " + "naoconte123"
    with mock.patch("claude_cmd.rodar", _modelo_escreve("analise/Registro analise.md", RELATORIO, texto=vazamento)), \
            mock.patch("rotina.commitar") as commitar, mock.patch("rotina.enviar") as enviar, \
            mock.patch("rotina.notificar") as notif:
        assert rotina.executar(ex, False, False, False) == 1
    commitar.assert_not_called()
    enviar.assert_not_called()
    notif.assert_called_once()
    assert RELATORIO in _pendencias(ex)["email"]


def test_pendencia_e_enviada_na_proxima_execucao_limpa(execucao):
    ex = execucao(email={"ativo": True})
    (ex.cfg.vault / RELATORIO).write_text("# Relatório\n")
    (ex.cfg.estado_dir).mkdir(parents=True, exist_ok=True)
    (ex.cfg.estado_dir / "rotina-pendencias.json").write_text(json.dumps({"commit": [], "email": [RELATORIO]}))
    with mock.patch("claude_cmd.rodar", _modelo_escreve("analise/Registro analise.md")), \
            mock.patch("rotina.enviar", return_value=True) as enviar, mock.patch("rotina.notificar"):
        assert rotina.executar(ex, True, False, False) == 0
    enviar.assert_called_once()
    assert _pendencias(ex)["email"] == []


def test_email_que_falha_fica_pendente(execucao):
    ex = execucao(email={"ativo": True})
    with mock.patch("claude_cmd.rodar", _modelo_escreve("analise/Registro analise.md", RELATORIO)), \
            mock.patch("enviar_email.main", return_value=1), mock.patch("rotina.notificar"):
        assert rotina.executar(ex, False, False, False) == 1
    assert _pendencias(ex)["email"] == [RELATORIO]


def test_relatorio_sai_mesmo_com_ingest_falho_e_fica_pendente(execucao):
    ex = execucao(email={"ativo": True})
    modelo = _modelo_escreve(RELATORIO)  # o ingest não atualiza o registro: falha
    with mock.patch("claude_cmd.rodar", modelo), mock.patch("rotina.enviar") as enviar, \
            mock.patch("rotina.notificar"):
        assert rotina.executar(ex, False, False, False) == 1
    assert (ex.cfg.vault / RELATORIO).exists()
    enviar.assert_not_called()
    assert _pendencias(ex)["email"] == [RELATORIO]


def test_tabela_de_foco_invalida_nao_gera_relatorio(execucao):
    ex = execucao()
    ex.cfg.foco.tabela.parent.mkdir(parents=True, exist_ok=True)
    ex.cfg.foco.tabela.write_text("| Data | Hora | Categoria | Minutos | Fonte |\n|---|---|---|---|---|\n| x | y |\n")
    with mock.patch("claude_cmd.rodar", _modelo_escreve("analise/Registro analise.md")), \
            mock.patch("rotina.relatorio") as relatorio, mock.patch("rotina.notificar"):
        assert rotina.executar(ex, False, False, False) == 1
    relatorio.assert_not_called()


@pytest.mark.parametrize("hoje, dia_relatorio, esperada", [
    (dt.date(2030, 4, 15), 1, dt.date(2030, 4, 8)),   # segunda, dia certo: semana anterior
    (dt.date(2030, 4, 17), 1, dt.date(2030, 4, 8)),   # rotina não rodou na segunda: recupera na quarta
    (dt.date(2030, 4, 15), 3, dt.date(2030, 4, 1)),   # ainda não é quarta: a semana devida é a de antes
    (dt.date(2030, 4, 17), 3, dt.date(2030, 4, 8)),
    (dt.date(2030, 4, 15), 7, dt.date(2030, 4, 1)),
])
def test_semana_devida(hoje, dia_relatorio, esperada):
    assert rotina.semana_devida(hoje, dia_relatorio) == esperada


def test_relatorio_atrasado_e_recuperado(execucao):
    ex = execucao(rotina={"dia_relatorio": 1})
    ex.agora = dt.datetime(2030, 4, 17, 21, 0)  # quarta: a execução de segunda foi perdida
    with mock.patch("claude_cmd.rodar", _modelo_escreve("analise/Registro analise.md", RELATORIO)), \
            mock.patch("rotina.notificar"):
        assert rotina.executar(ex, False, True, False) == 0
    assert (ex.cfg.vault / RELATORIO).exists()


def test_pendencia_de_arquivo_apagado_e_descartada(execucao):
    ex = execucao(rotina={"commit": True}, email={"ativo": True})
    ex.cfg.estado_dir.mkdir(parents=True, exist_ok=True)
    (ex.cfg.estado_dir / "rotina-pendencias.json").write_text(
        json.dumps({"commit": ["analise/sumiu.md"], "email": ["analise/relatorios/sumiu.md"]}))
    with mock.patch("claude_cmd.rodar", _modelo_escreve("analise/Registro analise.md")), \
            mock.patch("rotina.commitar", return_value=True) as commitar, mock.patch("rotina.enviar") as enviar, \
            mock.patch("rotina.notificar"):
        assert rotina.executar(ex, True, False, False) == 0
    assert commitar.call_args.args[1] == ["analise/Registro analise.md"]
    enviar.assert_not_called()
    log = (ex.cfg.log_dir / "rotina.log").read_text()
    assert "pendencia de commit descartada" in log and "pendencia de e-mail descartada" in log


def test_vault_ocupado_pelo_autosave(execucao):
    import comum
    ex = execucao(rotina={"tempo_max_s": 1})
    with comum.trava(comum.trava_do_vault(ex.cfg)), mock.patch("claude_cmd.rodar") as rodar, \
            mock.patch("rotina.notificar") as notif:
        assert rotina.executar(ex, False, False, False) == 1
    rodar.assert_not_called()
    notif.assert_called_once()


def test_escrita_em_caminho_critico_e_falha(execucao):
    ex = execucao()
    modelo = _modelo_escreve("analise/Registro analise.md", ".obsidian/plugins/x/main.js")
    with mock.patch("claude_cmd.rodar", modelo), mock.patch("rotina.notificar"):
        assert rotina.executar(ex, True, True, False) == 1
    assert any(f.startswith("escopo") for f in ex.falhas)


def test_mudanca_alheia_fora_da_analise_e_so_aviso(execucao):
    ex = execucao()
    modelo = _modelo_escreve("analise/Registro analise.md", "projetos/editado-a-mao.md", ".obsidian/graph.json")
    with mock.patch("claude_cmd.rodar", modelo), mock.patch("rotina.notificar") as notif:
        assert rotina.executar(ex, True, True, False) == 0
    notif.assert_not_called()
    assert "AVISO mudou fora de analise/: projetos/editado-a-mao.md" in (ex.cfg.log_dir / "rotina.log").read_text()


def test_excecao_vira_falha_notificada(execucao):
    ex = execucao()
    with mock.patch("rotina.executar", side_effect=KeyError("x")), mock.patch("rotina.notificar") as notif:
        assert rotina.executar_protegido(ex, False, False, False) == 1
    notif.assert_called_once()
    assert "FALHA excecao KeyError" in (ex.cfg.log_dir / "rotina.log").read_text()


def test_dry_run_nao_executa_nada(execucao, capsys):
    ex = execucao(dry_run=True)
    with mock.patch("claude_cmd.subprocess.run") as run:
        assert rotina.executar(ex, so_ingest=False, sem_email=True, forcar_relatorio=True) == 0
    run.assert_not_called()
    saida = capsys.readouterr().out
    assert "--- ingest (DRY-RUN" in saida and "--- relatorio (DRY-RUN" in saida
    assert "d1.md" in saida
    assert not (ex.cfg.estado_dir / "ingest-estado.json").exists()


def test_tempo_total_cobre_lock_ingest_relatorio_e_folga(config, capsys):
    cfg = config(rotina={"tempo_max_s": 600})
    with mock.patch("rotina.carregar_config", return_value=cfg):
        assert rotina.main(["--tempo-total"]) == 0
    assert int(capsys.readouterr().out) == 3 * 600 + rotina.FOLGA_S


def test_sigterm_vira_falha_registrada(execucao):
    ex = execucao()
    with pytest.raises(rotina.Interrompida):
        rotina._ao_receber_sigterm(15, None)
    with mock.patch("rotina.executar", side_effect=rotina.Interrompida), mock.patch("rotina.notificar") as notif:
        assert rotina.executar_protegido(ex, False, False, False) == 1
    notif.assert_called_once()
    assert "FALHA interrompida" in (ex.cfg.log_dir / "rotina.log").read_text()


def test_nota_com_conteudo_executavel_bloqueia_commit(execucao):
    ex = execucao(rotina={"commit": True})
    modelo = _modelo_escreve("analise/Registro analise.md", texto="```dataviewjs\ndv.paragraph(1)\n```\n")
    with mock.patch("claude_cmd.rodar", modelo), mock.patch("rotina.commitar") as commitar, \
            mock.patch("rotina.notificar"):
        assert rotina.executar(ex, True, True, False) == 1
    commitar.assert_not_called()
    assert "bloco-executavel" in (ex.cfg.log_dir / "rotina.log").read_text()


def test_conteudo_preexistente_na_analise_nao_trava_commit(execucao):
    ex = execucao(rotina={"commit": True})
    registro = ex.cfg.analise_pasta / "Registro analise.md"
    registro.write_text("```dataviewjs\ndv.x()\n```\n")  # a pessoa já tinha isso na nota

    def modelo(cmd, pedido, *, cwd, tempo_max_s, remover_env=()):
        with open(registro, "a") as f:
            f.write("## 2030-04-15 · ingest\n- ponto novo\n")
        return OK
    with mock.patch("claude_cmd.rodar", modelo), mock.patch("rotina.commitar", return_value=True) as commitar, \
            mock.patch("rotina.notificar"):
        assert rotina.executar(ex, True, True, False) == 0
    assert commitar.call_args.args[1] == ["analise/Registro analise.md"]


def test_pendencia_e_revarrida_inteira(execucao):
    ex = execucao(rotina={"commit": True})
    pendente = ex.cfg.analise_pasta / "pendente.md"
    pendente.write_text("<% tp.date.now() %>\n")  # bloqueou antes; continua bloqueando
    ex.cfg.estado_dir.mkdir(parents=True, exist_ok=True)
    (ex.cfg.estado_dir / "rotina-pendencias.json").write_text(json.dumps({"commit": ["analise/pendente.md"]}))
    with mock.patch("claude_cmd.rodar", _modelo_escreve("analise/Registro analise.md")), \
            mock.patch("rotina.commitar") as commitar, mock.patch("rotina.notificar"):
        assert rotina.executar(ex, True, True, False) == 1
    commitar.assert_not_called()


def test_caminho_do_lock_vem_da_configuracao(config, tmp_path, capsys):
    cfg = config()
    with mock.patch("rotina.carregar_config", return_value=cfg):
        assert rotina.main(["--caminho-lock"]) == 0
    assert capsys.readouterr().out.strip() == str(cfg.estado_dir / "rotina.lock")


@pytest.mark.parametrize("forma", ["separada", "com-igual"])
def test_rotina_sh_aceita_as_duas_formas_de_config(tmp_path, vault, forma):
    import os
    import subprocess
    import sys

    from conftest import RAIZ
    cfg = tmp_path / "rotina.toml"
    cfg.write_text(f'raizes = ["{tmp_path}"]\nvault = "{vault}"\nestado_dir = "{tmp_path / "estado"}"\n'
                   f'log_dir = "{tmp_path / "logs"}"\n')
    args = ["--config", str(cfg)] if forma == "separada" else [f"--config={cfg}"]
    r = subprocess.run(["bash", str(RAIZ / "scripts" / "rotina.sh"), *args, "--so-ingest", "--dry-run"],
                       env={**os.environ, "CLAUDE_BRAIN_PYTHON": sys.executable}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "estado" / "rotina.lock").exists()
