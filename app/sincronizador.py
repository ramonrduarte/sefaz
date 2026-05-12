import logging
from dataclasses import dataclass, field
from typing import Callable

from app import config_manager, armazenamento, sefaz_nfe, sefaz_cte
from app.certificado import ContextoCertificado

logger = logging.getLogger(__name__)

CSTAT_COM_DOCS = "118"
CSTAT_SEM_DOCS = "117"


@dataclass
class ResultadoSync:
    tipo: str
    total_baixados: int
    ult_nsu: str
    erros: list[str] = field(default_factory=list)


def _sincronizar_tipo(tipo: str, config: dict,
                      cert_path: str, key_path: str,
                      cb: Callable[[str], None] | None = None) -> ResultadoSync:
    cnpj = config["cnpj"]
    ambiente = config.get("ambiente", 1)
    pasta_destino = config["pasta_destino"]
    ult_nsu = config["nsu"].get(tipo.lower(), "0")
    endpoint = config_manager.obter_endpoint(config, tipo.lower())

    total = 0
    erros = []

    while True:
        if cb:
            cb(f"Consultando {tipo} a partir do NSU {ult_nsu}...")
        try:
            if tipo == "NFe":
                resposta = sefaz_nfe.consultar(endpoint, cnpj, ult_nsu, ambiente, cert_path, key_path)
            else:
                resposta = sefaz_cte.consultar(endpoint, cnpj, ult_nsu, ambiente, cert_path, key_path)

            if cb:
                cb(f"Resposta: {resposta.c_stat} — {resposta.x_motivo}")

            if resposta.c_stat == CSTAT_SEM_DOCS:
                if cb:
                    cb("Nenhum documento novo.")
                break

            if resposta.c_stat != CSTAT_COM_DOCS:
                msg = f"Status inesperado: {resposta.c_stat} — {resposta.x_motivo}"
                erros.append(msg)
                if cb:
                    cb(f"ERRO: {msg}")
                break

            if cb:
                cb(f"Recebidos {len(resposta.documentos)} documento(s).")

            for doc in resposta.documentos:
                try:
                    caminho = armazenamento.salvar_documento(
                        pasta_destino=pasta_destino,
                        tipo=tipo,
                        ch_acesso=doc.ch_acesso,
                        schema=doc.schema,
                        xml_bytes=doc.xml_bytes,
                    )
                    total += 1
                    if cb:
                        cb(f"  Salvo: {caminho.name}")
                except Exception as e:
                    msg = f"Erro ao salvar {doc.ch_acesso}: {e}"
                    erros.append(msg)
                    if cb:
                        cb(f"  ERRO: {msg}")

            novo_nsu = resposta.ult_nsu_ret
            if not novo_nsu or novo_nsu == ult_nsu:
                break
            ult_nsu = novo_nsu
            config_manager.atualizar_nsu(tipo.lower(), ult_nsu)

            if len(resposta.documentos) < 50:
                break

        except Exception as e:
            msg = f"Erro na comunicação com SEFAZ-RS ({tipo}): {e}"
            erros.append(msg)
            if cb:
                cb(f"ERRO: {msg}")
            break

    config_manager.atualizar_nsu(tipo.lower(), ult_nsu)
    return ResultadoSync(tipo=tipo, total_baixados=total, ult_nsu=ult_nsu, erros=erros)


def sincronizar_nfe(config: dict, cb=None) -> ResultadoSync:
    with ContextoCertificado(config["certificado"]["caminho"],
                             config_manager.obter_senha_certificado(config)) as (c, k):
        return _sincronizar_tipo("NFe", config, c, k, cb)


def sincronizar_cte(config: dict, cb=None) -> ResultadoSync:
    with ContextoCertificado(config["certificado"]["caminho"],
                             config_manager.obter_senha_certificado(config)) as (c, k):
        return _sincronizar_tipo("CTe", config, c, k, cb)


def sincronizar_tudo(config: dict, cb=None) -> list[ResultadoSync]:
    with ContextoCertificado(config["certificado"]["caminho"],
                             config_manager.obter_senha_certificado(config)) as (c, k):
        return [
            _sincronizar_tipo("NFe", config, c, k, cb),
            _sincronizar_tipo("CTe", config, c, k, cb),
        ]
