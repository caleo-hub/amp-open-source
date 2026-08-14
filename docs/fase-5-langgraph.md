# Fase 5 — Primeiro fluxo com LangGraph

Data de conclusão: 2026-08-14

## Objetivo

Construir o primeiro agente local do AMP usando LangGraph como runtime de orquestração, Ollama como servidor de modelos e uma ferramenta local real.

## Resultado

A fase foi concluída com um agente de terminal capaz de:

- receber mensagens do usuário;
- usar um modelo FAST como router;
- escolher entre os perfis FAST e SMART;
- executar o grafo com arestas condicionais;
- permitir tool calling no caminho FAST;
- consultar o estado real do servidor por meio de uma ferramenta `system_status`;
- retornar ao modelo após a tool para interpretar os dados;
- medir o tempo total de cada execução.

## Arquitetura implementada

```text
START
  |
  v
router (qwen3.5:2b-q4_K_M)
  |
  +-------------------+
  |                   |
  v                   v
FAST                 SMART
2B                   4B
think=false          think=false
  |                   |
  v                   v
tool call?            END
  |
  +--- nao ----------> END
  |
  +--- sim
       |
       v
   system_status
       |
       v
      FAST
       |
       v
      END
```

## Perfis de modelo

### Router

- modelo: `qwen3.5:2b-q4_K_M`
- `think=false`
- `num_predict=5`
- responsabilidade: responder apenas `fast` ou `smart`

### FAST

- modelo: `qwen3.5:2b-q4_K_M`
- `think=false`
- `num_predict=160`
- benchmark anterior: aproximadamente 12 tok/s
- responsabilidade: conversa simples, perguntas diretas, classificação, resumo, extração e chamadas de ferramentas

### SMART

- modelo: `qwen3.5:4b`
- `think=false`
- sem limite de `num_predict` fixado na configuração final desta fase
- benchmark anterior: aproximadamente 5,3 tok/s
- responsabilidade: planejamento, comparação, arquitetura e análise com múltiplas etapas

O modo `reasoning=true` foi removido do fluxo normal nesta fase porque, nos testes, o modelo 4B chegou a consumir todo o orçamento de geração em `reasoning_content` sem produzir `content` final. Ele poderá retornar futuramente como um nível de escalonamento raro.

## Estado do LangGraph

O estado mínimo contém:

- `messages`: histórico de mensagens que percorre o grafo;
- `profile`: perfil selecionado pelo router (`fast` ou `smart`).

O reducer `add_messages` é usado para acumular mensagens produzidas pelos nós e pelas ferramentas.

## Nós implementados

- `router`: classifica a tarefa como FAST ou SMART;
- `fast`: executa o modelo 2B e pode solicitar ferramentas;
- `smart`: executa o modelo 4B sem thinking;
- `tools`: `ToolNode` responsável por executar as ferramentas solicitadas pelo modelo.

## Arestas condicionais

Duas decisões principais existem no grafo:

1. `router -> fast | smart`
2. `fast -> tools | END`

Após a execução de uma ferramenta, o fluxo volta para `fast`, permitindo que o modelo interprete o resultado antes de encerrar.

## Ferramenta implementada

### `system_status`

A ferramenta consulta informações reais do servidor AMP e retorna dados de:

- memória RAM;
- armazenamento;
- processo do Ollama;
- GPU NVIDIA via `nvidia-smi`.

A ferramenta usa comandos locais controlados e não recebe comandos arbitrários do modelo.

## Teste final da fase

Entrada:

```text
como está o servidor?
```

Fluxo observado:

```text
[router] perfil escolhido: fast
[model] FAST -> qwen3.5:2b-q4_K_M
[tool] chamadas solicitadas: 1
[model] FAST -> qwen3.5:2b-q4_K_M
```

O agente retornou uma resposta baseada em dados reais do notebook, incluindo RAM, disco, GPU e processo do Ollama.

Tempo total observado nessa execução: aproximadamente 34,88 s.

## Conceitos de LangGraph aprendidos nesta fase

- estado;
- reducers de estado;
- nós;
- arestas;
- arestas condicionais;
- tool calling;
- `ToolNode`;
- retorno de uma ferramenta para o modelo;
- separação entre runtime de agentes e servidor de modelo.

## Critério de pronto

A Fase 5 é considerada concluída porque já é possível explicar e demonstrar claramente:

- o que pertence ao LangGraph;
- o que pertence ao Ollama;
- como o estado percorre o grafo;
- como o router decide uma transição;
- como uma ferramenta é solicitada e executada;
- como o resultado da ferramenta volta ao LLM antes da resposta final.

## Próximo passo

A Fase 6 deverá colocar esse agente atrás de uma API FastAPI, começando com endpoints de saúde e conversa e preservando inicialmente o grafo atual sem adicionar novas capacidades.