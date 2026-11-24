# Changelog

Cada versão corresponde a um episódio da série (tag `epNN`).

## [ep00] Primeira versão pública: 2026-11-24

- **Transcrição:** servidor compatível com a API da OpenAI (`/v1/audio/transcriptions`) com faster-whisper e Whisper large-v3-turbo; tempos por palavra; respostas `json`, `text`, `srt`, `vtt` e `verbose_json`; liberta o ComfyUI e o Ollama antes de carregar e sai da placa quando fica parado.
- **Ollama:** Modelfile que põe o Qwen 3.5 9B a responder em português de Portugal (o nosso modelo "kcu").
- **Pipeline ComfyUI:** `pipeline.py` com os passos `imagem` (Z-Image Turbo), `editar` (Qwen-Image-Edit 2511), `video` (Wan 2.2 I2V, com primeira e última imagem opcionais), `ultimo-fotograma` e `suavizar`; quatro fluxos em formato API.
