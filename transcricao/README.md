# Transcrição local (Whisper)

Servidor que transcreve áudio e vídeo no teu PC, com a mesma API da OpenAI (`POST /v1/audio/transcriptions`). Qualquer programa que fale com a OpenAI (n8n, scripts, apps) pode usá-lo: basta trocar o endereço base para `http://127.0.0.1:8000/v1`.

Mais detalhes (requisitos, instalação, definições) no [README principal](../README.md#1-transcrição-local).

## Ficheiros

| Ficheiro | Para quê |
|---|---|
| `servidor_transcricao.py` | O servidor (FastAPI + faster-whisper). |
| `requirements.txt` | Dependências Python. |
| `iniciar.ps1` | Arranca no Windows e guarda os registos em `servidor.out.log` / `servidor.err.log`. |
| `iniciar.sh` | Arranca no Linux / macOS. |
| `testar.py` | Envia um ficheiro teu e mostra a resposta. |

## Arranque rápido

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.\iniciar.ps1
# noutra janela:
.venv\Scripts\python testar.py gravacao.mp3 --palavras
```

## Variáveis de ambiente

| Variável | Padrão | O que faz |
|---|---|---|
| `TRANSCRICAO_HOST` | `127.0.0.1` | Onde escuta. `0.0.0.0` só com chave e atrás de VPN/firewall. |
| `TRANSCRICAO_PORTA` | `8000` | Porta. |
| `TRANSCRICAO_API_KEY` | *(vazio)* | Se definida, exige `Authorization: Bearer <chave>`. |
| `TRANSCRICAO_MODELO` | `large-v3-turbo` | Modelo do faster-whisper (ou pasta local com um modelo CTranslate2). |
| `TRANSCRICAO_DISPOSITIVO` | `cuda` | `cuda` ou `cpu`. |
| `TRANSCRICAO_PRECISAO` | `float16` | `float16` na GPU; `int8` no CPU. |
| `TRANSCRICAO_IDIOMA` | *(deteta)* | Idioma padrão, ex.: `pt`. |
| `TRANSCRICAO_IDLE_SEGUNDOS` | `300` | Tira o modelo da placa ao fim deste tempo sem pedidos. |
| `TRANSCRICAO_PRECISA_GB` | `3.0` | VRAM livre que tenta garantir antes de carregar. |
| `TRANSCRICAO_COMFY_URL` | `http://127.0.0.1:8188` | ComfyUI a libertar (se não existir, ignora). |
| `TRANSCRICAO_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama a descarregar (se não existir, ignora). |
| `TRANSCRICAO_COMFY_ESPERA_MAX` | `1800` | Quanto tempo espera, no máximo, que o ComfyUI acabe um trabalho. |
| `TRANSCRICAO_FFMPEG` | `ffmpeg` do PATH | Caminho do ffmpeg. |

## Formatos de resposta

`response_format` aceita `json` (padrão), `text`, `srt`, `vtt` e `verbose_json`. Com `verbose_json` e `timestamp_granularities[]=word` recebes também a lista `words` com `start`/`end` de cada palavra (útil para legendas palavra a palavra e cortes de vídeo).
