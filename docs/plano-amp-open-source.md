# Plano humano para construir uma AMP open source no seu notebook

> Um projeto progressivo de hobby e aprendizado para transformar um notebook em uma **Agent Management Platform (AMP)** self-hosted, começando do zero com Ubuntu.

## 1. Visão do projeto

O objetivo é construir, aos poucos, uma plataforma pessoal capaz de:

- executar agentes de IA localmente;
- chamar modelos locais pelo Ollama;
- pesquisar na web pelo SearXNG;
- manter estado, histórico e memória;
- acompanhar execuções e erros;
- coordenar mais de um agente;
- controlar usuários, ferramentas e permissões;
- oferecer uma interface web simples;
- futuramente receber comandos por voz, inclusive por Alexa.

Este não é um projeto para reproduzir toda a infraestrutura de uma grande empresa. É um laboratório doméstico que poderá crescer conforme você aprende e identifica necessidades reais.

## 2. A distinção mais importante

**LangGraph é o runtime/orquestrador dos agentes; ele não é a plataforma inteira.**

Ele ajuda a definir fluxos, estado, nós, decisões, checkpoints, retomadas e interação humana. A AMP completa surgirá da combinação de vários componentes:

```text
Usuário / Alexa futura
        |
        v
Interface web
        |
        v
FastAPI — API e plano de controle
        |
        v
LangGraph — runtime e orquestração
   |         |          |
   v         v          v
Ollama    SearXNG    Ferramentas
   |                    |
   +----------+---------+
              v
      Persistência e logs
```

Uma divisão mental útil:

- **Ollama:** serve os modelos locais.
- **LangGraph:** organiza a lógica e o estado dos agentes.
- **FastAPI:** expõe a plataforma por uma API.
- **SearXNG:** fornece pesquisa web self-hosted.
- **Banco de dados:** guarda agentes, execuções, checkpoints e configurações.
- **Observabilidade:** mostra o que aconteceu e onde falhou.
- **UI:** permite operar o sistema sem depender do terminal.
- **Camada de segurança:** decide quem pode fazer o quê.

## 3. Princípios para não transformar o hobby em sofrimento

1. Faça uma fase por vez.
2. Termine uma versão pequena antes de adicionar infraestrutura.
3. Use um único notebook e um único usuário no início.
4. Prefira componentes substituíveis e configurações simples.
5. Documente comandos e decisões enquanto aprende.
6. Faça backup antes de mudanças importantes.
7. Só adicione uma tecnologia quando ela resolver um problema que você já sentiu.
8. Considere cada fase um projeto independente e comemorável.

## 4. Arquitetura-alvo, sem obrigação de construí-la toda

| Camada | Componente inicial | Responsabilidade |
|---|---|---|
| Sistema | Ubuntu Server LTS | Base do notebook-servidor |
| Contêineres | Docker + Compose | Instalação e isolamento de serviços |
| Modelos | Ollama | Inferência local |
| Orquestração | LangGraph | Fluxos, estado e agentes |
| API | FastAPI | Endpoints, validação e controle |
| Pesquisa | SearXNG | Busca web privada/self-hosted |
| Persistência | SQLite, depois PostgreSQL | Configurações, histórico e checkpoints |
| Filas | Processo local, depois Redis se necessário | Trabalhos assíncronos |
| Observabilidade | Logs estruturados; métricas depois | Diagnóstico e acompanhamento |
| Interface | UI web pequena | Operação cotidiana |
| Voz | Serviço intermediário + Alexa | Entrada e resposta por voz |

## 5. Ritmo sugerido

Não existe prazo obrigatório. Um ritmo confortável seria uma sessão de 1 a 3 horas por semana.

| Bloco | Fases | Resultado visível |
|---|---|---|
| Fundação | 0 a 3 | Notebook com Ubuntu, Docker e modelo local |
| Primeiro produto | 4 a 7 | Agente web acessível por API e com histórico |
| Plataforma | 8 a 11 | Monitoramento, multiagentes, permissões e UI |
| Expansão | 12 e 13 | Operação confiável e preparação para Alexa |

Pare ao fim de qualquer fase se o sistema já estiver atendendo ao que você quer. Crescer é opcional.

---

# Fase 0 — Preparação e decisões mínimas

## Objetivo

Preparar o notebook e reduzir o risco de perder dados ou escolher uma instalação inadequada.

## Tarefas

- [ ] Anotar marca, modelo, processador, memória RAM, armazenamento e presença de GPU.
- [ ] Verificar se o notebook possui pelo menos cerca de 8 GB de RAM; 16 GB ou mais dará mais liberdade para modelos locais.
- [ ] Copiar todos os arquivos pessoais para outro dispositivo ou serviço de backup.
- [ ] Testar se o backup realmente abre em outro computador.
- [ ] Escolher entre instalação dedicada ou dual boot.
- [ ] Separar um pendrive de pelo menos 8 GB para o instalador.
- [ ] Definir um nome simples para o servidor, por exemplo `jarvis` ou `amp-lab`.
- [ ] Criar um caderno de laboratório, como `diario.md`, para registrar decisões, erros e soluções.

## Entregável

Uma pequena ficha do equipamento, backup verificado e decisão sobre o tipo de instalação.

## Critério de pronto

Você consegue responder: “Se eu apagar o disco agora, meus arquivos importantes continuam seguros?”

## O que aprender

- diferença entre RAM, armazenamento, CPU e GPU;
- diferença entre instalação dedicada, máquina virtual e dual boot;
- importância de backup e recuperação.

## Não fazer ainda

- comprar GPU ou equipamento novo sem testar o que o notebook já consegue fazer;
- montar cluster;
- decidir Kubernetes, banco vetorial ou arquitetura de microserviços;
- expor o notebook à internet.

---

# Fase 1 — Instalar o Ubuntu

## Objetivo

Transformar o notebook em uma base Linux estável e acessível pela rede local.

## Escolha sugerida

Use uma versão **Ubuntu Server LTS** suportada. A edição Server consome menos recursos; se você preferir aprender com interface gráfica, Ubuntu Desktop LTS também funciona.

## Tarefas

- [ ] Baixar a imagem oficial do Ubuntu LTS.
- [ ] Verificar a integridade da imagem conforme as instruções oficiais.
- [ ] Criar o pendrive inicializável.
- [ ] Iniciar o notebook pelo pendrive e instalar o Ubuntu.
- [ ] Durante a instalação, criar um usuário comum, não trabalhar diariamente como `root`.
- [ ] Habilitar OpenSSH se o instalador oferecer essa opção.
- [ ] Aplicar as atualizações do sistema após o primeiro login.
- [ ] Conferir data, fuso horário e layout de teclado.
- [ ] Descobrir o endereço IP do notebook na rede local.
- [ ] Acessá-lo por SSH a partir do seu computador principal.
- [ ] Configurar o notebook para não suspender ao fechar a tampa, caso ele vá operar fechado.

## Entregável

Ubuntu funcionando e login remoto por SSH dentro da rede local.

## Critério de pronto

Você reinicia o notebook e consegue acessá-lo novamente por SSH sem conectar monitor ou teclado.

## O que aprender

- terminal e estrutura básica de diretórios do Linux;
- usuários, grupos e permissões;
- atualização de pacotes;
- endereço IP, rede local e SSH;
- serviços iniciados junto com o sistema.

## Não fazer ainda

- liberar portas no roteador;
- ativar login SSH do usuário `root`;
- instalar muitos pacotes “para usar depois”;
- mudar dezenas de configurações de segurança sem entender como recuperar o acesso.

---

# Fase 2 — Criar a base do servidor

## Objetivo

Organizar o sistema para que seja fácil operar, atualizar e recuperar.

## Tarefas

- [ ] Reservar um endereço IP estável pelo roteador ou configurar uma reserva DHCP.
- [ ] Criar uma pasta única para o laboratório, por exemplo `/opt/amp` ou uma pasta dentro do diretório do usuário.
- [ ] Planejar subpastas para aplicação, dados, configuração e backups.
- [ ] Instalar somente utilitários essenciais, como Git, editor de texto e ferramentas de diagnóstico.
- [ ] Ativar um firewall local e liberar inicialmente apenas SSH na rede confiável.
- [ ] Configurar atualizações automáticas de segurança, se estiver confortável com isso.
- [ ] Registrar como restaurar o acesso caso a rede ou o firewall sejam configurados incorretamente.
- [ ] Criar uma rotina simples de backup das configurações e dados do projeto.

Estrutura inicial sugerida:

```text
amp/
├── app/          # código da plataforma
├── compose/      # definições dos serviços
├── config/       # exemplos de configuração sem segredos
├── data/         # volumes persistentes
├── backups/      # cópias locais temporárias
└── docs/         # diário e decisões
```

## Entregável

Servidor organizado, atualizado, protegido na rede local e com uma pasta de projeto conhecida.

## Critério de pronto

Você sabe onde ficam o código, os dados e os backups e consegue explicar quais portas estão abertas.

## O que aprender

- serviços de sistema;
- firewall e portas;
- persistência de dados;
- diferença entre código, configuração e segredo;
- estratégia básica de backup.

## Não fazer ainda

- usar domínio público;
- instalar proxy reverso, certificados ou VPN sem uma necessidade concreta;
- automatizar tudo com ferramentas avançadas de infraestrutura.

---

# Fase 3 — Docker e primeiro serviço

## Objetivo

Aprender a iniciar, parar, atualizar e preservar os dados de um serviço em contêiner.

## Tarefas

- [ ] Instalar Docker Engine e o recurso Docker Compose seguindo a documentação oficial.
- [ ] Permitir que seu usuário opere o Docker conforme o método recomendado.
- [ ] Executar um contêiner de teste.
- [ ] Criar um arquivo Compose pequeno para um serviço simples.
- [ ] Praticar iniciar, parar, visualizar logs e recriar o serviço.
- [ ] Criar um volume persistente e confirmar que os dados sobrevivem à recriação do contêiner.
- [ ] Definir uma política de reinício apropriada.
- [ ] Registrar a versão das imagens em vez de depender sempre da etiqueta `latest`.

## Entregável

Um serviço de teste gerenciado por Compose e um roteiro pessoal com as operações mais comuns.

## Critério de pronto

Você consegue reiniciar o servidor, confirmar que o serviço voltou e encontrar seus logs.

## O que aprender

- imagem, contêiner, porta, rede e volume;
- diferença entre apagar um contêiner e apagar seus dados;
- arquivo Compose;
- logs e ciclo de vida de serviços.

## Não fazer ainda

- Kubernetes;
- Swarm;
- dezenas de contêineres;
- imagens próprias complexas antes de compreender as imagens oficiais.

---

# Fase 4 — Ollama e primeiro modelo local

## Objetivo

Executar um modelo de linguagem local e descobrir os limites reais do notebook.

## Tarefas

- [ ] Instalar o Ollama de forma nativa ou em contêiner; escolha apenas uma abordagem.
- [ ] Baixar um modelo pequeno, compatível com a RAM disponível.
- [ ] Fazer uma conversa simples pelo terminal.
- [ ] Chamar a API local do Ollama.
- [ ] Medir, sem obsessão, tempo de primeira resposta e uso de memória.
- [ ] Testar um segundo modelo somente para comparar velocidade e qualidade.
- [ ] Anotar qual modelo será o padrão inicial.
- [ ] Confirmar que o Ollama inicia após reiniciar o notebook.

## Entregável

Um modelo local respondendo por API e uma nota curta sobre desempenho e consumo de memória.

## Critério de pronto

Uma requisição local recebe uma resposta reproduzível sem depender de API externa.

## O que aprender

- modelo, parâmetros e quantização;
- contexto e tokens;
- inferência em CPU e GPU;
- limites de memória e latência;
- diferença entre servidor de modelo e agente.

## Não fazer ainda

- baixar muitos modelos grandes;
- fazer fine-tuning;
- comprar hardware antes de medir sua carga real;
- manter vários modelos carregados ao mesmo tempo sem necessidade.

---

# Fase 5 — Primeiro fluxo com LangGraph

## Objetivo

Criar o menor agente possível e compreender o papel do LangGraph.

## Tarefas

- [ ] Criar um ambiente Python isolado.
- [ ] Criar um projeto Git local.
- [ ] Instalar LangGraph e apenas as dependências necessárias para conversar com o Ollama.
- [ ] Definir um estado mínimo, inicialmente apenas mensagens.
- [ ] Criar um grafo com um nó que chama o modelo.
- [ ] Compilar e executar o grafo pelo terminal.
- [ ] Adicionar uma ferramenta fictícia ou uma calculadora simples.
- [ ] Registrar entradas, saídas e erros.
- [ ] Escrever um teste simples para uma execução previsível.

Fluxo inicial:

```text
Entrada -> nó do modelo -> resposta -> fim
```

Depois:

```text
Entrada -> modelo -> precisa de ferramenta?
                       | sim -> ferramenta -> modelo
                       | não ----------------> fim
```

## Entregável

Um agente de terminal que usa o Ollama e, quando apropriado, chama uma ferramenta simples.

## Critério de pronto

Você consegue explicar o estado do grafo, seus nós, as transições e onde o Ollama participa.

## O que aprender

- estado, nó, aresta e condição;
- chamada de ferramentas;
- separação entre modelo e orquestrador;
- tratamento de falhas;
- testes básicos de fluxos de agente.

## Não fazer ainda

- criar uma “equipe” de agentes;
- adicionar memória vetorial;
- construir um sistema genérico de plugins;
- criar grafos dinâmicos editáveis pela UI.

---

# Fase 6 — FastAPI como porta de entrada

## Objetivo

Transformar o agente de terminal em um serviço utilizável por outras aplicações.

## Tarefas

- [ ] Criar uma aplicação FastAPI pequena.
- [ ] Implementar um endpoint de saúde, como `/health`.
- [ ] Implementar um endpoint de conversa, como `/chat`.
- [ ] Validar entrada e saída com modelos de dados.
- [ ] Retornar erros claros sem expor detalhes sensíveis.
- [ ] Adicionar um identificador para cada execução.
- [ ] Criar um contêiner para a aplicação.
- [ ] Adicionar a API ao Compose.
- [ ] Testar a documentação interativa gerada pela própria API.

Contrato inicial sugerido:

```json
POST /chat
{
  "message": "Qual é a capital do Chile?",
  "thread_id": "teste-001"
}
```

## Entregável

Uma API local que recebe uma mensagem, executa o grafo e devolve resposta e identificador da execução.

## Critério de pronto

Outro computador na mesma rede consegue consultar `/health` e enviar uma mensagem para `/chat`.

## O que aprender

- HTTP, JSON, rotas e códigos de status;
- validação de dados;
- diferença entre API e runtime;
- empacotamento da aplicação;
- configuração por variáveis de ambiente.

## Não fazer ainda

- publicar a API diretamente na internet;
- criar dezenas de endpoints;
- implementar streaming antes de o fluxo comum estar estável;
- gerar SDKs ou compatibilidade com muitos clientes.

---

# Fase 7 — SearXNG e primeiro agente web

## Objetivo

Permitir que o agente faça pesquisas web sem acoplar o projeto a uma única ferramenta comercial.

## Tarefas

- [ ] Subir uma instância de SearXNG pelo Compose.
- [ ] Mantê-la acessível somente pela rede local ou pela rede interna dos contêineres.
- [ ] Testar uma pesquisa manualmente.
- [ ] Criar no agente uma ferramenta `pesquisar_web`.
- [ ] Limitar quantidade de resultados, tamanho do texto e tempo de espera.
- [ ] Ensinar o fluxo a usar busca apenas quando a pergunta exigir informação externa ou atual.
- [ ] Fazer a resposta indicar quais páginas foram consultadas.
- [ ] Tratar indisponibilidade, resultado vazio e conteúdo inválido.
- [ ] Criar um pequeno conjunto de perguntas de teste.

Fluxo:

```text
Pergunta
   |
   v
Decidir se precisa pesquisar
   | não                  | sim
   v                      v
Responder           Consultar SearXNG
                           |
                           v
                  Resumir com referências
```

## Entregável

Um agente acessível pela API que decide quando pesquisar e retorna uma resposta com referências.

## Critério de pronto

O agente responde corretamente a pelo menos:

- uma pergunta que não exige pesquisa;
- uma pergunta atual que exige pesquisa;
- uma pesquisa sem resultado;
- uma situação em que o SearXNG está fora do ar.

## O que aprender

- ferramentas externas;
- dados não confiáveis vindos da web;
- timeouts, limites e tratamento de erro;
- diferença entre pesquisar, extrair e responder;
- noção inicial de prompt injection em conteúdo externo.

## Não fazer ainda

- permitir navegação irrestrita ou execução de código sugerido por páginas;
- raspar sites em grande escala;
- criar dezenas de ferramentas;
- confiar automaticamente em qualquer resultado encontrado.

---

# Fase 8 — Persistência e histórico

## Objetivo

Fazer conversas e execuções sobreviverem a reinícios.

## Estratégia progressiva

Comece com **SQLite** se houver apenas um processo e uso pessoal. Migre para **PostgreSQL** quando concorrência, administração ou outros serviços justificarem a mudança.

## Tarefas

- [ ] Definir as entidades mínimas: agente, conversa, execução e mensagem.
- [ ] Configurar checkpoints persistentes do LangGraph.
- [ ] Salvar horário, estado, resultado e erro de cada execução.
- [ ] Criar endpoints para listar conversas e consultar uma execução.
- [ ] Definir por quanto tempo os dados serão mantidos.
- [ ] Criar um backup manual e restaurá-lo em um ambiente de teste.
- [ ] Separar dados de usuário de logs técnicos.
- [ ] Evitar guardar prompts ou segredos desnecessários.

Modelo conceitual mínimo:

```text
Agente 1 ---- N Conversas
Conversa 1 -- N Execuções
Execução 1 -- N Eventos
Conversa 1 -- N Mensagens
```

## Entregável

Histórico e checkpoints persistentes, com restauração testada.

## Critério de pronto

Depois de reiniciar todos os serviços, você consegue abrir uma conversa anterior e continuar do estado esperado.

## O que aprender

- modelo de dados;
- transações e migrações;
- checkpoint versus memória de longo prazo;
- retenção, backup e restauração;
- concorrência básica.

## Não fazer ainda

- adicionar banco vetorial apenas porque agentes costumam usar RAG;
- salvar todo conteúdo indefinidamente;
- criar um data lake;
- migrar para PostgreSQL antes de SQLite realmente limitar o projeto.

---

# Fase 9 — Observabilidade útil

## Objetivo

Conseguir responder: “O que aconteceu nesta execução e por que ela falhou?”

## Tarefas

- [ ] Produzir logs estruturados com horário, nível e identificador da execução.
- [ ] Registrar início e fim de cada nó do grafo.
- [ ] Medir duração da execução e das chamadas ao modelo e às ferramentas.
- [ ] Registrar modelo utilizado e, quando disponível, uso aproximado de tokens.
- [ ] Ocultar senhas, tokens, cookies e outros segredos.
- [ ] Criar uma tela ou endpoint simples de últimas execuções.
- [ ] Definir um limite de retenção e rotação de logs.
- [ ] Simular uma falha e confirmar que é possível diagnosticá-la.

Evolução opcional, somente depois que logs simples forem insuficientes:

- métricas com Prometheus;
- painéis com Grafana;
- rastreamento distribuído com OpenTelemetry;
- ferramenta especializada de observabilidade de LLMs.

## Entregável

Uma visão simples de execuções recentes, duração, sucesso ou falha e ponto do erro.

## Critério de pronto

Dado um identificador de execução, você encontra sua linha do tempo sem precisar adivinhar o que ocorreu.

## O que aprender

- logs, métricas e traces;
- correlação por identificador;
- latência e gargalos;
- privacidade em telemetria;
- diferença entre observabilidade e simples impressão no terminal.

## Não fazer ainda

- instalar uma grande pilha de monitoramento antes de produzir bons eventos;
- guardar o conteúdo completo de todas as conversas nos logs;
- criar painéis para métricas que ainda não orientam nenhuma decisão.

---

# Fase 10 — Multiagentes com propósito

## Objetivo

Adicionar um segundo papel somente onde a separação trouxer benefício mensurável.

## Experimento sugerido

Criar dois papéis:

1. **Pesquisador:** coleta e organiza fontes.
2. **Redator:** produz a resposta usando apenas o material coletado.

O supervisor pode ser apenas uma regra explícita no grafo, não necessariamente outro LLM.

## Tarefas

- [ ] Escrever a responsabilidade e os limites de cada agente em poucas linhas.
- [ ] Definir o formato exato da saída do pesquisador.
- [ ] Definir o formato exato da entrada do redator.
- [ ] Construir o fluxo no LangGraph.
- [ ] Estabelecer número máximo de passos e tentativas.
- [ ] Impedir ciclos infinitos.
- [ ] Comparar o resultado com o agente único usando as mesmas perguntas.
- [ ] Manter a versão multiagente somente se melhorar qualidade, auditabilidade ou manutenção.

## Entregável

Um fluxo pesquisador → redator com limites explícitos e comparação documentada com a versão de agente único.

## Critério de pronto

Você consegue demonstrar uma vantagem concreta do segundo agente e acompanhar cada etapa separadamente.

## O que aprender

- decomposição de tarefas;
- contratos entre agentes;
- roteamento e supervisão;
- limites de custo, tempo e iterações;
- avaliação comparativa.

## Não fazer ainda

- criar agentes com cargos humanos apenas por estética;
- permitir conversas ilimitadas entre agentes;
- montar um marketplace de agentes;
- usar multiagentes para tarefas que uma função determinística resolveria melhor.

---

# Fase 11 — Segurança e permissões

## Objetivo

Controlar acesso à plataforma e reduzir o impacto de ferramentas perigosas.

## Tarefas

- [ ] Criar autenticação simples para a API e a UI.
- [ ] Definir inicialmente dois papéis: administrador e usuário.
- [ ] Associar cada ferramenta a permissões explícitas.
- [ ] Classificar ferramentas por risco: leitura, escrita, ação externa e administração.
- [ ] Exigir confirmação humana antes de ações com efeito externo ou destrutivo.
- [ ] Manter segredos fora do Git e fora das imagens de contêiner.
- [ ] Usar contas de serviço com o menor privilégio possível.
- [ ] Limitar tamanho de entrada, tempo de execução e quantidade de chamadas.
- [ ] Manter serviços internos sem portas públicas desnecessárias.
- [ ] Registrar eventos administrativos em uma trilha de auditoria.
- [ ] Revisar backups para garantir que segredos não estejam sendo copiados sem proteção.

Política mínima sugerida:

| Tipo de ferramenta | Exemplo | Regra inicial |
|---|---|---|
| Leitura local | Consultar histórico | Permitida ao dono |
| Leitura externa | Pesquisar na web | Permitida com limites |
| Escrita local | Alterar configuração | Apenas administrador |
| Ação externa | Enviar mensagem | Confirmação humana |
| Destrutiva | Apagar dados | Bloqueada ou dupla confirmação |

## Entregável

Login local, papéis básicos e política explícita para ferramentas.

## Critério de pronto

Um usuário comum não consegue executar uma ferramenta administrativa, e uma ação externa sensível fica aguardando aprovação.

## O que aprender

- autenticação versus autorização;
- menor privilégio;
- gestão de segredos;
- auditoria;
- ameaça de prompt injection e limites de confiança.

## Não fazer ainda

- criar um sistema corporativo completo de identidade;
- escrever criptografia própria;
- permitir shell genérico, acesso irrestrito a arquivos ou comandos administrativos ao LLM;
- considerar o sistema seguro apenas porque está dentro de um contêiner.

---

# Fase 12 — Interface web da AMP

## Objetivo

Operar a plataforma no navegador sem transformar a UI em outro grande projeto.

## Telas mínimas

1. **Chat:** conversar com um agente.
2. **Agentes:** listar agentes e ver sua descrição.
3. **Execuções:** consultar status, duração e erros.
4. **Aprovações:** aceitar ou recusar ações sensíveis.
5. **Configurações:** escolher modelo e limites básicos.

## Tarefas

- [ ] Escolher a abordagem mais familiar: página simples, framework leve ou UI Python para protótipo.
- [ ] Construir primeiro somente a tela de chat.
- [ ] Exibir claramente quando o sistema está pensando, pesquisando ou aguardando aprovação.
- [ ] Adicionar a lista de execuções.
- [ ] Adicionar visualização simples da linha do tempo de uma execução.
- [ ] Adicionar aprovações humanas.
- [ ] Tratar estados vazio, carregando, indisponível e erro.
- [ ] Tornar a interface utilizável no celular dentro da rede local.
- [ ] Evitar mostrar raciocínio interno; mostrar eventos operacionais e resultados de ferramentas.

## Entregável

Uma UI local que permite conversar, acompanhar execuções e aprovar ações.

## Critério de pronto

Uma pessoa da casa consegue usar o agente pelo navegador sem receber instruções de terminal.

## O que aprender

- interação entre frontend e API;
- estados de carregamento e erro;
- streaming, se ele for adicionado nesta fase;
- experiência de aprovação humana;
- desenho de produto focado no essencial.

## Não fazer ainda

- editor visual de grafos;
- sistema de temas complexo;
- construtor no-code completo;
- aplicativo móvel nativo;
- dezenas de telas administrativas.

---

# Fase 13 — Operação doméstica confiável

## Objetivo

Fazer a AMP sobreviver ao uso cotidiano, a reinícios e a pequenas falhas.

## Tarefas

- [ ] Confirmar reinício automático dos serviços necessários.
- [ ] Criar verificações de saúde para API, banco, Ollama e SearXNG.
- [ ] Definir ordem ou tolerância de inicialização entre serviços.
- [ ] Testar falta de internet, modelo indisponível e banco temporariamente fora do ar.
- [ ] Automatizar backups em periodicidade apropriada.
- [ ] Realizar uma restauração completa em teste.
- [ ] Criar uma rotina mensal curta de atualização.
- [ ] Antes de atualizar, ler notas de versão e criar backup.
- [ ] Documentar como iniciar, parar, atualizar e recuperar a plataforma.
- [ ] Monitorar temperatura e espaço em disco do notebook.

## Entregável

Manual doméstico de operação e recuperação, com backup restaurado pelo menos uma vez.

## Critério de pronto

Após uma reinicialização inesperada, a plataforma volta sem intervenção ou apresenta um diagnóstico claro e recuperável.

## O que aprender

- saúde e disponibilidade;
- dependências entre serviços;
- atualização com baixo risco;
- recuperação de desastre em pequena escala;
- manutenção de longo prazo.

## Não fazer ainda

- alta disponibilidade com vários servidores;
- balanceamento de carga;
- metas formais de disponibilidade empresarial;
- Kubernetes para resolver problemas que um único Compose já resolve.

---

# Fase 14 — Preparação para integração com Alexa

## Objetivo

Criar uma ponte de voz segura sem expor diretamente toda a AMP.

## Ideia de arquitetura

```text
Alexa
  |
  v
Skill / função intermediária pública
  |
  v
Canal autenticado e limitado
  |
  v
Endpoint específico da AMP
  |
  v
LangGraph -> Ollama / ferramentas
```

A Alexa normalmente precisa alcançar um endpoint HTTPS público. Portanto, a integração exigirá uma ponte externa, um túnel seguro, uma VPN apropriada ou uma função em nuvem. Isso deve ser uma borda pequena e isolada; não exponha toda a API administrativa do notebook.

## Tarefas

- [ ] Criar primeiro um endpoint interno específico para voz.
- [ ] Limitar quais agentes e ferramentas a voz pode acionar.
- [ ] Produzir respostas curtas, adequadas para fala.
- [ ] Testar localmente com texto que simula entrada de voz.
- [ ] Definir autenticação entre a ponte e a AMP.
- [ ] Implementar proteção contra repetição de requisições e limites de uso.
- [ ] Exigir confirmação adicional para qualquer ação sensível.
- [ ] Só então estudar e criar uma Alexa Skill.
- [ ] Escolher conscientemente como o endpoint será alcançado pela internet.
- [ ] Registrar e revisar os comandos de voz acionados.

## Entregável

Primeiro, um endpoint de voz simulado e seguro. Depois, opcionalmente, uma Skill capaz de fazer uma pergunta simples à AMP.

## Critério de pronto

Um comando de voz permitido recebe resposta curta, enquanto comandos administrativos ou sensíveis são recusados ou exigem confirmação apropriada.

## O que aprender

- webhooks e HTTPS;
- autenticação entre serviços;
- desenho de conversas por voz;
- segurança de endpoints públicos;
- separação entre borda pública e serviços internos.

## Não fazer cedo demais

- abrir a porta da FastAPI no roteador;
- dar à Alexa acesso administrativo;
- permitir ações destrutivas apenas por reconhecimento de voz;
- começar pela Skill antes de o endpoint interno estar estável.

---

# 6. Marcos que já valem como “produto pronto”

Você não precisa chegar à última fase para considerar o projeto bem-sucedido.

## Marco A — Laboratório local

- Ubuntu instalado;
- Docker funcionando;
- Ollama respondendo.

**Você aprendeu:** Linux, contêineres e inferência local.

## Marco B — Primeiro agente útil

- LangGraph coordenando o fluxo;
- FastAPI expondo o agente;
- SearXNG fornecendo pesquisa.

**Você construiu:** um agente web local e autocontido.

## Marco C — AMP pessoal mínima

- agentes e execuções identificados;
- histórico persistente;
- logs pesquisáveis;
- UI de chat e execuções.

**Você construiu:** uma plataforma pessoal operável.

## Marco D — AMP doméstica controlada

- papéis e permissões;
- aprovações humanas;
- backups testados;
- ferramentas multiagente justificadas.

**Você construiu:** uma AMP adequada para experimentação responsável em casa.

## Marco E — Assistente por voz

- endpoint de voz limitado;
- ponte segura;
- integração opcional com Alexa.

**Você construiu:** uma nova interface para a plataforma, não um novo núcleo.

---

# 7. Ordem de implementação recomendada no repositório

Não crie tudo de uma vez. Deixe a estrutura crescer junto com as fases.

```text
amp/
├── README.md
├── .env.example
├── compose.yaml
├── docs/
│   ├── diario.md
│   ├── arquitetura.md
│   └── operacao.md
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── agents/
│   │   ├── tools/
│   │   ├── persistence/
│   │   └── observability/
│   └── tests/
├── frontend/             # somente quando chegar à fase da UI
└── data/                 # fora do Git
```

Regras simples:

- `.env.example` contém apenas nomes e exemplos não secretos;
- `.env` contém valores locais e não entra no Git;
- `data/` e backups não entram no Git;
- cada agente tem uma responsabilidade compreensível;
- cada ferramenta tem entrada, saída, timeout e permissão definidos;
- mudanças no banco são versionadas por migrações quando isso se tornar necessário.

---

# 8. Backlog: ideias que devem esperar uma necessidade real

Mantenha estas ideias em uma lista, sem implementá-las no início:

- Kubernetes e cluster de notebooks;
- sistema no-code para desenhar grafos;
- RAG e banco vetorial;
- memória semântica permanente;
- marketplace de agentes ou ferramentas;
- filas distribuídas;
- múltiplos modelos roteados automaticamente;
- fine-tuning;
- alta disponibilidade;
- cobrança e cotas por usuário;
- suporte a múltiplas organizações;
- aplicativo móvel;
- exposição pública geral da plataforma.

Uma boa regra: promova um item do backlog somente quando você conseguir escrever **qual problema atual ele resolve** e **como saberá que resolveu**.

---

# 9. Checklist de qualidade para cada fase

Antes de seguir para a próxima fase, responda:

- [ ] Consigo demonstrar o que construí em menos de cinco minutos?
- [ ] Sei iniciar e parar esta parte?
- [ ] Sei onde encontrar os logs?
- [ ] Sei onde os dados ficam?
- [ ] Consigo recuperar de uma falha comum?
- [ ] Registrei o que aprendi e as decisões tomadas?
- [ ] Existe pelo menos um teste ou procedimento manual repetível?
- [ ] A nova tecnologia resolveu um problema concreto?
- [ ] Fiz backup antes de uma mudança de risco?

Se muitas respostas forem “não”, permaneça mais um pouco na fase atual. Isso não é atraso; é aprendizado consolidado.

---

# 10. Indicadores simples para acompanhar

Evite transformar o hobby em um programa corporativo. Acompanhe apenas o suficiente para perceber evolução:

| Indicador | Pergunta que responde |
|---|---|
| Tempo para responder | O sistema está confortável de usar? |
| Taxa de sucesso das execuções | Ele é confiável nas tarefas escolhidas? |
| Memória e temperatura | O notebook está operando dentro dos limites? |
| Espaço em disco | Logs, modelos ou histórico estão crescendo demais? |
| Chamadas de ferramentas | O agente está usando recursos com moderação? |
| Intervenções humanas | Onde ainda é necessária aprovação ou correção? |

---

# 11. Primeira sessão prática

Para começar sem sobrecarga, faça apenas isto:

- [ ] Levante as especificações do notebook.
- [ ] Faça e teste o backup.
- [ ] Escolha Ubuntu Server LTS ou Desktop LTS.
- [ ] Crie o pendrive de instalação.
- [ ] Abra um `diario.md` e registre a decisão.

Ao terminar, pare. A instalação pode ficar para a sessão seguinte.

## Modelo de registro no diário

```markdown
## Data

### Objetivo da sessão

### O que fiz

### O que funcionou

### Erros e como resolvi

### Decisões tomadas

### Próximo passo pequeno
```

---

# 12. Definição final de sucesso

A AMP estará madura para este projeto de hobby quando você puder:

1. escolher um agente pela interface;
2. iniciar uma conversa;
3. acompanhar a execução e as ferramentas utilizadas;
4. retomar a conversa depois de um reinício;
5. diagnosticar uma falha pelo identificador da execução;
6. impedir uma ferramenta não autorizada;
7. aprovar manualmente uma ação sensível;
8. restaurar os dados a partir de um backup;
9. explicar claramente onde termina o LangGraph e onde começa a sua plataforma.

O resultado mais importante não será a quantidade de componentes. Será ter uma plataforma pequena que você entende, consegue operar e pode evoluir com confiança.
