# FrontCRM (WTS Chat) — Especificação de Extração para Raw + Silver

← [[iaops]] · design anterior (diagnóstico completo): [[DESIGN-EXTRACAO-V2]] · réplica de relatório (referência de schema): `PROJETOS/frontcrm-relatorio-atendimentos/README.md` e `gerar_relatorio.py`

**Objetivo deste documento:** especificação técnica para abrir uma solicitação (PR) ao time de engenharia, cobrindo as camadas **Raw** e **Silver** da extração do FrontCRM. A camada **Gold** — réplica do relatório `[FRONT] Relatório de atendimentos` — fica sob responsabilidade de quem escreve este documento, a partir do Silver aqui especificado. Este arquivo é autocontido; os dois documentos linkados acima têm o raciocínio completo por trás de cada decisão, caso o time de engenharia queira o histórico.

---

## 1. O que é o FrontCRM

"FrontCRM" é o nome interno do produto **WTS Chat** (`frontcrm.wts.chat` na UI, `api.wts.chat` na API) — plataforma de atendimento omnichannel (WhatsApp, Instagram, Messenger) com um módulo de funil comercial (pipeline/kanban) embutido, usada pelo time comercial/atendimento da Permaneo.

**Autenticação:** header `Authorization: Bearer <token>`, token permanente gerado em *Ajustes > Integrações > Integração via API* dentro da própria plataforma. Doc oficial: https://flwchat.readme.io/reference/autenticação. Recomendação: guardar o token em Secret Manager, nunca versionar (o script de referência já segue isso via env var `FLW_TOKEN`).

**Base address — atenção, tem 3 segmentos confirmados**, não um único host:

| Segmento | Exemplo confirmado | Uso |
|---|---|---|
| `https://api.wts.chat/chat` | `GET /chat/v1/channel` (testado hoje, 200 OK), `GET /chat/v2/session` (usado no script de relatório) | canais, sessões de atendimento |
| `https://api.wts.chat/core` | `GET /core/v1/contact` | contatos |
| `https://api.wts.chat/crm` | `GET /v2/panel`, `GET /v2/panel/card` | funil comercial (pipeline) |

Isso não estava documentado num único lugar antes — vale confirmar com engenharia se existe um único client/SDK interno já lidando com essa divisão, ou se cada Cloud Function resolve a base manualmente.

---

## 2. Estado atual — o que já existe e por que está sendo revisto

**Repo:** `Permaneo-Permadata/extract-frontcrm` — 3 Cloud Functions gen2 (`trigger-http`), SA `integrador-dados-permadata@permadata-455520.iam.gserviceaccount.com`, escrevendo em `permadata-455520.raw_frontcrm`:

| Function | Endpoint | Tabela BQ |
|---|---|---|
| `extract-channels` | `GET /chat/v1/channel` | `raw_frontcrm.hotmart_channels` |
| `extract-contacts` | `GET /core/v1/contact` (`UpdatedAt.After/Before`) | `raw_frontcrm.hotmart_contacts` |
| `extract-chat-sessions` | `GET /chat/v1/session` (`UpdatedAt.After/Before`) | `raw_frontcrm.hotmart_chat_sessions` |

(Nome das tabelas com prefixo `hotmart_` é resquício histórico — não tem relação com a Hotmart, é dado do FrontCRM.)

**Três problemas diagnosticados em 2026-09-09** (detalhe completo em [[DESIGN-EXTRACAO-V2]]), motivo desta solicitação:

1. **O funil comercial nunca é extraído.** Nenhuma function chama `GET /v2/panel` ou `GET /v2/panel/card`. Os "cards" do pipeline — etapa, valor (`monetaryAmount`), status (OPEN/WON/LOST/ARCHIVED) — não existem no Lake hoje. Isso é o gap principal por trás da desconfiança na base atual.
2. **Perda real de registro, não só atraso.** Diff exato por ID entre o relatório exportado manualmente (248 sessões) e `raw_frontcrm.hotmart_chat_sessions` no mesmo corte: 230 no BQ, 19 faltando. 18 eram atraso normal de sync; **1 era um buraco real** — sessão criada 16h antes do corte, nunca capturada, porque a extração usa janela `UpdatedAt.After/Before` fixa (últimas 6h) e um registro que fica "Pendente" sem ninguém tocar não tem seu `updatedAt` empurrado para dentro de uma janela futura de reprocessamento.
3. **`--allow-unauthenticated`** nas 3 functions — qualquer um com a URL invoca o extractor sem autenticação. Dívida de segurança barata de resolver junto.

---

## 3. Escopo desta solicitação — Raw

### 3.1 Entidades a extrair

| Entidade | Endpoint | Parâmetros relevantes | Chave | Status |
|---|---|---|---|---|
| Canais | `GET /chat/v1/channel` | `ChannelType` (opcional: All/Whatsapp/Messenger/Instagram/WebChat) | `id` | mantém, baixo volume/urgência |
| Contatos | `GET /core/v1/contact` | `UpdatedAt.After/Before` | `id` | mantém, é a chave de match com Hotmart (telefone) |
| Sessões de atendimento | `GET /chat/v2/session` | ver 3.2 — **crítico** | `id` | mantém, mas com correção de parâmetros |
| **Painéis (pipeline)** | `GET /v2/panel` | — | `id` | **novo** |
| **Cards do pipeline (deals)** | `GET /v2/panel/card` | — | `id` | **novo** — é o gap do achado 1 |

### 3.2 Atenção crítica no endpoint de sessões: `IncludeDetails`

O script de referência (`gerar_relatorio.py`) só consegue nomes legíveis (nome do contato, do agente, do canal, do departamento) porque passa:

```
IncludeDetails=AgentDetails,DepartmentsDetails,ContactDetails,ChannelTypeDetails,ClassificationDetails,ChannelDetails
```

Sem esse parâmetro, a API devolve só UUIDs. **Não está confirmado se a extração atual (`extract-chat-sessions`) já usa esse parâmetro.** Se não usar, `raw_frontcrm.hotmart_chat_sessions` hoje só tem IDs — e a Gold (réplica do relatório) exigiria juntar manualmente contra `hotmart_contacts`, `hotmart_channels` e uma tabela de agentes/departamentos que **não existe ainda** na Raw. Duas saídas possíveis, a decidir com engenharia:

- (a) a extração de sessão já pede `IncludeDetails` e grava os objetos aninhados como JSON/STRUCT na Raw (preferível — evita depender de joins de dimensão que podem ficar dessincronizados); ou
- (b) a Raw fica só com IDs, e engenharia também expõe `GET /v1/agent` e `GET /v1/department` como novas tabelas Raw para permitir o join na Silver.

Também usar `PageSize=100` (máximo) e paginação `OrderBy=createdAt`/`OrderDirection=DESCENDING`, `PageNumber` incremental — mesmo padrão do script de referência.

### 3.3 Migrar (ou não) para v2 no endpoint de sessão

A extração atual usa `GET /chat/v1/session`; o script de relatório usa `GET /chat/v2/session` (retorna `IncludeDetails`, paginação com `hasMorePages`/`totalItems`). Recomendo padronizar em `v2` para já sair com os campos que a Gold vai precisar — confirmar com engenharia se `v1` está deprecated ou se há diferença funcional relevante além dos detalhes.

### 3.4 Correção do bug de janela (achado 2)

Não depender só de `UpdatedAt.After/Before` com janela curta (6h). Duas opções, não excludentes:
- **Mínimo viável para este PR:** aumentar a janela de polling para algo mais generoso (ex. 48h) como rede de segurança contra registros "Pendente" parados.
- **Evolução recomendada (fase 2, não bloqueia este PR):** adotar webhooks nativos da API (`GET /v1/webhook/event` lista os tipos disponíveis — `SESSION_NEW/UPDATE/COMPLETE`, `CONTACT_NEW/UPDATE`, `PANEL_CARD_NEW/UPDATE/STEP_CHANGE`) como fonte primária de captura em tempo real, com o polling de janela larga apenas como reconciliação diária. Arquitetura completa (receptor Cloud Run → landing table → MERGE) em [[DESIGN-EXTRACAO-V2]], seção "Desenho da v2" — inclui decisões ainda em aberto (onde roda o receptor, validação de assinatura do webhook) que precisam de definição de engenharia antes de implementar essa parte.

### 3.5 Schema novo — `panel_cards`

Campos do `PublicPanelCardDTOV2` (via `GET /v2/panel/card`):

```
id, createdAt, updatedAt, companyId, panelId, panelTitle, stepId, stepTitle, stepPhase,
position, title, description, key, number, dueDate, isOverdue, tagIds, sessionId,
monetaryAmount, responsibleUserId, responsibleUser, contactIds, contacts, customFields,
metadata, status, lostReason, loaded_at
```

`panels` (`GET /v2/panel`) guarda o cadastro de etapas (`steps[]`) — necessário para traduzir `stepId` em nome de etapa sem depender de join constante com a API viva.

`panel_card.sessionId` e `panel_card.contactIds` são a ponte direta pipeline ↔ atendimento ↔ contato — permite montar essa junção sem depender de match difuso (o match difuso só entra na hora de cruzar com a Hotmart, fora do escopo deste documento).

### 3.6 Segurança (achado 3)

Corrigir `--allow-unauthenticated` nas functions de polling — não bloqueia a entrega funcional, mas é dívida barata de resolver na mesma PR já que o código está sendo mexido.

---

## 4. Escopo desta solicitação — Silver

### 4.1 O que a Silver deve fazer

- Tipar e converter timestamps para `America/Sao_Paulo` (a Raw vem em UTC) — padrão já usado nas demais silvers do Lake.
- Deduplicar **tecnicamente** por `id`, mantendo o registro mais recente por `updatedAt` — mesmo padrão `QUALIFY ROW_NUMBER() OVER(PARTITION BY id ORDER BY updated_at DESC) = 1` já usado nas silvers de Unisub.
- **Não aplicar aqui** a regra de negócio de deduplicação por telefone (colapsar múltiplos protocolos da mesma pessoa mantendo o mais recente) — essa é uma regra de relatório/negócio, não de integridade de dado, e fica por conta da Gold (ver seção 6).
- Resolver `stepId` → nome da etapa via join com `panels.steps[]` (ou já achatar isso na própria Silver de `panel_cards`, a decidir com engenharia qual fica mais simples de manter).

### 4.2 Colunas que a Silver de sessões precisa expor (para a Gold replicar o relatório)

Mapeamento completo já validado contra o export manual (`gerar_relatorio.py`, ver README do projeto para o detalhe de cada campo):

| Campo da API (`GET /chat/v2/session`) | Uso na réplica do relatório |
|---|---|
| `number` | Protocolo |
| `origin` | Quem iniciou (Contato/Empresa) |
| `contactDetails.name`, `.phonenumberFormatted`, `.instagram`, `.tagsName` | Bloco Contato |
| `agentDetails.name` | Usuário atendente |
| `channelDetails.humanId`, `.platform` | Canal |
| `departmentDetails.name` | Equipe |
| `createdAt`, `startAt`, `firstResponseAt`, `lastInteractionDate`, `endAt` | Datas do ciclo de atendimento (converter UTC → America/Sao_Paulo) |
| `timeWait`, `timeService` | Tempos formatados `HH:MM:SS` (`timeService` = "Não concluído" se `status != COMPLETED`) |
| `statusDescription` | Situação (já vem em PT-BR) |
| `classification.categoryName`, `.categoryDescription`, `.amount` | Classificação |
| `utm.source`, `.campaign`, `.headline`, `.content`, `.referralUrl` | Bloco UTM |
| `previewUrl` | Link do atendimento (usado inclusive para validação/diff manual) |

### 4.3 Gaps conhecidos da API — flag para engenharia confirmar

- **NPS/satisfação (`resposta-csat`) e "concluído automaticamente"** não aparecem em nenhum campo documentado de `GET /v2/session`. **Porém**, a documentação de arquitetura de dados existente (auditoria de 2026-08-06) descreve `gold_sales.tb_gold_sales_frontcrm_hotmart_contacts` como já enriquecida com CSAT (`Satisfeito`/`Encantado`/`Mal atendido`). **Isso é uma contradição a esclarecer com quem manteve a extração original** — hipóteses: (a) existe um endpoint não documentado publicamente que a extração atual usa, (b) o CSAT vem de outra fonte (import manual, planilha, outro sistema) e é joinado na Gold, ou (c) a informação da auditoria está desatualizada/incorreta. Não assumir nenhuma das três sem confirmar — se for (a), o endpoint precisa entrar no escopo Raw deste documento.
- **Filtro de data (`CreatedAt.After/Before`) não bate com o "dia" do protocolo.** O número de protocolo (ex. `2026090900123`) parece seguir o dia em UTC, não America/Sao_Paulo. Teste comparativo no dia 09/09/2026: filtrando por `CreatedAt` convertido para UTC, vieram 301 sessões (faltando as primeiras ~40 do dia, protocolos `00001`–`00040`); paginando sem filtro de data e cortando pelo prefixo do protocolo no cliente, vieram as 341 completas. **Implicação para a Raw/Silver:** se a extração usa `CreatedAt.After/Before` (dia local convertido para UTC) para qualquer lógica de particionamento ou backfill por dia, ela está sistematicamente perdendo as primeiras horas de cada dia. Vale revisar se a extração atual tem esse mesmo problema (ela usa `UpdatedAt`, não `CreatedAt`, então o efeito pode ser diferente — mas o comportamento de timezone do protocolo é uma característica da API que qualquer lógica de corte por dia precisa considerar).

---

## 5. Fora de escopo deste documento (fica com a Gold, não com engenharia)

- Regra de dedup por telefone (`QUALIFY ROW_NUMBER() OVER (PARTITION BY telefone ORDER BY data_interacao DESC, protocolo DESC) = 1`) para contagem de leads únicos.
- Match Hotmart × FrontCRM (prioridade: `panel_card.contactIds → contact.phoneNumber` dentro do próprio FrontCRM; depois `contact.phoneNumber` normalizado × telefone Hotmart; fallback fuzzy por nome só como último recurso) — measurement da taxa de erro antes de qualquer decisão de arquitetura, conforme já combinado com Victoria/Larissa.
- Layout final e fórmulas do relatório replicado — já resolvido no script `gerar_relatorio.py`, serve de gabarito para a Gold.

---

## 6. Definition of Done proposto para a PR de engenharia

- [ ] `raw_frontcrm.panels` e `raw_frontcrm.panel_cards` existindo e populados (backfill histórico + incremental).
- [ ] `raw_frontcrm.hotmart_chat_sessions` migrada para `v2/session` com `IncludeDetails` completo (ou tabelas de dimensão `agent`/`department` adicionadas, se optarem pela via (b) da seção 3.2).
- [ ] Janela de polling de sessões/contatos ampliada (mínimo: para não repetir o "achado 2"); webhook fica como evolução de fase 2, não bloqueante.
- [ ] Functions sem `--allow-unauthenticated`.
- [ ] Silver com dedup técnico por `id`/`updatedAt`, timestamps em America/Sao_Paulo, e todas as colunas da tabela da seção 4.2 disponíveis (direto ou via join documentado).
- [ ] Resposta documentada sobre a origem do CSAT (seção 4.3) antes de eu começar a Gold, para eu saber se preciso pedir mais um endpoint ou se é join externo.
- [ ] Validação: diff manual (relatório exportado vs. Silver) para um dia fechado batendo 1:1, mesmo método usado no diagnóstico de 2026-09-09.

---

## 7. Referências

- Diagnóstico completo e arquitetura webhook+polling: [[DESIGN-EXTRACAO-V2]] (`MAIN_CLAUDE/PROFISSIONAL/IAOPS/frontcrm/DESIGN-EXTRACAO-V2.md`)
- Script de referência (réplica do relatório via API, já testado): `MAIN_CLAUDE/PROJETOS/frontcrm-relatorio-atendimentos/README.md` e `gerar_relatorio.py`
- Doc oficial de autenticação: https://flwchat.readme.io/reference/autenticação
- Índice de referência de endpoints: https://flwchat.readme.io/llms.txt
- Contexto de negócio original (dor, proposta inicial de raw/silver/gold): `MAIN_AG/PROFISSIONAL/IAOPS/hotmart_agent_v3_frontcrm/ESCOPO_FRONTCRM.md`
- Estado documentado do `raw_frontcrm` na auditoria de arquitetura de dados (2026-08-06): `MAIN_AG/VINI/PERMANEO/DOCUMENTACAO/revenue/00-documentacao-arquitetura-dados.md`, seções 2.1 e catálogo `tb_gold_sales_frontcrm_hotmart_contacts`
