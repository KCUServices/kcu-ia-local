# Pipeline ComfyUI: imagem → edição → vídeo

Um script (`pipeline.py`) que manda trabalho ao teu ComfyUI local pela API e descarrega os resultados para uma pasta tua. Três passos que se encadeiam:

1. **imagem**: Z-Image Turbo cria a imagem de partida (personagem, objeto, cenário).
2. **editar**: Qwen-Image-Edit 2511 põe essa personagem numa cena nova, mantendo-a igual (até 3 imagens de referência).
3. **video**: Wan 2.2 I2V anima a cena (clip de 5 s a 16 fps), opcionalmente com imagem final.

Mais duas ajudas com ffmpeg: `ultimo-fotograma` (para o plano seguinte começar onde o anterior acabou) e `suavizar` (passa o clip para 32 fps e aumenta o tamanho).

Requisitos, modelos e licenças estão no [README principal](../README.md#3-pipeline-comfyui).

## Ficheiros

| Ficheiro | Para quê |
|---|---|
| `pipeline.py` | O script (só biblioteca padrão do Python). |
| `config.exemplo.json` | Endereço do ComfyUI, pasta de saída, nomes dos modelos, tamanhos. Copia para `config.json` e muda o que precisares. |
| `workflows/z_image_turbo_api.json` | Fluxo de imagem (formato API). |
| `workflows/qwen_image_edit_2511_api.json` | Fluxo de edição (formato API). |
| `workflows/wan22_i2v_api.json` | Fluxo de vídeo a partir de uma imagem. |
| `workflows/wan22_flf2v_api.json` | Fluxo de vídeo com primeira e última imagem. |

Os fluxos estão em **formato API** (o que o ComfyUI envia para `/prompt`). Para os abrir no editor visual, arrasta o `.json` para a janela do ComfyUI; ele importa-os. Se mudares um fluxo, mantém os números dos nós, porque o script escreve nos nós pelo número.

## Exemplo completo

```sh
cp config.exemplo.json config.json

# 1. personagem (4 variantes, escolhe a melhor)
python pipeline.py imagem --nome robo --n 4 --texto "A small friendly red robot, full body, three-quarter view, plain light-grey studio background, high quality 3D render, no text."

# 2. a mesma personagem noutra cena
python pipeline.py editar --img saida/robo_2.png --nome cena1 --texto "Keep the robot from image 1 exactly the same. It stands in a sunny greenhouse full of plants, holding a small watering can. Vertical composition, same 3D style."

# 3. animar
python pipeline.py video --img saida/cena1_1.png --nome cena1 --texto "The robot waters the plants, then turns its head toward the camera and waves. Gentle camera push in."

# 4. encadear o plano seguinte no último fotograma
python pipeline.py ultimo-fotograma saida/cena1_1.mp4
python pipeline.py video --img saida/cena1_1_fim.png --nome cena2 --texto "The robot walks to the door and opens it."

# 5. suavizar para 32 fps e 1080x1920
python pipeline.py suavizar saida/cena1_1.mp4 --fps 32 --largura 1080 --altura 1920
```

Transformações (uma flor a abrir, um objeto a mudar) funcionam melhor com primeira **e** última imagem: cria a imagem final com `editar` e passa-a com `--fim`.

## Dicas

- Escreve as descrições em **inglês**: os três modelos respondem melhor.
- Para manter a personagem igual entre planos, usa sempre a mesma imagem de referência no `editar` ("must look exactly like the character in image 2").
- Muda só a `--seed` para ter outra versão do mesmo pedido.
- Os vídeos ficam também na pasta `output` do ComfyUI (`prefixo_video` no config). As imagens não: o fluxo usa `PreviewImage` e o script descarrega-as diretamente.
