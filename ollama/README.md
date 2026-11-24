# Ollama: Qwen em português de Portugal (o nosso modelo "kcu")

Um [Modelfile](Modelfile) que pega no **Qwen 3.5 9B** e o obriga a responder em **português de Portugal**, com vocabulário de cá (ecrã, telemóvel, ficheiro, utilizador). Não há pesos novos: é o mesmo modelo com uma instrução de sistema e os parâmetros de amostragem recomendados.

## Criar o modelo

```sh
ollama pull qwen3.5:9b
ollama create qwen-pt -f Modelfile
ollama run qwen-pt "What is a GPU?"
```

A resposta vem em pt-PT, mesmo com a pergunta em inglês. Para outra língua, pede-a expressamente ("responde em inglês").

## Requisitos

- [Ollama](https://ollama.com) recente (as linhas `RENDERER` e `PARSER` precisam de uma versão que já suporte o Qwen 3.5; se a tua der erro, atualiza o Ollama).
- Cerca de **7–8 GB** de memória livre (VRAM numa placa NVIDIA, ou memória unificada num Mac com Apple Silicon) para o modelo de 9B com a quantização padrão.

## Usar a partir de outros programas

O Ollama tem uma API compatível com a OpenAI em `http://127.0.0.1:11434/v1`. Em qualquer cliente OpenAI, põe esse endereço, uma chave qualquer (ex.: `ollama`) e o modelo `qwen-pt`.

## Mudar o comportamento

- **Outro tom:** edita a linha `SYSTEM` e volta a correr `ollama create qwen-pt -f Modelfile`.
- **Mais previsível:** baixa `temperature` (ex.: `0.6`).
- **Outro tamanho:** troca `FROM qwen3.5:9b` por outra variante do Qwen 3.5 que caiba na tua máquina.
