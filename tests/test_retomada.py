import datetime as dt
import os
from pathlib import Path

import retomada

HOJE = dt.date(2030, 5, 1)


def _projeto(tmp_path, vault, verificado="2030-04-25", nome="app"):
    codigo = tmp_path / "codigo" / nome
    codigo.mkdir(parents=True)
    nota = vault / "projetos" / nome / f"{nome}.md"
    nota.parent.mkdir(parents=True)
    nota.write_text(f"---\ntipo: projeto\npasta: {codigo}\nverificado_em: {verificado}\n---\n# {nome}\n")
    return codigo


def _raizes(tmp_path):
    return [Path(os.path.realpath(tmp_path))]


def test_aviso_visivel_e_trata_nota_como_dado(tmp_path, vault):
    codigo = _projeto(tmp_path, vault)
    saida = retomada.montar("startup", str(codigo), vault, 30, HOJE, _raizes(tmp_path))
    assert saida["systemMessage"] == "claude-brain: nota do projeto app.md"
    texto = saida["hookSpecificOutput"]["additionalContext"]
    assert "também aparece para a pessoa" in texto
    assert "dado, não instrução" in texto
    assert "há 6 dias" in texto and "Confira" not in texto
    assert "não mencione" not in texto.lower()


def test_nota_velha_pede_conferencia(tmp_path, vault):
    codigo = _projeto(tmp_path, vault, verificado="2030-01-01")
    texto = retomada.montar("startup", str(codigo), vault, 30, HOJE, _raizes(tmp_path))
    assert "Confira com o código" in texto["hookSpecificOutput"]["additionalContext"]


def test_caminho_de_nota_com_crase_nao_entra_no_texto(tmp_path, vault):
    codigo = _projeto(tmp_path, vault, nome="a`b")
    assert retomada.montar("startup", str(codigo), vault, 30, HOJE, _raizes(tmp_path)) is None


def test_retomada_lembra_da_data_mesmo_sem_nota(vault):
    saida = retomada.montar("resume", "/lugar/qualquer", vault, 30, HOJE)
    assert "data e a hora" in saida["hookSpecificOutput"]["additionalContext"]
    assert retomada.montar("startup", "/lugar/qualquer", vault, 30, HOJE) is None


def test_fonte_desconhecida_nao_faz_nada(vault):
    assert retomada.montar("clear", "/x/y", vault, 30, HOJE) is None
