import os
from pathlib import Path

import pytest

from comum import validar_pasta
from vault import classificar, critico, links_inseguros, mudancas, notas_que_citam, projeto_pela_pasta, retrato


@pytest.fixture
def raizes(tmp_path):
    return [Path(os.path.realpath(tmp_path))]


@pytest.mark.parametrize("valor", ["", "/", "~", "relativo/pasta", "/etc/ssh", "/usr/lib", "/mnt/c"])
def test_validar_pasta_rejeita_amplas_de_sistema_e_relativas(valor):
    with pytest.raises(ValueError):
        validar_pasta(valor)


def test_validar_pasta_padrao_e_dentro_da_home():
    with pytest.raises(ValueError):
        validar_pasta(str(Path.home()))
    with pytest.raises(ValueError):
        validar_pasta(str(Path.home().parent / "outra-pessoa"), existir=False)


def test_validar_pasta_exige_raiz_e_existencia(tmp_path, raizes):
    (tmp_path / "ok").mkdir()
    assert validar_pasta(tmp_path / "ok", raizes) == raizes[0] / "ok"
    with pytest.raises(ValueError, match="raízes"):
        validar_pasta(tmp_path, raizes)                        # a própria raiz é ampla demais
    with pytest.raises(ValueError, match="não existe"):
        validar_pasta(tmp_path / "nao-existe", raizes)


def test_validar_pasta_segue_link_para_fora_da_raiz(tmp_path, raizes):
    os.symlink("/etc", tmp_path / "atalho")
    with pytest.raises(ValueError, match="sistema"):
        validar_pasta(tmp_path / "atalho", raizes)


def _nota(vault: Path, nome: str, pasta: str, tipo: str = "projeto") -> Path:
    arq = vault / "projetos" / nome / f"{nome}.md"
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(f"---\ntipo: {tipo}\npasta: {pasta}\n---\n# {nome}\n")
    return arq


def test_projeto_pela_pasta_mais_especifica_vence(tmp_path, vault, raizes):
    geral = tmp_path / "codigo"
    especifico = geral / "app"
    (especifico / "src").mkdir(parents=True)
    _nota(vault, "geral", str(geral))
    nota = _nota(vault, "app", str(especifico))
    assert projeto_pela_pasta(vault, str(especifico / "src"), raizes) == nota


def test_pasta_ampla_na_nota_e_ignorada(vault, raizes):
    _nota(vault, "tudo", "/")
    _nota(vault, "casa", "~")
    _nota(vault, "sistema", "/etc")
    assert projeto_pela_pasta(vault, str(vault), raizes) is None
    assert projeto_pela_pasta(vault, "/etc/ssh", raizes) is None


def test_cwd_relativo_nao_casa(vault, raizes):
    assert projeto_pela_pasta(vault, "projetos", raizes) is None


def test_notas_que_citam_pelo_marcador(vault):
    reg = vault / "Registro x.md"
    reg.write_text("## 2030-01-01 · a\n%% sessões: id-a, id-b %%\n")
    (vault / "outra.md").write_text("menciona id-b fora do marcador\n")
    assert notas_que_citam(vault, "id-b") == [reg]


def test_retrato_ve_ocultos_qualquer_extensao_e_remocao(vault):
    (vault / "a.md").write_text("1")
    (vault / "velho.txt").write_text("x")
    antes = retrato(vault)
    (vault / "a.md").write_text("22")
    (vault / ".obsidian" / "plugins" / "x").mkdir(parents=True)
    (vault / ".obsidian" / "plugins" / "x" / "main.js").write_text("codigo()")
    (vault / "velho.txt").unlink()
    assert mudancas(antes, retrato(vault)) == [".obsidian/plugins/x/main.js", "a.md", "velho.txt"]


@pytest.mark.parametrize("rel", [
    ".obsidian/plugins/x/main.js", ".obsidian/plugins/x/manifest.json", ".obsidian/snippets/a.css",
    ".obsidian/community-plugins.json", ".git/hooks/pre-commit", ".git/config",
    ".obsidian/plugins/obsidian-shellcommands/data.json", ".obsidian/plugins/templater-obsidian/data.json",
    ".obsidian/plugins/dataview/data.json",
    "CLAUDE.md", "projetos/app/CLAUDE.md", "projetos/app/AGENTS.md", "projetos/app/CLAUDE.local.md",
    "projetos/.claude/settings.json",
])
def test_caminhos_que_executam_ou_instruem_sao_criticos(rel):
    assert critico(rel)


@pytest.mark.parametrize("rel", [
    ".obsidian/plugins/x/data.json", ".obsidian/graph.json", ".trash/velha.md", ".git/index",
    ".git/objects/ab/cdef", "projetos/app/app.md",
])
def test_mudancas_comuns_de_outros_programas_nao_sao_criticas(rel):
    assert not critico(rel)


def test_classificar(vault):
    permitidos = [vault / "projetos", vault / "Inicio.md"]
    mudados = ["projetos/a/a.md", "Inicio.md", "analise/x.md", ".obsidian/community-plugins.json",
               "projetos/.escondido.md", ".obsidian/workspace.json", ".obsidian/plugins/p/data.json",
               "projetos/a/CLAUDE.md"]
    c = classificar(mudados, vault, permitidos, ignorar=[".obsidian/workspace.json"])
    assert c.permitidos == ["projetos/a/a.md", "Inicio.md"]
    assert c.criticos == [".obsidian/community-plugins.json", "projetos/a/CLAUDE.md"]
    assert c.avisos == ["analise/x.md", "projetos/.escondido.md", ".obsidian/plugins/p/data.json"]


def test_links_inseguros(tmp_path, vault):
    projetos = vault / "projetos"
    (projetos / "dentro").mkdir()
    (vault / ".obsidian").mkdir()
    (vault / "analise" / "x").mkdir()
    os.symlink(tmp_path, projetos / "fuga")                       # fora do vault
    os.symlink(vault / ".obsidian", projetos / "oculto")         # destino oculto
    os.symlink(vault / "analise" / "x", projetos / "outra-area")  # fora dos caminhos de escrita
    os.symlink(projetos / "dentro", projetos / "atalho-interno")  # ok: dentro do permitido
    assert links_inseguros([projetos], vault) == sorted(
        [projetos / "fuga", projetos / "oculto", projetos / "outra-area"])


def test_caminho_de_escrita_que_e_link_para_fora(tmp_path, vault):
    (tmp_path / "longe").mkdir()
    os.symlink(tmp_path / "longe", vault / "notas")
    assert links_inseguros([vault / "notas"], vault) == [vault / "notas"]
