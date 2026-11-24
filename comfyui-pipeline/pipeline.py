"""Pipeline imagem -> edicao -> video no ComfyUI local, a partir da linha de comandos.

  python pipeline.py imagem  --texto "..." [--n 4] [--seed 1] [--nome robo]
  python pipeline.py editar  --img saida/robo_1.png [--img outra_ref.png] --texto "..." [--nome cena1]
  python pipeline.py video   --img saida/cena1_1.png --texto "..." [--fim saida/fim.png] [--segundos 5]
  python pipeline.py ultimo-fotograma saida/cena1_1.mp4            (para encadear planos)
  python pipeline.py suavizar saida/cena1_1.mp4 [--fps 32] [--largura 1080 --altura 1920]

Modelos:
  imagem  -> Z-Image Turbo (8 passos)
  editar  -> Qwen-Image-Edit 2511 + LoRA Lightning de 4 passos (ate 3 imagens de referencia)
  video   -> Wan 2.2 I2V 14B (high/low noise) + LoRA lightx2v de 4 passos, 16 fps
             com --fim usa primeira e ultima imagem (WanFirstLastFrameToVideo)

Os fluxos estao em workflows/*.json (formato API do ComfyUI). Este script le-os, troca o texto,
o tamanho, a seed, as imagens e os nomes dos modelos (do config.json) e envia-os.
So usa a biblioteca padrao do Python.
"""
import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid

AQUI = os.path.dirname(os.path.abspath(__file__))
WORKFLOWS = os.path.join(AQUI, "workflows")


# ---------------------------------------------------------------- configuracao
def carregar_config(caminho=None):
    """config.json ao lado do script (copia do config.exemplo.json); variaveis de ambiente por cima."""
    with open(os.path.join(AQUI, "config.exemplo.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    caminho = caminho or os.environ.get("PIPELINE_CONFIG") or os.path.join(AQUI, "config.json")
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            meu = json.load(f)
        modelos = dict(cfg["modelos"], **meu.get("modelos", {}))
        tamanhos = dict(cfg["tamanhos"], **meu.get("tamanhos", {}))
        cfg.update(meu)
        cfg["modelos"], cfg["tamanhos"] = modelos, tamanhos
    cfg["comfy_url"] = os.environ.get("COMFY_URL", cfg["comfy_url"]).rstrip("/")
    cfg["ffmpeg"] = os.environ.get("PIPELINE_FFMPEG", cfg.get("ffmpeg") or "ffmpeg")
    saida = os.environ.get("PIPELINE_SAIDA", cfg["pasta_saida"])
    cfg["pasta_saida"] = saida if os.path.isabs(saida) else os.path.join(os.getcwd(), saida)
    return cfg


CFG = None


def cfg():
    global CFG
    if CFG is None:
        CFG = carregar_config()
    return CFG


def workflow(nome):
    with open(os.path.join(WORKFLOWS, nome), encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- ComfyUI
def _req(caminho, dados=None, cab=None, timeout=60):
    r = urllib.request.Request(cfg()["comfy_url"] + caminho, data=dados, headers=cab or {})
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return f.read()


def enviar_imagem(caminho):
    """Envia uma imagem para a pasta input do ComfyUI e devolve o nome com que ficou."""
    nome = "pipeline_" + os.path.basename(caminho)
    lim = uuid.uuid4().hex
    with open(caminho, "rb") as f:
        dados = f.read()
    corpo = (f"--{lim}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{nome}\"\r\n"
             f"Content-Type: image/png\r\n\r\n").encode() + dados + \
            (f"\r\n--{lim}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{lim}--\r\n").encode()
    r = json.loads(_req("/upload/image", corpo, {"Content-Type": f"multipart/form-data; boundary={lim}"}))
    return r["name"]


def correr(fluxo, nome):
    """Envia o fluxo, espera e descarrega as saidas para <pasta_saida>/<nome>_N.ext. Devolve os caminhos."""
    t0 = time.time()
    r = json.loads(_req("/prompt", json.dumps({"prompt": fluxo, "client_id": uuid.uuid4().hex}).encode(),
                        {"Content-Type": "application/json"}))
    if r.get("node_errors"):
        sys.exit("ERROS: " + json.dumps(r["node_errors"], ensure_ascii=False)[:3000])
    pid = r["prompt_id"]
    print(f"Na fila ({pid}). A espera...", flush=True)
    while True:
        time.sleep(3)
        h = json.loads(_req("/history/" + pid))
        if pid in h:
            h = h[pid]
            break
    est = h.get("status", {})
    if est.get("status_str") != "success":
        sys.exit("FALHOU: " + json.dumps(est, ensure_ascii=False)[:4000])
    pasta = cfg()["pasta_saida"]
    os.makedirs(pasta, exist_ok=True)
    feitos = []
    for saida in h["outputs"].values():
        for lista in saida.values():
            if not isinstance(lista, list):
                continue
            for it in lista:
                if not isinstance(it, dict) or "filename" not in it:
                    continue
                q = urllib.parse.urlencode({"filename": it["filename"], "subfolder": it.get("subfolder", ""),
                                            "type": it.get("type", "output")})
                ext = os.path.splitext(it["filename"])[1]
                dest = os.path.join(pasta, f"{nome}_{len(feitos) + 1}{ext}")
                with open(dest, "wb") as f:
                    f.write(_req("/view?" + q, timeout=300))
                feitos.append(dest)
    print(f"OK em {time.time() - t0:.0f} s:")
    for f in feitos:
        print("  ", f)
    return feitos


# ---------------------------------------------------------------- fluxos
def fluxo_imagem(texto, largura, altura, seed, n):
    m = cfg()["modelos"]
    f = workflow("z_image_turbo_api.json")
    f["1"]["inputs"]["unet_name"] = m["zimage_unet"]
    f["2"]["inputs"]["clip_name"] = m["zimage_clip"]
    f["3"]["inputs"]["vae_name"] = m["zimage_vae"]
    f["4"]["inputs"]["text"] = texto
    f["6"]["inputs"].update(width=largura, height=altura, batch_size=n)
    f["8"]["inputs"]["seed"] = seed
    return f


def fluxo_editar(imagens, texto, largura, altura, seed):
    """Qwen-Image-Edit 2511: ate 3 imagens de referencia (image 1, 2, 3 no texto)."""
    m = cfg()["modelos"]
    f = workflow("qwen_image_edit_2511_api.json")
    f["1"]["inputs"]["unet_name"] = m["qwen_unet"]
    f["2"]["inputs"]["clip_name"] = m["qwen_clip"]
    f["3"]["inputs"]["vae_name"] = m["qwen_vae"]
    f["8"]["inputs"]["lora_name"] = m["qwen_lora"]
    f["4"]["inputs"]["image"] = imagens[0]
    f["9"]["inputs"]["prompt"] = texto
    f["13"]["inputs"].update(width=largura, height=altura)
    f["14"]["inputs"]["seed"] = seed
    for i, im in enumerate(imagens[1:3], start=2):
        f[f"L{i}"] = {"class_type": "LoadImage", "inputs": {"image": im}}
        f[f"S{i}"] = {"class_type": "FluxKontextImageScale", "inputs": {"image": [f"L{i}", 0]}}
        f["9"]["inputs"][f"image{i}"] = [f"S{i}", 0]
        f["10"]["inputs"][f"image{i}"] = [f"S{i}", 0]
    return f


def fluxo_video(imagem, texto, largura, altura, segundos, seed, prefixo, fim=None):
    m = cfg()["modelos"]
    f = workflow("wan22_flf2v_api.json" if fim else "wan22_i2v_api.json")
    f["1"]["inputs"]["unet_name"] = m["wan_unet_high"]
    f["2"]["inputs"]["unet_name"] = m["wan_unet_low"]
    f["3"]["inputs"]["lora_name"] = m["wan_lora_high"]
    f["4"]["inputs"]["lora_name"] = m["wan_lora_low"]
    f["7"]["inputs"]["clip_name"] = m["wan_clip"]
    f["8"]["inputs"]["vae_name"] = m["wan_vae"]
    f["9"]["inputs"]["text"] = texto
    f["11"]["inputs"]["image"] = imagem
    if fim:
        f["18"]["inputs"]["image"] = fim
    # o Wan quer 4k+1 quadros (16 fps)
    quadros = int(round(segundos * 16 / 4)) * 4 + 1
    f["12"]["inputs"].update(width=largura, height=altura, length=quadros)
    f["13"]["inputs"]["noise_seed"] = seed
    f["17"]["inputs"]["filename_prefix"] = prefixo
    return f


# ---------------------------------------------------------------- ffmpeg (encadear e suavizar)
def _ffmpeg(args):
    exe = cfg()["ffmpeg"]
    if not shutil.which(exe) and not os.path.exists(exe):
        sys.exit("ffmpeg nao encontrado: instala-o ou define \"ffmpeg\" no config.json")
    subprocess.run([exe, "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


def ultimo_fotograma(video, dest=None):
    """Guarda o ultimo fotograma de um clip, para o plano seguinte comecar exatamente ali."""
    dest = dest or os.path.splitext(video)[0] + "_fim.png"
    _ffmpeg(["-sseof", "-0.5", "-i", video, "-update", "1", "-q:v", "1", dest])
    print("  ", dest)
    return dest


def suavizar(video, fps, largura, altura, dest=None):
    """Interpola de 16 para mais fps (minterpolate) e aumenta o tamanho. O clip cru a 16 fps parece aos solavancos."""
    dest = dest or os.path.splitext(video)[0] + f"_{fps}fps.mp4"
    filtro = f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
    if largura and altura:
        filtro += f",scale={largura}:{altura}:flags=lanczos"
    _ffmpeg(["-i", video, "-vf", filtro, "-c:v", "libx264", "-crf", "16", "-preset", "slow",
             "-pix_fmt", "yuv420p", "-an", dest])
    print("  ", dest)
    return dest


# ---------------------------------------------------------------- linha de comandos
def main():
    ap = argparse.ArgumentParser(description="Pipeline imagem -> edicao -> video no ComfyUI local")
    ap.add_argument("modo", choices=["imagem", "editar", "video", "ultimo-fotograma", "suavizar"])
    ap.add_argument("ficheiro", nargs="?", help="clip de entrada (ultimo-fotograma, suavizar)")
    ap.add_argument("--texto", help="descricao (em ingles costuma dar melhores resultados)")
    ap.add_argument("--img", action="append", help="imagem de entrada (em 'editar' podes repetir ate 3 vezes)")
    ap.add_argument("--fim", help="video: imagem final (usa primeira + ultima imagem)")
    ap.add_argument("--nome", default="resultado", help="nome base dos ficheiros de saida")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--n", type=int, default=1, help="imagem: quantas variantes de uma vez")
    ap.add_argument("--largura", type=int)
    ap.add_argument("--altura", type=int)
    ap.add_argument("--segundos", type=float, default=5)
    ap.add_argument("--fps", type=int, default=32, help="suavizar: fps finais")
    ap.add_argument("--config", help="caminho do config.json")
    a = ap.parse_args()

    global CFG
    CFG = carregar_config(a.config)
    tam = CFG["tamanhos"]

    if a.modo in ("imagem", "editar", "video") and not a.texto:
        ap.error("--texto e obrigatorio neste modo")
    if a.modo in ("editar", "video") and not a.img:
        ap.error("--img e obrigatorio neste modo")
    if a.modo in ("ultimo-fotograma", "suavizar") and not a.ficheiro:
        ap.error("indica o clip")

    if a.modo == "imagem":
        w, h = a.largura or tam["imagem"][0], a.altura or tam["imagem"][1]
        correr(fluxo_imagem(a.texto, w, h, a.seed, a.n), a.nome)
    elif a.modo == "editar":
        w, h = a.largura or tam["editar"][0], a.altura or tam["editar"][1]
        refs = [enviar_imagem(i) for i in a.img[:3]]
        correr(fluxo_editar(refs, a.texto, w, h, a.seed), a.nome)
    elif a.modo == "video":
        w, h = a.largura or tam["video"][0], a.altura or tam["video"][1]
        ini = enviar_imagem(a.img[0])
        fim = enviar_imagem(a.fim) if a.fim else None
        correr(fluxo_video(ini, a.texto, w, h, a.segundos, a.seed, CFG["prefixo_video"] + a.nome, fim), a.nome)
    elif a.modo == "ultimo-fotograma":
        ultimo_fotograma(a.ficheiro)
    elif a.modo == "suavizar":
        suavizar(a.ficheiro, a.fps, a.largura, a.altura)


if __name__ == "__main__":
    main()
