"""Testa o servidor de transcricao com um ficheiro teu.

  python testar.py gravacao.mp3
  python testar.py video.mp4 --palavras --url http://127.0.0.1:8000 --chave A_TUA_CHAVE

So usa a biblioteca padrao do Python.
"""
import argparse
import json
import mimetypes
import os
import urllib.request
import uuid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ficheiro")
    ap.add_argument("--url", default=os.environ.get("TRANSCRICAO_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--chave", default=os.environ.get("TRANSCRICAO_API_KEY", ""))
    ap.add_argument("--idioma", default="pt")
    ap.add_argument("--palavras", action="store_true", help="pede tempos por palavra (verbose_json)")
    ap.add_argument("--formato", default=None, help="json, text, srt, vtt ou verbose_json")
    a = ap.parse_args()

    formato = a.formato or ("verbose_json" if a.palavras else "json")
    campos = [("model", "whisper-1"), ("language", a.idioma), ("response_format", formato)]
    if a.palavras:
        campos.append(("timestamp_granularities[]", "word"))

    lim = uuid.uuid4().hex
    corpo = b""
    for k, v in campos:
        corpo += f'--{lim}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    tipo = mimetypes.guess_type(a.ficheiro)[0] or "application/octet-stream"
    nome = os.path.basename(a.ficheiro)
    corpo += (f'--{lim}\r\nContent-Disposition: form-data; name="file"; filename="{nome}"\r\n'
              f"Content-Type: {tipo}\r\n\r\n").encode()
    with open(a.ficheiro, "rb") as f:
        corpo += f.read()
    corpo += f"\r\n--{lim}--\r\n".encode()

    cab = {"Content-Type": f"multipart/form-data; boundary={lim}"}
    if a.chave:
        cab["Authorization"] = f"Bearer {a.chave}"
    req = urllib.request.Request(a.url.rstrip("/") + "/v1/audio/transcriptions", data=corpo, headers=cab)
    with urllib.request.urlopen(req, timeout=3600) as r:
        resposta = r.read().decode("utf-8")
    try:
        print(json.dumps(json.loads(resposta), ensure_ascii=False, indent=2))
    except ValueError:
        print(resposta)


if __name__ == "__main__":
    main()
