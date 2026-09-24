# Ticket para engenharia — FrontCRM raw + silver

← [[SOLICITACAO-RAW-SILVER]] (spec técnica completa, este ticket é a versão condensada pra abrir no Jira)

**Projeto sugerido:** PTI (Dados/BI) — é o projeto de backoffice de Dados/BI já mapeado na governança; confirmar se é esse mesmo antes de abrir.
**Tipo:** Story (ou Task, conforme convenção do time)
**Labels sugeridas:** `frontcrm`, `raw`, `silver`, `data-pipeline`

---

## Título

`[FrontCRM] Corrigir extração raw (funil comercial ausente + perda de registros) e entregar silver completa`

---

## Descrição

**Contexto**

A extração atual do FrontCRM (repo `extract-frontcrm`, 3 Cloud Functions escrevendo em `permadata-455520.raw_frontcrm`) tem dois problemas confirmados por diagnóstico em 2026-09-09 (diff exato contra relatório exportado manualmente):

1. O funil comercial (pipeline de vendas — cards, etapa, valor, status) **nunca é extraído**. Só temos canais, contatos e sessões de atendimento — infraestrutura de conversa, não dado de vendas.
2. **Perda real de registros**, não só atraso: sessões que ficam "Pendente" sem ninguém tocar não são recapturadas pela janela de `UpdatedAt` (6h) — encontrado 1 buraco real de 16h+ numa amostra de 1 dia.

Terceiro ponto, menor: as 3 functions estão `--allow-unauthenticated`.

**Objetivo desta issue**

Corrigir a extração Raw e entregar uma camada Silver completa e confiável, para que o time de BI construa a camada Gold (réplica do relatório `[FRONT] Relatório de atendimentos`) em cima de dado consistente.

**Escopo — Raw**

- [ ] Adicionar `raw_frontcrm.panels` (`GET /v2/panel`, base `api.wts.chat/crm`) e `raw_frontcrm.panel_cards` (`GET /v2/panel/card`) — schema completo do `PublicPanelCardDTOV2` na spec técnica linkada.
- [ ] Migrar extração de sessões para `GET /chat/v2/session` com `IncludeDetails=AgentDetails,DepartmentsDetails,ContactDetails,ChannelTypeDetails,ClassificationDetails,ChannelDetails` (confirmar se a extração atual já usa isso — se não, hoje só existem UUIDs, não nomes).
- [ ] Ampliar a janela de polling (mínimo: de 6h para algo como 48h) como correção imediata da perda de registro. Adoção de webhooks nativos da API como fonte primária fica como evolução de fase 2 — não bloqueia esta issue (arquitetura completa na spec linkada).
- [ ] Remover `--allow-unauthenticated` das 3 functions.

**Escopo — Silver**

- [ ] Tipagem e conversão de timestamps para `America/Sao_Paulo`.
- [ ] Dedup técnico por `id` + `updatedAt` (`QUALIFY ROW_NUMBER() OVER(PARTITION BY id ORDER BY updated_at DESC) = 1`, mesmo padrão já usado nas silvers de Unisub).
- [ ] Resolver `stepId` → nome da etapa (join com `panels.steps[]`).
- [ ] Garantir que todas as colunas usadas no relatório de atendimentos estejam disponíveis (lista completa de campo→coluna na spec linkada, seção 4.2) — direto ou via join documentado.

**Fora de escopo (fica com BI/Gold, não é desta issue)**

- Dedup por telefone para contagem de leads únicos (regra de negócio de relatório).
- Match Hotmart × FrontCRM.
- Layout final do relatório replicado.

**Pergunta em aberto que precisa de resposta de quem manteve a extração original antes de eu (BI) começar a Gold:**

A documentação de arquitetura describe a Gold atual (`tb_gold_sales_frontcrm_hotmart_contacts`) como já tendo CSAT (`Satisfeito`/`Encantado`/`Mal atendido`), mas nenhum endpoint documentado da API expõe isso. De onde vem esse dado hoje? (endpoint não documentado / fonte externa / informação desatualizada?)

**Critérios de aceite**

- [ ] `panels` e `panel_cards` populadas (backfill + incremental).
- [ ] `hotmart_chat_sessions` com nomes resolvidos (não só UUIDs).
- [ ] Diff manual (relatório exportado vs. silver) batendo 1:1 para um dia fechado.
- [ ] Functions sem acesso anônimo.
- [ ] Resposta documentada sobre a origem do CSAT.

**Referências**

- Spec técnica completa: `MAIN_CLAUDE/PROFISSIONAL/IAOPS/frontcrm/SOLICITACAO-RAW-SILVER.md`
- Diagnóstico original (2026-09-09): `MAIN_CLAUDE/PROFISSIONAL/IAOPS/frontcrm/DESIGN-EXTRACAO-V2.md`
- Doc oficial da API: https://flwchat.readme.io/reference/autenticação
