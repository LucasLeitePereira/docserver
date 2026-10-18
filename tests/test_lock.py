import subprocess
import sys
import time

import pytest

from docserver import lock

SEGURAR = """
import sys, time
from pathlib import Path
from docserver import lock
with lock.travar(Path(sys.argv[1])):
    Path(sys.argv[2]).write_text("pegou")
    time.sleep(float(sys.argv[3]))
"""


def segurar_em_outro_processo(caminho, sinal, segundos):
    proc = subprocess.Popen([sys.executable, "-c", SEGURAR, str(caminho), str(sinal), str(segundos)])
    limite = time.monotonic() + 30
    while not sinal.exists():
        assert time.monotonic() < limite, "o processo filho não pegou o lock"
        time.sleep(0.05)
    return proc


def test_caminho_lock_usa_nome_proprio_ao_lado_do_indice(tmp_path):
    assert lock.caminho_lock(tmp_path / "indice.db").name == "indice.db.ingestao.lock"
    assert lock.caminho_lock(tmp_path / "indice.db", "revisao").name == "indice.db.revisao.lock"


def test_adquire_e_libera_criando_a_pasta_pai(tmp_path):
    caminho = tmp_path / "a" / "b" / "x.lock"
    with lock.travar(caminho, espera_s=0.3):
        assert caminho.exists()
    # liberado: pode travar de novo
    with lock.travar(caminho, espera_s=0.3):
        pass


def test_segundo_processo_espera_e_depois_consegue(tmp_path):
    caminho, sinal = tmp_path / "x.lock", tmp_path / "sinal"
    proc = segurar_em_outro_processo(caminho, sinal, 2)
    try:
        avisos = []
        inicio = time.monotonic()
        with lock.travar(caminho, espera_s=20, ao_aguardar=lambda: avisos.append(1)):
            pass
        assert time.monotonic() - inicio > 0.5
        assert avisos == [1]
    finally:
        proc.wait(timeout=30)


def test_espera_curta_levanta_lock_ocupado_e_avisa_uma_vez(tmp_path):
    caminho, sinal = tmp_path / "x.lock", tmp_path / "sinal"
    proc = segurar_em_outro_processo(caminho, sinal, 3)
    try:
        avisos = []
        with pytest.raises(lock.LockOcupado, match="x.lock"):
            with lock.travar(caminho, espera_s=0.6, intervalo_s=0.1, ao_aguardar=lambda: avisos.append(1)):
                pass
        assert avisos == [1]
    finally:
        proc.wait(timeout=30)


def test_arquivo_de_lock_preexistente_sem_dono_nao_trava(tmp_path):
    caminho = tmp_path / "velho.lock"
    caminho.write_text("lixo de uma execução antiga")
    with lock.travar(caminho, espera_s=0.3):
        pass


def test_excecao_dentro_do_bloco_libera_o_lock(tmp_path):
    caminho = tmp_path / "x.lock"
    with pytest.raises(RuntimeError):
        with lock.travar(caminho, espera_s=0.3):
            raise RuntimeError("falha")
    with lock.travar(caminho, espera_s=0.3):
        pass
