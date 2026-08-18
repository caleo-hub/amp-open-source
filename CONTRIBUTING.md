# Como contribuir

Obrigado pelo interesse na AMP Open Source.

Este projeto implementa uma Agent Managed Platform self-hosted. Contribuições devem respeitar a
separação entre Control Plane, Data Plane, Model Plane e Tool Plane e manter os contratos entre
componentes explícitos.

## Antes de começar

1. Consulte as Issues existentes.
2. Para mudanças maiores, abra uma Issue explicando o problema e a proposta.
3. Consulte `docs/conventions.md` e os ADRs aplicáveis.
4. Mantenha a alteração pequena e focada.
5. Nunca inclua senhas, tokens, dados pessoais, modelos baixados ou bancos locais.

## Uma boa contribuição

- explica qual problema resolve;
- contém instruções reproduzíveis;
- inclui teste ou procedimento de verificação apropriado;
- atualiza a documentação quando necessário;
- respeita o princípio de menor privilégio;
- não permite que agentes acessem providers ou infraestrutura diretamente;
- inclui contratos e observabilidade proporcionais ao componente.

## Qualidade

Use Python 3.12+, `uv`, Ruff, mypy estrito e pytest para código Python. O console usa TypeScript
estrito, React, ESLint e Prettier. Depois de `make bootstrap`, execute `make check` antes de enviar.

Novos serviços e agentes devem partir dos geradores documentados em `docs/conventions.md`, declarar
ownership e permanecer implantáveis de forma independente.

## Commits e pull requests

- Use mensagens de commit curtas e descritivas.
- Explique no pull request o que mudou, por que mudou e como foi verificado.
- Prefira um assunto por pull request.
- Marque claramente qualquer limitação conhecida ou decisão pendente.

## Segurança

Não publique vulnerabilidades exploráveis, credenciais ou dados privados em uma Issue pública. Para riscos ainda sem canal privado definido, descreva apenas que existe um possível problema e aguarde orientação do mantenedor antes de compartilhar detalhes sensíveis.
