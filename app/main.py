import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import config_manager, armazenamento, sincronizador
from app.certificado import (
    validar_certificado, CertificadoInvalidoError, CertificadoExpiradoError
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent

app = FastAPI(title="Portal NF-e / CT-e")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _status_certificado(config: dict) -> dict:
    cert = config.get("certificado", {})
    if not cert.get("caminho") or not cert.get("senha_criptografada"):
        return {"status": "nao_configurado", "label": "Não configurado", "info": {}}
    try:
        senha = config_manager.obter_senha_certificado(config)
        info = validar_certificado(cert["caminho"], senha)
        if info["dias_restantes"] <= 30:
            return {"status": "expirando", "label": f"Expira em {info['dias_restantes']} dias", "info": info}
        return {"status": "valido", "label": "Válido", "info": info}
    except CertificadoExpiradoError as e:
        return {"status": "expirado", "label": "Expirado", "info": {"nome": str(e)}}
    except Exception as e:
        return {"status": "erro", "label": "Erro", "info": {"nome": str(e)}}


# ─── Páginas ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    config = config_manager.carregar()
    cert_status = _status_certificado(config)
    ok, erros = config_manager.esta_configurado(config)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "config": config,
        "cert_status": cert_status,
        "configurado": ok,
        "erros_config": erros,
        "current": "dashboard",
    })


@app.get("/configuracoes", response_class=HTMLResponse)
async def pg_configuracoes(request: Request, ok: str = "", erro: str = ""):
    config = config_manager.carregar()
    return templates.TemplateResponse("configuracoes.html", {
        "request": request,
        "config": config,
        "msg_ok": ok,
        "msg_erro": erro,
        "current": "configuracoes",
    })


@app.post("/configuracoes")
async def salvar_configuracoes(
    cnpj: Annotated[str, Form()],
    pasta_destino: Annotated[str, Form()],
    ambiente: Annotated[int, Form()],
    nfe_producao: Annotated[str, Form()],
    nfe_homologacao: Annotated[str, Form()],
    cte_producao: Annotated[str, Form()],
    cte_homologacao: Annotated[str, Form()],
):
    cnpj_limpo = "".join(c for c in cnpj if c.isdigit())
    if len(cnpj_limpo) != 14:
        return RedirectResponse("/configuracoes?erro=CNPJ+inválido+%28deve+ter+14+dígitos%29", status_code=303)

    ok, msg = armazenamento.verificar_pasta(pasta_destino)
    if not ok:
        return RedirectResponse(f"/configuracoes?erro=Pasta+inacessível%3A+{msg}", status_code=303)

    config = config_manager.carregar()
    config["cnpj"] = cnpj_limpo
    config["pasta_destino"] = pasta_destino
    config["ambiente"] = ambiente
    config["endpoints"]["nfe_producao"] = nfe_producao
    config["endpoints"]["nfe_homologacao"] = nfe_homologacao
    config["endpoints"]["cte_producao"] = cte_producao
    config["endpoints"]["cte_homologacao"] = cte_homologacao
    config_manager.salvar(config)
    return RedirectResponse("/configuracoes?ok=Configurações+salvas+com+sucesso", status_code=303)


@app.get("/certificado", response_class=HTMLResponse)
async def pg_certificado(request: Request, ok: str = "", erro: str = ""):
    config = config_manager.carregar()
    cert_status = _status_certificado(config)
    return templates.TemplateResponse("certificado.html", {
        "request": request,
        "config": config,
        "cert_status": cert_status,
        "msg_ok": ok,
        "msg_erro": erro,
        "current": "certificado",
    })


@app.post("/certificado")
async def upload_certificado(
    arquivo: Annotated[UploadFile, File()],
    senha: Annotated[str, Form()],
):
    if not arquivo.filename or not arquivo.filename.lower().endswith((".pfx", ".p12")):
        return RedirectResponse("/certificado?erro=O+arquivo+deve+ter+extensão+.pfx+ou+.p12", status_code=303)

    destino = config_manager.CERT_FILE
    try:
        conteudo = await arquivo.read()
        destino.write_bytes(conteudo)

        info = validar_certificado(str(destino), senha)

        config = config_manager.carregar()
        config["certificado"]["caminho"] = str(destino)
        config["certificado"]["senha_criptografada"] = config_manager.criptografar_senha(senha)
        config_manager.salvar(config)

        msg = f"Certificado carregado. Titular: {info['nome']}. Válido até {info['validade']}."
        return RedirectResponse(f"/certificado?ok={msg.replace(' ', '+')}", status_code=303)

    except CertificadoExpiradoError as e:
        destino.unlink(missing_ok=True)
        return RedirectResponse(f"/certificado?erro={str(e).replace(' ', '+')}", status_code=303)
    except CertificadoInvalidoError as e:
        destino.unlink(missing_ok=True)
        return RedirectResponse(f"/certificado?erro={str(e).replace(' ', '+')}", status_code=303)
    except Exception as e:
        destino.unlink(missing_ok=True)
        return RedirectResponse(f"/certificado?erro=Erro+inesperado%3A+{str(e)[:80]}", status_code=303)


@app.post("/certificado/remover")
async def remover_certificado():
    config = config_manager.carregar()
    config["certificado"]["caminho"] = ""
    config["certificado"]["senha_criptografada"] = ""
    config_manager.salvar(config)
    config_manager.CERT_FILE.unlink(missing_ok=True)
    return RedirectResponse("/certificado?ok=Certificado+removido", status_code=303)


@app.get("/sincronizar", response_class=HTMLResponse)
async def pg_sincronizar(request: Request):
    config = config_manager.carregar()
    ok, erros = config_manager.esta_configurado(config)
    return templates.TemplateResponse("sincronizar.html", {
        "request": request,
        "configurado": ok,
        "erros_config": erros,
        "current": "sincronizar",
    })


# ─── API ───────────────────────────────────────────────────────────────────────

@app.get("/api/sync/{tipo}/stream")
async def sync_stream(tipo: str):
    """Server-Sent Events: transmite o progresso da sincronização em tempo real."""
    if tipo not in ("nfe", "cte", "tudo"):
        async def gen_err():
            yield f"data: {json.dumps({'msg': 'Tipo inválido.', 'nivel': 'erro'})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        return StreamingResponse(gen_err(), media_type="text/event-stream")

    config = config_manager.carregar()
    ok, erros = config_manager.esta_configurado(config)

    if not ok:
        async def gen_config_err():
            for e in erros:
                yield f"data: {json.dumps({'msg': f'ERRO: {e}', 'nivel': 'erro'})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        return StreamingResponse(gen_config_err(), media_type="text/event-stream")

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def on_progress(msg: str):
        loop.call_soon_threadsafe(queue.put_nowait, {"msg": msg, "nivel": "info"})

    def run_sync():
        try:
            if tipo == "nfe":
                results = [sincronizador.sincronizar_nfe(config, on_progress)]
            elif tipo == "cte":
                results = [sincronizador.sincronizar_cte(config, on_progress)]
            else:
                results = sincronizador.sincronizar_tudo(config, on_progress)

            linhas = []
            tem_erro = False
            for r in results:
                linhas.append(f"{'✓' if not r.erros else '⚠'} {r.tipo}: {r.total_baixados} documento(s) | NSU: {r.ult_nsu}")
                for e in r.erros:
                    linhas.append(f"  ✗ {e}")
                    tem_erro = True

            nivel = "erro" if tem_erro else "sucesso"
            loop.call_soon_threadsafe(queue.put_nowait, {
                "msg": "\n".join(linhas), "nivel": nivel, "done": True
            })
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, {
                "msg": f"ERRO CRÍTICO: {e}", "nivel": "erro", "done": True
            })

    async def generate():
        loop.run_in_executor(None, run_sync)
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=120.0)
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if item.get("done"):
                    break
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/nsu/reset/{tipo}")
async def reset_nsu(tipo: str):
    if tipo not in ("nfe", "cte", "tudo"):
        return {"erro": "Tipo inválido"}
    if tipo == "tudo":
        config_manager.atualizar_nsu("nfe", "0")
        config_manager.atualizar_nsu("cte", "0")
    else:
        config_manager.atualizar_nsu(tipo, "0")
    return {"ok": True, "tipo": tipo}


@app.get("/api/status")
async def api_status():
    config = config_manager.carregar()
    cert_status = _status_certificado(config)
    ok, erros = config_manager.esta_configurado(config)
    return {
        "configurado": ok,
        "erros": erros,
        "cnpj": config.get("cnpj"),
        "ambiente": config.get("ambiente"),
        "nsu_nfe": config["nsu"].get("nfe"),
        "nsu_cte": config["nsu"].get("cte"),
        "certificado": cert_status,
    }
