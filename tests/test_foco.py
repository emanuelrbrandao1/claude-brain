import datetime as dt
import threading

import pytest

import foco
from comum import Foco

CFG = Foco(tabela=None, duracao_min=50, virada_hora=4, alvo_dia_min=(100,) * 7,
           categorias=("leitura", "codigo"))
TABELA = """# Sessões

| Data | Hora | Categoria | Minutos | Fonte |
|---|---|---|---|---|
| 2030-03-04 | 20:00 | leitura | 50 | manual |
| 2030-03-04 | 21:00 | codigo | 50 | claude |
| 2030-03-04 | 01:30 | codigo | 50 | claude |
| 2030-03-05 | 18:00 | ? | 15 | manual |
"""


def test_le_tabela_e_ignora_cabecalho_e_texto():
    sessoes = foco.ler(TABELA, CFG)
    assert [s.minutos for s in sessoes] == [50, 50, 50, 15]
    assert sessoes[3].categoria == "?"


def test_hora_antes_da_virada_e_depois_da_meia_noite_do_mesmo_dia_de_foco():
    depois_da_meia_noite = foco.ler(TABELA, CFG)[2]
    assert depois_da_meia_noite.dia == dt.date(2030, 3, 4)
    assert depois_da_meia_noite.fim == 24 * 60 + 90


def test_totais_por_dia_e_categoria():
    sessoes = foco.ler(TABELA, CFG)
    assert foco.por_dia(sessoes) == {dt.date(2030, 3, 4): 150, dt.date(2030, 3, 5): 15}
    assert foco.por_categoria(sessoes) == {"leitura": 50, "codigo": 100, "?": 15}


@pytest.mark.parametrize("linha, trecho", [
    ("| 2030-03-04 | 20:00 | leitura | 50 |", "5 colunas"),
    ("| 04/03/2030 | 20:00 | leitura | 50 | manual |", "AAAA-MM-DD"),
    ("| 2030-03-04 | 8h | leitura | 50 | manual |", "HH:MM"),
    ("| 2030-03-04 | 20:00 | cozinha | 50 | manual |", "categoria"),
    ("| 2030-03-04 | 20:00 | leitura | muito | manual |", "minutos"),
    ("| 2030-03-04 | 20:00 | leitura | 0 | manual |", "minutos"),
    ("| 2030-03-04 | 20:00 | leitura | 50 | duas palavras |", "fonte"),
])
def test_linha_invalida_tem_erro_claro_com_numero(linha, trecho):
    with pytest.raises(foco.LinhaInvalida) as erro:
        foco.ler(f"| Data | Hora | Categoria | Minutos | Fonte |\n|---|---|---|---|---|\n{linha}\n", CFG)
    assert erro.value.linha == 3
    assert trecho in str(erro.value)


@pytest.mark.parametrize("agora, dia, minuto", [
    (dt.datetime(2030, 3, 5, 0, 40), dt.date(2030, 3, 4), 24 * 60 + 40),
    (dt.datetime(2030, 3, 5, 3, 59), dt.date(2030, 3, 4), 27 * 60 + 59),
    (dt.datetime(2030, 3, 5, 4, 0), dt.date(2030, 3, 5), 4 * 60),
])
def test_virada_do_dia(agora, dia, minuto):
    assert foco.dia_de_foco(agora, 4) == (dia, minuto)


def test_registrar_depois_da_meia_noite_usa_o_dia_de_foco(tmp_path):
    linha = foco.linha_nova(dt.datetime(2030, 3, 5, 0, 40), "codigo", 50, "manual", CFG)
    assert linha == "| 2030-03-04 | 00:40 | codigo | 50 | manual |"
    tabela = tmp_path / "t.md"
    foco.registrar(tabela, linha, tmp_path / "foco.lock")
    foco.registrar(tabela, foco.linha_nova(dt.datetime(2030, 3, 5, 9, 0), "leitura", 15, "manual", CFG),
                   tmp_path / "foco.lock")
    assert [(s.dia, s.minutos) for s in foco.ler(tabela.read_text(), CFG)] == [
        (dt.date(2030, 3, 4), 50), (dt.date(2030, 3, 5), 15)]


def test_registrar_em_paralelo_nao_perde_linha(tmp_path):
    tabela, lock = tmp_path / "t.md", tmp_path / "foco.lock"
    linhas = [foco.linha_nova(dt.datetime(2030, 3, 5, 9, i), "leitura", 10, "manual", CFG) for i in range(8)]
    threads = [threading.Thread(target=foco.registrar, args=(tabela, li, lock)) for li in linhas]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(foco.ler(tabela.read_text(), CFG)) == 8


def test_registrar_recusa_categoria_desconhecida():
    with pytest.raises(foco.LinhaInvalida):
        foco.linha_nova(dt.datetime(2030, 3, 5, 9, 0), "cozinha", 50, "manual", CFG)


def _sessoes(minutos_por_dia: dict) -> list[foco.Sessao]:
    out = []
    for dia, minutos in minutos_por_dia.items():
        for k in range(minutos // 50):
            out.append(foco.Sessao(dia, 20 * 60 + 50 * k, "leitura", 50, "manual"))
    return out


def test_melhor_ignora_o_periodo_atual():
    total = {dt.date(2030, 3, 4): 100, dt.date(2030, 3, 11): 300, dt.date(2030, 3, 12): 50}
    assert foco.melhor(total, foco.semana, foco.semana(dt.date(2030, 3, 11))) == ((2030, 10), 100)
    assert foco.melhor(total, foco.mes, (2030, 3)) == (None, 0)


def test_ritmo_alvo_atingido_e_novo_melhor_dia():
    sessoes = _sessoes({dt.date(2030, 3, 4): 100, dt.date(2030, 3, 5): 200})
    linhas = foco.linhas_ritmo(sessoes, dt.datetime(2030, 3, 5, 23, 59), CFG)
    assert linhas[0].startswith("Hoje (ter 2030-03-05)") and "alvo atingido" in linhas[0]
    assert any(li.startswith("[perto] Melhor dia") and "novo melhor dia" in li for li in linhas)


def test_ritmo_ignora_o_que_vem_depois_de_agora():
    sessoes = _sessoes({dt.date(2030, 3, 5): 150})
    linhas = foco.linhas_ritmo(sessoes, dt.datetime(2030, 3, 5, 20, 30), CFG)
    assert "0.8 h de 1.7 h" in linhas[0]  # só a primeira sessão (fim 20:00) já aconteceu


def test_ritmo_sem_historico_nao_inventa_melhor_marca():
    linhas = foco.linhas_ritmo([], dt.datetime(2030, 3, 5, 10, 0), CFG)
    assert len(linhas) == 2 and not any("Melhor" in li for li in linhas)
