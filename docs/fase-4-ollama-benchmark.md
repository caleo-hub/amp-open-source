# Fase 4 — Benchmark do Ollama no hardware atual

Data do registro: 2026-08-14

Este documento registra os resultados práticos obtidos durante a Fase 4 do AMP open source e define uma política inicial de uso de modelos locais no notebook.

## Hardware observado

- Notebook: Acer Aspire A515-51G
- Memória RAM: 20 GB
- GPU: NVIDIA GeForce MX130
- VRAM: 2 GB
- Driver NVIDIA: 580.173.02
- CUDA reportada pelo `nvidia-smi`: 13.0
- Ollama executando via `/usr/local/bin/ollama serve`
- Durante o teste, o processo `llama-server` do Ollama utilizou aproximadamente 858 MiB de VRAM.

## Modelos testados

### FAST

Modelo: `qwen3.5:2b-q4_K_M`

Configuração sugerida:

```text
think=false
num_predict=120~200
```

Desempenho observado:

- aproximadamente 12 tokens/s em uso prático;
- teste registrado com 85 tokens de saída;
- `total_duration`: 16,146 s;
- `load_duration`: 8,347 s;
- `prompt_eval_duration`: 0,668 s;
- `eval_duration`: 7,129 s.

Uso recomendado:

- consultar status de tarefas;
- resumir textos curtos e médios;
- classificar mensagens;
- extrair ou transformar informações simples;
- responder comandos cotidianos em que baixa latência é mais importante que raciocínio profundo.

### SMART

Modelo: `qwen3.5:4b`

Configuração sugerida:

```text
think=false
num_predict=200~400
```

Desempenho observado:

- aproximadamente 5,3 tokens/s em uso prático;
- teste registrado com 92 tokens de saída;
- `total_duration`: 26,821 s;
- `load_duration`: 7,887 s;
- `prompt_eval_duration`: 1,646 s;
- `eval_duration`: 17,285 s.

Uso recomendado:

- planejamento de tarefas;
- respostas que exigem mais contexto;
- síntese de alternativas;
- tarefas em que qualidade é mais importante que baixa latência.

### REASONING

Modelo: `qwen3.5:4b`

Configuração sugerida:

```text
think=true
```

O modo de raciocínio deve ser ativado apenas quando necessário, porque aumenta significativamente a latência e o custo computacional local.

Uso recomendado:

- comparar alternativas complexas;
- escolher uma estratégia entre várias opções;
- planejar soluções com múltiplas etapas;
- analisar problemas ambíguos ou que exigem raciocínio explícito.

## Política inicial de roteamento do AMP

A arquitetura do AMP não deve obrigar um único modelo a executar todas as tarefas.

```text
"Qual é o status desta tarefa?"
          ↓
     FAST / 2B

"Resuma este texto"
          ↓
     FAST / 2B

"Classifique esta mensagem"
          ↓
     FAST / 2B

"Planeje como resolver este problema"
          ↓
     SMART / 4B

"Analise essas alternativas e escolha a melhor"
          ↓
  REASONING / 4B + thinking
```

A decisão de arquitetura inicial é, portanto:

| Perfil | Modelo | Thinking | `num_predict` | Velocidade aproximada |
|---|---|---:|---:|---:|
| FAST | `qwen3.5:2b-q4_K_M` | false | 120–200 | ~12 tok/s |
| SMART | `qwen3.5:4b` | false | 200–400 | ~5,3 tok/s |
| REASONING | `qwen3.5:4b` | true | conforme necessidade | menor, variável |

## Observações sobre CPU/GPU

No instante inspecionado com `nvidia-smi`:

- GPU: NVIDIA GeForce MX130;
- memória usada: 867 MiB / 2048 MiB;
- processo de compute do Ollama (`llama-server`): aproximadamente 858 MiB;
- utilização instantânea da GPU no momento da consulta: 0%, o que é compatível com uma medição feita após a geração ter terminado.

O processo principal `ollama serve` apresentava cerca de 80 MiB de RSS. Esse número não representa sozinho toda a memória do modelo, pois a inferência ocorre no processo `llama-server` e pode usar RAM, memória mapeada e VRAM.

## Próximo benchmark desejado

Com 20 GB de RAM, ainda vale testar pelo menos um modelo quantizado na faixa de 7–9B.

Objetivo do teste:

- verificar se existe um perfil de maior qualidade aceitável para tarefas difíceis;
- aceitar, se necessário, algo na ordem de ~2–4 tokens/s;
- medir RAM, VRAM, estabilidade e tempo de resposta;
- comparar qualidade prática com o `qwen3.5:4b`.

Esse eventual modelo poderá futuramente compor um quarto perfil, por exemplo `DEEP`, sem substituir os perfis FAST e SMART.

## Conclusão da Fase 4

O hardware atual já é suficiente para uma arquitetura de agentes local com roteamento de modelos por complexidade. O ponto mais importante não é escolher um único modelo universal, e sim utilizar o modelo menor sempre que possível e escalar para modelos maiores apenas quando a tarefa justificar a latência adicional.

A Fase 5 deve partir dessa política e encapsular a chamada ao Ollama atrás de uma camada de seleção de perfil, mesmo que o primeiro grafo LangGraph comece com apenas um caminho simples.