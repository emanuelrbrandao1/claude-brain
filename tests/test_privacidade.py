from pathlib import Path

import pytest

import privacidade

# Tokens montados em tempo de execução: o repositório não guarda nada com formato de segredo.
FALSOS = {
    "chave-aws": "AKIA" + "Q" * 16,
    "token-github": "ghp_" + "a1" * 18,
    "token-gitlab": "glpat-" + "c" * 20,
    "chave-google": "AIza" + "B" * 35,
    "chave-api-sk": "sk-" + "x" * 30,
    "chave-stripe": "sk_" + "live_" + "a" * 16,
    "token-slack": "xoxb-" + "1" * 12,
    "jwt": "eyJ" + "a" * 10 + ".eyJ" + "b" * 10 + "." + "c" * 12,
    "chave-privada": "-----BEGIN " + "RSA PRIVATE KEY-----",
    "senha-atribuida": "senha = " + "naoconte123",
    "email": "alguem@" + "provedor.test",
}


@pytest.mark.parametrize("tipo, texto", FALSOS.items())
def test_detecta_cada_tipo(tipo, texto):
    achados = privacidade.varrer_texto(f"linha 1\nantes {texto} depois\n")
    assert [(a.linha, a.tipo) for a in achados] == [(2, tipo)]


# Formas que escapavam da primeira versão (\b depois de _, valor entre aspas com espaço, tabela...).
CONTORNOS = [
    "password = " + '"frase longa com espacos"',
    "senha: " + "`abre te sesamo`",
    "token: " + "'valor com espaco'",
    "| senha | " + "hunter22" + " |",
    "a senha é " + "minhasenha123",
    "aws_secret_access_key=" + "wJalrXUtnFEMIK7MDENG",
    "DB_PASSWORD=" + "supersecreto",
    "client_secret => " + "abcdef123456",
    "chave: AIza" + "Z" * 35,
    "rk_" + "test_" + "b" * 16,
    "x_" + "AKIA" + "Q" * 16,
    "postgres://app:" + "s3nha" + "@db.exemplo.test/app",
]


@pytest.mark.parametrize("texto", CONTORNOS)
def test_formas_de_contorno_sao_pegas(texto):
    assert privacidade.varrer_texto(texto), texto


def test_achado_sai_mascarado():
    achado = privacidade.varrer_texto(FALSOS["token-github"])[0]
    assert FALSOS["token-github"] not in str(achado) and achado.trecho.endswith("…")


PROSA = [
    "A senha é armazenada no keyring do sistema.",
    "O token é renovado a cada hora.",
    "token: nenhum",
    "senha: variável de ambiente",
    "senha = nenhuma",
    "| senha | definida pelo administrador |",
]


@pytest.mark.parametrize("texto", PROSA)
def test_prosa_sobre_senha_nao_e_segredo(texto):
    assert privacidade.varrer_texto(texto) == [], texto


@pytest.mark.parametrize("texto", [
    "token: " + "abc123def",            # dígito
    "senha: " + "s3gr3d0!",             # símbolo
    "API_KEY=" + "qualquercoisa",       # atribuição dispensa dígito
    "senha: " + '"so letras aqui"',     # entre aspas sempre conta
])
def test_valor_com_cara_de_segredo_continua_pego(texto):
    assert [a.tipo for a in privacidade.varrer_texto(texto)] == ["senha-atribuida"]


@pytest.mark.parametrize("linha", [
    "a" * 3999, "senha" * 799, "token_" * 666, "a." * 1999, "x@" * 1999, "password" * 499 + "=",
    "aws_" * 999, "senha: " + "|" * 3990,
])
def test_linhas_hostis_terminam_rapido(linha):
    import time
    inicio = time.perf_counter()
    privacidade.varrer_texto(linha)
    assert time.perf_counter() - inicio < 0.5


@pytest.mark.parametrize("linha, tipo", [
    ("x" * 5000 + " " + FALSOS["token-github"] + " " + "y" * 100, "token-github"),
    ("password = " + "hunter2hunter9 " + "z" * 4100, "senha-atribuida"),
    ("z" * 4100 + " password = " + "hunter2hunter9", "senha-atribuida"),
    ("z" * 3790 + " senha = " + "abc123xyz789 " + "z" * 400, "senha-atribuida"),  # na emenda de duas janelas
    ("q" * 5000 + " fulano@" + "provedor.test " + "q" * 100, "email"),
])
def test_linha_longa_e_varrida_por_inteiro(linha, tipo):
    assert [a.tipo for a in privacidade.varrer_texto(linha)] == [tipo]


@pytest.mark.parametrize("borda", [privacidade.JANELA, privacidade.JANELA - privacidade.SOBREPOSICAO,
                                   2 * privacidade.JANELA - privacidade.SOBREPOSICAO])
@pytest.mark.parametrize("deslocamento", range(-5, 6))
@pytest.mark.parametrize("segredo, tipo, permitidos", [
    ("senha: " + "hunter2hunter9", "senha-atribuida", ()),            # "senha: hunter" cortado seria prosa
    ("password = " + "hunter2hunter9", "senha-atribuida", ()),
    ("a@exemplo.test" + ".evil.com", "email", ("@exemplo.test",)),   # cortado seria e-mail permitido
])
def test_segredo_na_borda_da_janela_nao_escapa(borda, deslocamento, segredo, tipo, permitidos):
    # o meio do segredo cai exatamente na borda (±5 caracteres)
    antes = borda + deslocamento - len(segredo) // 2
    linha = "z" * antes + " " + segredo + " " + "z" * 9000
    achados = privacidade.bloqueantes(privacidade.varrer_texto(linha, emails_permitidos=permitidos))
    assert [a.tipo for a in achados] == [tipo]


@pytest.mark.parametrize("deslocamento", range(-5, 6))
def test_email_permitido_na_borda_continua_permitido(deslocamento):
    antes = privacidade.JANELA + deslocamento - 7
    linha = "z" * antes + " a@" + "exemplo.test " + "z" * 9000
    assert privacidade.varrer_texto(linha, emails_permitidos=("@exemplo.test",)) == []


@pytest.mark.parametrize("prefixo, pego", [(41, True), (80, True), (81, False)])
def test_nome_de_senha_com_prefixo_longo(prefixo, pego):
    chave = "c" * (prefixo - 1) + "_" + "password"  # prefixo = tudo antes do nome, "_" incluso
    achados = privacidade.varrer_texto(chave + " = " + "hunter2hunter9")
    assert bool(achados) is pego


def test_termo_do_usuario_em_linha_longa():
    import re
    achados = privacidade.varrer_texto("w" * 7000 + " codinome " + "w" * 10, termos=[re.compile("codinome")])
    assert [a.tipo for a in achados] == ["termo-proibido"]


@pytest.mark.parametrize("linha", [
    "x" * 100_000, "eyJ" * 33_333, "sk-" * 33_333, "a." * 50_000, "ghp_" * 25_000, "a://b:" * 16_000,
    "glpat-" * 16_000, "<%" * 50_000, "-----BEGIN " * 9_000, "senha: " * 14_000, "a-" * 50_000, "a_" * 50_000,
    ("a." * 31 + "@") * 1_500, "password=" * 11_000,
])
def test_linha_de_100k_hostil_termina_rapido(linha):
    import time
    inicio = time.perf_counter()
    privacidade.varrer_texto(linha)
    assert time.perf_counter() - inicio < 0.5




EXECUTAVEIS = [
    ("```dataviewjs\ndv.paragraph(1)\n```", "bloco-executavel"),
    ("> ```dataviewjs", "bloco-executavel"),                 # dentro de citação/callout
    ("> > ```dataviewjs", "bloco-executavel"),
    (">```dataviewjs", "bloco-executavel"),
    ("> [!note]\n> ```dataviewjs\n> dv.x()\n> ```", "bloco-executavel"),
    ("- ```dataviewjs", "bloco-executavel"),                 # item de lista
    ("    - ```dataviewjs", "bloco-executavel"),
    ("1. ```run-python", "bloco-executavel"),
    ("12) ~~~js-engine", "bloco-executavel"),
    ("```meta-bind-js-view\n{x} as x\n---\nreturn 1\n```", "bloco-executavel"),
    ("Total: ` $= dv.pages().length` notas", "dataview-js-inline"),
    ("~~~ dataviewjs\n~~~", "bloco-executavel"),
    ("```js-engine\nreturn 1\n```", "bloco-executavel"),
    ("```run-python\nimport os\n```", "bloco-executavel"),
    ("```button\nname Rodar\naction comando\n```", "bloco-executavel"),
    ("Total: `$= dv.pages().length` notas", "dataview-js-inline"),
    ("<%* tR += await tp.system.prompt() %>", "templater"),
    ("Data: <% tp.date.now() %>", "templater"),
]


@pytest.mark.parametrize("texto, tipo", EXECUTAVEIS)
def test_conteudo_que_plugin_executa_bloqueia(texto, tipo):
    assert tipo in [a.tipo for a in privacidade.bloqueantes(privacidade.varrer_texto(texto))]


@pytest.mark.parametrize("texto", [
    "```python\nprint('oi')\n```",
    "```js\nconst x = 1\n```",
    "```dataview\nLIST FROM #projeto\n```",       # consulta DQL, não JS
    "Nome: `= this.file.name`",                      # inline DQL, não JS
    "Se 5 < 6 e 7 > 2, a taxa é de 100%.",
    "<em>ênfase</em> e um comentário %% oculto %%",
    "> citação comum com `código` e ```python",
    "- item de lista com 3 > 2",
])
def test_codigo_e_prosa_comuns_passam(texto):
    assert privacidade.varrer_texto(texto) == []


@pytest.mark.parametrize("cerca", ["```bash", "```sh", "``` shell", "```powershell"])
def test_bloco_de_shell_e_so_aviso(cerca):
    achados = privacidade.varrer_texto(f"{cerca}\nls\n```")
    assert [(a.tipo, a.bloqueia) for a in achados] == [("bloco-de-shell", False)]


def test_so_o_que_a_sessao_acrescentou_bloqueia(tmp_path):
    preexistente = "<% tp.date.now() %>\n```dataviewjs\nx\n```\nsenha = " + "naoconte123\n"
    a, b, c = tmp_path / "a.md", tmp_path / "b.md", tmp_path / "c.md"
    a.write_text(preexistente + "texto novo da sessão\n")          # nada novo de perigoso
    b.write_text(preexistente + "<% tp.file.title %>\n")            # mesmo tipo, +1
    c.write_text("<% tp.date.now() %>\n")                          # arquivo novo
    anteriores = {str(a): preexistente, str(b): preexistente}
    achados = privacidade.varrer_arquivos([a, b, c], anteriores=anteriores)
    bloqueia = {(Path(x.arquivo).name, x.tipo) for x in privacidade.bloqueantes(achados)}
    assert bloqueia == {("b.md", "templater"), ("c.md", "templater")}
    avisos = {(Path(x.arquivo).name, x.tipo) for x in achados if not x.bloqueia}
    assert ("a.md", "templater (preexistente)") in avisos and ("a.md", "senha-atribuida (preexistente)") in avisos
    assert ("b.md", "bloco-executavel (preexistente)") in avisos


BLOCO = "```dataviewjs\ndv.paragraph('oi')\n```\n"


@pytest.mark.parametrize("antes, depois, bloqueia", [
    (BLOCO, BLOCO + "texto novo\n", False),                                       # idêntico: aviso
    (BLOCO, BLOCO.replace("'oi'", "require('child_process')"), True),             # corpo alterado
    (BLOCO, "texto sem o bloco\n", False),                                        # removido
    (BLOCO, BLOCO + BLOCO, True),                                                  # duplicado: +1
    ("> " + BLOCO.replace("\n", "\n> "), "> " + BLOCO.replace("\n", "\n> ").replace("oi", "x"), True),
    ("<% tp.date.now() %>\n", "<% tp.date.now() %>\nmais texto\n", False),
    ("<% tp.date.now() %>\n", "<% tp.system.prompt() %>\n", True),               # trocado por outro
    ("<% tp.date.now() %>\n", "<% tp.date.now() %> <% tp.date.now() %>\n", True),
    ("Total: `$= dv.pages().length`\n", "Total: `$= dv.pages().length`\nfim\n", False),
    ("Total: `$= dv.pages().length`\n", "Total: `$= app.vault.adapter`\n", True),
])
def test_regiao_executavel_comparada_por_conteudo(tmp_path, antes, depois, bloqueia):
    nota = tmp_path / "n.md"
    nota.write_text(depois)
    achados = privacidade.varrer_arquivos([nota], anteriores={str(nota): antes})
    assert bool(privacidade.bloqueantes(achados)) is bloqueia


@pytest.mark.parametrize("texto", ["<%" * 50_000, "<% a\n" * 20_000, "`$=" * 33_000, "```dataviewjs\n" * 20_000])
def test_regioes_executaveis_em_tempo_linear(texto):
    import time
    inicio = time.perf_counter()
    privacidade.regioes_executaveis(texto)
    assert time.perf_counter() - inicio < 0.5


def test_conteudo_executavel_so_conta_em_nota(tmp_path):
    (tmp_path / "a.md").write_text("<% tp.date.now() %>\n")
    (tmp_path / "b.txt").write_text("<% tp.date.now() %>\n")
    achados = privacidade.varrer_arquivos([tmp_path / "a.md", tmp_path / "b.txt"])
    assert [Path(a.arquivo).name for a in achados] == ["a.md"]


def test_texto_limpo_passa():
    texto = ("## 2030-01-01 · Calibração\nLimites: seco 2900, molhado 1300.\n"
             "Variável da senha: SMTP_SENHA\nmax tokens: 4096\n")
    assert privacidade.varrer_texto(texto) == []


def test_email_permitido_por_dominio():
    assert privacidade.varrer_texto("contato@exemplo.test", emails_permitidos=("@exemplo.test",)) == []


def test_termos_proibidos_de_arquivo(tmp_path):
    lista = tmp_path / "termos.txt"
    lista.write_text("# comentário\nprojeto secreto\n\\bcodinome\\b\n")
    termos = privacidade.carregar_termos(lista)
    achados = privacidade.varrer_texto("o Projeto Secreto e o codinome", termos=termos)
    assert [a.tipo for a in achados] == ["termo-proibido", "termo-proibido"]


def test_regex_invalida_na_lista_da_erro_claro(tmp_path):
    lista = tmp_path / "termos.txt"
    lista.write_text("(sem fechar\n")
    with pytest.raises(ValueError, match="termos.txt:1"):
        privacidade.carregar_termos(lista)


def test_arquivo_removido_ou_imagem_e_pulado(tmp_path):
    (tmp_path / "g.png").write_bytes(b"\x89PNG" + FALSOS["chave-aws"].encode())
    assert privacidade.varrer_arquivos([tmp_path / "g.png", tmp_path / "sumiu.md"]) == []


def test_cli_codigo_de_saida(tmp_path, capsys):
    limpo, sujo = tmp_path / "a.md", tmp_path / "b.md"
    limpo.write_text("nada aqui\n")
    sujo.write_text(FALSOS["chave-aws"] + "\n")
    longo = tmp_path / "c.md"
    longo.write_text("y" * 5000 + "\n")
    assert privacidade.main([str(limpo)]) == 0
    assert privacidade.main([str(longo)]) == 0          # só aviso não reprova
    assert privacidade.main([str(limpo), str(sujo)]) == 1
    assert "chave-aws" in capsys.readouterr().out
