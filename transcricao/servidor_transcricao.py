"""
Servidor de transcricao local, compativel com a API da OpenAI (speech-to-text).

Endpoints
  GET  /health                     estado do servidor (sem chave)
  GET  /v1/models                  lista com "whisper-1" (para clientes OpenAI)
  POST /v1/audio/transcriptions    transcreve um ficheiro de audio ou video
  GET  /v1/gpu                     memoria livre da placa e quem a esta a usar
  POST /v1/gpu/libertar            descarrega o Whisper e os modelos do Ollama (e, se pedires, do ComfyUI)

Motor: faster-whisper (CTranslate2) com o Whisper large-v3-turbo, com tempos por palavra.
O modelo carrega no primeiro pedido e sai da placa ao fim de IDLE_SECONDS sem pedidos,
para a GPU ficar livre para jogos, ComfyUI ou outros modelos.

Antes de carregar, se a placa nao tiver memoria suficiente, o servidor:
  1. espera que o ComfyUI acabe o trabalho em curso (nunca o interrompe);
  2. pede ao Ollama para descarregar os modelos;
  3. pede ao ComfyUI para libertar a memoria (POST /free).

Toda a configuracao vem de variaveis de ambiente (ver README.md desta pasta).
"""
from __future__ import annotations

import gc
import glob
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
import urllib.request
from typing import Optional

import numpy as np
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

# ---------------------------------------------------------------- configuracao (variaveis de ambiente)
MODELO = os.environ.get("TRANSCRICAO_MODELO", "large-v3-turbo")      # nome do faster-whisper ou pasta local
DISPOSITIVO = os.environ.get("TRANSCRICAO_DISPOSITIVO", "cuda")       # "cuda" ou "cpu"
PRECISAO = os.environ.get("TRANSCRICAO_PRECISAO", "float16")          # "float16" (GPU), "int8" (CPU)
IDIOMA_PADRAO = os.environ.get("TRANSCRICAO_IDIOMA", "").strip() or None  # ex.: "pt"; vazio = deteta sozinho
IDLE_SECONDS = int(os.environ.get("TRANSCRICAO_IDLE_SEGUNDOS", "300"))
API_KEY = os.environ.get("TRANSCRICAO_API_KEY", "").strip()           # vazio = sem chave (so em 127.0.0.1!)
FFMPEG = os.environ.get("TRANSCRICAO_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
COMFY_URL = os.environ.get("TRANSCRICAO_COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
OLLAMA_URL = os.environ.get("TRANSCRICAO_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
PRECISA_GB = float(os.environ.get("TRANSCRICAO_PRECISA_GB", "3.0"))   # VRAM que o Whisper turbo usa (~3 GB)
COMFY_ESPERA_MAX = int(os.environ.get("TRANSCRICAO_COMFY_ESPERA_MAX", "1800"))  # segundos

SEM_JANELA = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW no Windows

app = FastAPI(title="Servidor de transcricao local", version="1.0")
gpu_lock = threading.Lock()
state: dict = {"modelo": None, "ultimo_uso": time.time()}


# ---------------------------------------------------------------- utilitarios
def check_key(request: Request):
    if not API_KEY:
        return
    if request.headers.get("authorization", "") != f"Bearer {API_KEY}":
        raise HTTPException(401, "chave de API invalida")


def touch():
    state["ultimo_uso"] = time.time()


def ffmpeg(args: list[str]) -> bytes:
    try:
        p = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", *args],
                           capture_output=True, creationflags=SEM_JANELA)
    except FileNotFoundError:
        raise HTTPException(500, "ffmpeg nao encontrado: instala-o ou define TRANSCRICAO_FFMPEG")
    if p.returncode != 0:
        raise HTTPException(500, f"ffmpeg: {p.stderr.decode(errors='ignore')[:300]}")
    return p.stdout


def _http_json(method: str, url: str, data: Optional[dict] = None, timeout: float = 10):
    req = urllib.request.Request(url, method=method,
                                 data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body) if body else {}


# ---------------------------------------------------------------- partilha da GPU (ComfyUI / Ollama)
def gpu_free_gb() -> float:
    """Memoria livre da placa TODA (nvidia-smi), nao so deste processo."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, creationflags=SEM_JANELA).stdout
        return float(out.strip().splitlines()[0]) / 1024
    except Exception:
        return float("inf")  # sem nvidia-smi (ex.: CPU): nao tenta libertar nada


def comfy_busy() -> bool:
    try:
        q = _http_json("GET", f"{COMFY_URL}/queue", timeout=5)
        return bool(q.get("queue_running") or q.get("queue_pending"))
    except Exception:
        return False  # ComfyUI desligado = nao esta ocupado


def free_comfy() -> bool:
    try:
        _http_json("POST", f"{COMFY_URL}/free", {"unload_models": True, "free_memory": True}, timeout=15)
        return True
    except Exception:
        return False


def unload_ollama() -> list[str]:
    try:
        modelos = [m["name"] for m in _http_json("GET", f"{OLLAMA_URL}/api/ps", timeout=5).get("models", [])]
    except Exception:
        return []
    for nome in modelos:
        try:
            _http_json("POST", f"{OLLAMA_URL}/api/generate", {"model": nome, "keep_alive": 0}, timeout=30)
        except Exception:
            pass
    return modelos


def release_others(need_gb: float) -> None:
    """Se a placa nao tiver espaco: espera pelo ComfyUI, descarrega o Ollama e liberta o ComfyUI."""
    if DISPOSITIVO != "cuda" or gpu_free_gb() >= need_gb:
        return
    t0 = time.time()
    while comfy_busy() and time.time() - t0 < COMFY_ESPERA_MAX:
        time.sleep(5)
    unload_ollama()
    if not comfy_busy():
        free_comfy()
    time.sleep(2)


# ---------------------------------------------------------------- modelo
def _dlls_cuda_windows():
    """No Windows o CTranslate2 precisa das DLLs do CUDA 12 (cuBLAS/cuDNN). Se as instalaste com
    pip (nvidia-cublas-cu12, nvidia-cudnn-cu12), ficam em site-packages/nvidia/*/bin: junta-as ao PATH."""
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return
    base = sysconfig.get_paths()["purelib"]
    for d in glob.glob(os.path.join(base, "nvidia", "*", "bin")) + glob.glob(os.path.join(base, "torch", "lib")):
        try:
            os.add_dll_directory(d)
        except OSError:
            continue
        if d not in os.environ.get("PATH", ""):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


def load_model():
    if state["modelo"] is None:
        release_others(PRECISA_GB)
        _dlls_cuda_windows()
        from faster_whisper import WhisperModel
        state["modelo"] = WhisperModel(MODELO, device=DISPOSITIVO, compute_type=PRECISAO)
    return state["modelo"]


def unload_all():
    state["modelo"] = None
    gc.collect()


def idle_watcher():
    while True:
        time.sleep(30)
        if state["modelo"] is not None and time.time() - state["ultimo_uso"] > IDLE_SECONDS:
            with gpu_lock:
                if time.time() - state["ultimo_uso"] > IDLE_SECONDS:
                    unload_all()


threading.Thread(target=idle_watcher, daemon=True).start()


def decode_to_16k(data: bytes) -> np.ndarray:
    """Converte qualquer audio/video para mono 16 kHz. Passa por um ficheiro temporario (e nao por stdin)
    porque um MP4 com o indice no fim nao se le a partir de um pipe."""
    fd, tmp = tempfile.mkstemp(suffix=".bin")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        raw = ffmpeg(["-i", tmp, "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"])
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    audio = np.frombuffer(raw, dtype=np.float32).copy()
    if audio.size == 0:
        raise HTTPException(400, "nao foi possivel ler audio do ficheiro enviado")
    return audio


def transcribe(audio: np.ndarray, language: Optional[str], prompt: Optional[str],
               temperature: Optional[float], words: bool) -> tuple[str, list[dict], list[dict], str]:
    segs, info = load_model().transcribe(
        audio, language=language or IDIOMA_PADRAO, word_timestamps=words, vad_filter=True,
        beam_size=5, condition_on_previous_text=False, initial_prompt=prompt or None,
        temperature=temperature if temperature is not None else [0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    textos, segmentos, palavras = [], [], []
    for i, seg in enumerate(segs):  # e um gerador: a descodificacao acontece aqui
        t = seg.text.strip()
        textos.append(t)
        segmentos.append({"id": i, "start": round(float(seg.start), 2), "end": round(float(seg.end), 2), "text": t})
        for w in (seg.words or []) if words else []:
            p = w.word.strip()
            if p:
                palavras.append({"word": p, "start": round(float(w.start), 2), "end": round(float(w.end), 2)})
        touch()
    return " ".join(t for t in textos if t), segmentos, palavras, info.language


def _tempo_srt(s: float, sep: str = ",") -> str:
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    seg, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{seg:02d}{sep}{ms:03d}"


def _legendas(segmentos: list[dict], vtt: bool) -> str:
    sep = "." if vtt else ","
    linhas = ["WEBVTT", ""] if vtt else []
    for i, s in enumerate(segmentos, 1):
        if not vtt:
            linhas.append(str(i))
        linhas += [f"{_tempo_srt(s['start'], sep)} --> {_tempo_srt(s['end'], sep)}", s["text"], ""]
    return "\n".join(linhas)


# ---------------------------------------------------------------- endpoints
@app.get("/health")
def health():
    return {"ok": True, "modelo": MODELO, "carregado": state["modelo"] is not None,
            "dispositivo": DISPOSITIVO, "descarrega_apos_segundos": IDLE_SECONDS}


@app.get("/v1/models", dependencies=[Depends(check_key)])
def models():
    return {"object": "list", "data": [{"id": "whisper-1", "object": "model", "owned_by": "local"}]}


@app.get("/v1/gpu", dependencies=[Depends(check_key)])
def gpu_status():
    try:
        ollama = [m["name"] for m in _http_json("GET", f"{OLLAMA_URL}/api/ps", timeout=5).get("models", [])]
    except Exception:
        ollama = None
    livre = gpu_free_gb()
    return {"free_gb": None if livre == float("inf") else round(livre, 2), "comfyui_busy": comfy_busy(),
            "ollama_loaded": ollama, "whisper_loaded": state["modelo"] is not None}


class FreeRequest(BaseModel):
    comfyui: bool = False  # tambem libertar os modelos em cache do ComfyUI (so se nao estiver a trabalhar)


@app.post("/v1/gpu/libertar", dependencies=[Depends(check_key)])
def gpu_free(req: FreeRequest = FreeRequest()):
    """Chama antes de um trabalho pesado (video, 3D): liberta o Whisper e o Ollama.
    Se estiver a decorrer uma transcricao, espera que acabe."""
    with gpu_lock:
        unload_all()
    ollama = unload_ollama()
    comfy = free_comfy() if req.comfyui and not comfy_busy() else False
    time.sleep(1)
    livre = gpu_free_gb()
    return {"free_gb_after": None if livre == float("inf") else round(livre, 2),
            "ollama_unloaded": ollama, "comfyui_freed": comfy}


@app.post("/v1/audio/transcriptions", dependencies=[Depends(check_key)])
def transcriptions(file: UploadFile = File(...), model: str = Form("whisper-1"),
                   language: Optional[str] = Form(None), response_format: str = Form("json"),
                   prompt: Optional[str] = Form(None), temperature: Optional[float] = Form(None),
                   granularities: Optional[list[str]] = Form(None, alias="timestamp_granularities[]")):
    audio = decode_to_16k(file.file.read())
    want_words = response_format == "verbose_json" and "word" in (granularities or [])
    with gpu_lock:
        touch()
        text, segmentos, palavras, idioma = transcribe(audio, language, prompt, temperature, want_words)
        touch()
    if response_format == "text":
        return PlainTextResponse(text)
    if response_format in ("srt", "vtt"):
        return PlainTextResponse(_legendas(segmentos, response_format == "vtt"))
    if response_format == "verbose_json":
        out = {"task": "transcribe", "text": text, "language": idioma,
               "duration": round(len(audio) / 16000, 2), "segments": segmentos}
        if want_words:
            out["words"] = palavras
        return out
    return {"text": text}


@app.exception_handler(RuntimeError)
def runtime_handler(_req, exc: RuntimeError):
    if "out of memory" in str(exc).lower():
        unload_all()
        return JSONResponse(status_code=503, content={"error": "GPU sem memoria (jogo ou outro trabalho a correr?). Tenta outra vez."})
    return JSONResponse(status_code=500, content={"error": str(exc)[:500]})


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("TRANSCRICAO_HOST", "127.0.0.1")
    porta = int(os.environ.get("TRANSCRICAO_PORTA", "8000"))
    if host not in ("127.0.0.1", "localhost") and not API_KEY:
        print("AVISO: a escutar fora de 127.0.0.1 sem TRANSCRICAO_API_KEY. Qualquer pessoa na rede pode usar.",
              file=sys.stderr)
    uvicorn.run(app, host=host, port=porta, log_level="info")
