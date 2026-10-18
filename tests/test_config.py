from pathlib import Path

import pytest

from docserver import config


def _escrever(pasta: Path, texto: str) -> Path:
    arquivo = pasta / config.NOME_ARQUIVO
    arquivo.write_text(texto, encoding="utf-8")
    return arquivo


def test_sem_arquivo_devolve_os_padroes_atuais(tmp_path):
    cfg = config.carregar(tmp_path)

    assert cfg.raiz is None
    assert cfg.docs_fonte == Path("docs-fonte")
    assert cfg.docs_normalizado == Path("docs-normalizado")
    assert cfg.indice == Path("data/indice.db")
    assert cfg.embeddings is True
    assert cfg.ignorar == ()
    assert cfg.revisor["max_tentativas"] == 3


def test_arquivo_na_pasta_pai_e_encontrado_a_partir_de_subpasta(tmp_path):
    arquivo = _escrever(tmp_path, '[docs]\nfonte = "docs"\n')
    subpasta = tmp_path / "a" / "b"
    subpasta.mkdir(parents=True)

    assert config.encontrar(subpasta) == arquivo.resolve()
    assert config.carregar(subpasta).docs_fonte == arquivo.resolve().parent / "docs"


def test_caminhos_relativos_partem_da_pasta_do_arquivo_e_nao_do_cwd(tmp_path, monkeypatch):
    projeto = tmp_path / "projeto"
    outra = tmp_path / "outra"
    projeto.mkdir()
    outra.mkdir()
    _escrever(
        projeto,
        '[docs]\nfonte = "docs"\nnormalizado = ".docserver/normalizado"\nindice = ".docserver/indice.db"\n'
        'embeddings = false\nignorar = ["_pendentes", "_revisoes.jsonl"]\n',
    )
    monkeypatch.chdir(projeto)
    (projeto / "sub").mkdir()
    monkeypatch.chdir(projeto / "sub")

    cfg = config.carregar()

    raiz = projeto.resolve()
    assert cfg.raiz == raiz
    assert cfg.docs_fonte == raiz / "docs"
    assert cfg.docs_normalizado == raiz / ".docserver" / "normalizado"
    assert cfg.indice == raiz / ".docserver" / "indice.db"
    assert cfg.embeddings is False
    assert cfg.ignorar == ("_pendentes", "_revisoes.jsonl", "_rejeitados")


def test_revisor_mescla_com_os_padroes_e_ignora_chaves_desconhecidas(tmp_path):
    _escrever(tmp_path, 'desconhecida = 1\n[docs]\nxpto = "y"\n[revisor]\nmodelo = "outro"\nmax_tentativas = 5\n')

    cfg = config.carregar(tmp_path)

    assert cfg.revisor["modelo"] == "outro"
    assert cfg.revisor["max_tentativas"] == 5
    assert cfg.revisor["pendentes"] == "_pendentes"
    assert cfg.revisor["aprovados"] == "conhecimento"
    assert cfg.revisor["comando"][0] == "claude"


@pytest.mark.parametrize(
    "texto, chave",
    [
        ('[docs]\nignorar = "_pendentes"\n', "docs.ignorar"),
        ("[docs]\nignorar = [1, 2]\n", "docs.ignorar"),
        ('[docs]\nembeddings = "nao"\n', "docs.embeddings"),
        ("[docs]\nfonte = 3\n", "docs.fonte"),
        ('[revisor]\nmax_tentativas = "tres"\n', "revisor.max_tentativas"),
        ('[revisor]\ncomando = "claude"\n', "revisor.comando"),
    ],
)
def test_tipo_errado_gera_erro_claro_com_arquivo_e_chave(tmp_path, texto, chave):
    _escrever(tmp_path, texto)

    with pytest.raises(ValueError) as erro:
        config.carregar(tmp_path)

    assert config.NOME_ARQUIVO in str(erro.value)
    assert chave in str(erro.value)


def test_toml_invalido_gera_erro_claro(tmp_path):
    _escrever(tmp_path, "[docs\nfonte = ")

    with pytest.raises(ValueError, match="TOML inválido") as erro:
        config.carregar(tmp_path)

    assert config.NOME_ARQUIVO in str(erro.value)


def test_quarentena_vale_mesmo_sem_ignorar_no_arquivo(tmp_path):
    (tmp_path / config.NOME_ARQUIVO).write_text(
        '[docs]\nfonte = "docs"\n[revisor]\npendentes = "rascunhos"\n', encoding="utf-8"
    )

    cfg = config.carregar(tmp_path)

    assert set(cfg.ignorar) == {"rascunhos", "_rejeitados", "_revisoes.jsonl"}
