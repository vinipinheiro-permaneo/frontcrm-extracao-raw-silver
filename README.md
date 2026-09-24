# FrontCRM (WTS Chat) — Extração Raw + Silver

Material de especificação para abrir a solicitação de engenharia que corrige a extração
atual do FrontCRM (`Permaneo-Permadata/extract-frontcrm`) e entrega as camadas Raw e Silver
completas. A camada Gold (réplica do relatório `[FRONT] Relatório de atendimentos`) fica sob
responsabilidade de quem abriu esta solicitação, construída em cima do Silver aqui
especificado.

## Estrutura

- **[`docs/TICKET-RAW-SILVER.md`](docs/TICKET-RAW-SILVER.md)** — versão condensada, pronta
  para colar como ticket no Jira.
- **[`docs/SOLICITACAO-RAW-SILVER.md`](docs/SOLICITACAO-RAW-SILVER.md)** — especificação
  técnica completa: endpoints, schemas, regras de silver, gaps conhecidos da API, critérios
  de aceite.
- **[`docs/DESIGN-EXTRACAO-V2.md`](docs/DESIGN-EXTRACAO-V2.md)** — diagnóstico original
  (2026-09-09) dos bugs da extração atual (funil comercial nunca extraído, perda real de
  registro por janela de `updatedAt`, functions sem autenticação) e desenho da arquitetura
  webhook + polling proposta como evolução.
- **[`scripts/gerar_relatorio.py`](scripts/gerar_relatorio.py)** + **[`scripts/README.md`](scripts/README.md)**
  — script de referência que já reconstrói o relatório de atendimentos via API pública,
  usado para validar o mapeamento completo de campos que a Silver precisa expor. Não é o
  extractor de produção — é o gabarito que comprova, com código funcionando, qual dado a
  API realmente devolve.

## Por onde começar

1. Leia `docs/DESIGN-EXTRACAO-V2.md` para entender por que a extração atual está sendo
   revista.
2. Leia `docs/SOLICITACAO-RAW-SILVER.md` para o escopo técnico completo (Raw + Silver).
3. Use `docs/TICKET-RAW-SILVER.md` como base do ticket no Jira.

## Autenticação da API

Nunca commitar token real. O script de referência lê de `FLW_TOKEN` (variável de ambiente).
Doc oficial da API: https://flwchat.readme.io/reference/autenticação
