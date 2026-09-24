# Front CRM (WTS Chat) — extração v2, refeita do zero

← [[iaops]] · relacionado: [[iaops-ata-2026-09-09-recorrencia-comercial]] (origem do pedido), `hotmart_agent_v2/` (consumidor final via matching)

**Por quê refazer:** Guilherme não confia na extração atual (`Permaneo-Permadata/extract-frontcrm`). Diagnóstico feito em 2026-09-09 confirma dois problemas concretos, não achismo — ver seção "Diagnóstico" abaixo. Este documento é o desenho da v2, antes de escrever código.

---

## Diagnóstico da extração atual (2026-09-09)

**"Front CRM" = WTS Chat** (`frontcrm.wts.chat`, API em `api.wts.chat`) — confirmado via link `Endereço conversa` no relatório que a Larissa exportou.

Repo atual: `Permaneo-Permadata/extract-frontcrm` — 3 Cloud Functions gen2, `trigger-http`, `--allow-unauthenticated`(!), rodando com a SA `integrador-dados-permadata@permadata-455520.iam.gserviceaccount.com`, escrevendo em `permadata-455520.raw_frontcrm`:

| Function | Endpoint da API | Tabela BQ |
|---|---|---|
| `extract-channels` | `GET /chat/v1/channel` | `hotmart_channels` |
| `extract-contacts` | `GET /core/v1/contact` (`UpdatedAt.After/Before`) | `hotmart_contacts` |
| `extract-chat-sessions` | `GET /chat/v1/session` (`UpdatedAt.After/Before`) | `hotmart_chat_sessions` |

**Achado 1 — o pipeline de vendas nunca é extraído.** Nenhuma function chama `GET /v2/panel` ou `GET /v2/panel/card` (endpoint `https://api.wts.chat/crm`). Isso significa que **o funil comercial em si — os "cards" com etapa, valor (`monetaryAmount`), status (OPEN/WON/LOST/ARCHIVED) — nunca chegou ao Lake.** O que existe hoje (canais, contatos, sessões de atendimento) é infraestrutura de conversa, não de vendas. Isso sozinho explica boa parte da desconfiança: perguntar "quantas oportunidades tem na pipeline" contra essa base não tem como funcionar, o dado não existe.

**Achado 2 — perda real de registro, não só atraso.** Comparei o relatório `[FRONT] Relatório de atendimentos.xlsx` (Larissa, 09/09, 248 sessões até 16h31) contra `raw_frontcrm.hotmart_chat_sessions` no mesmo intervalo: **230 registros no BQ, 19 faltando** (diff exato por `id`, extraído da URL `Endereço conversa` de cada linha). Desses 19:
- **18 são atraso normal de sincronização** — criados entre 15h52–16h31, ainda `Pendente`/`Em andamento`, a função ainda não tinha rodado de novo.
- **1 é um buraco real**: sessão criada às **00h06** (16+ horas antes do corte), status `Pendente`, ainda ausente do BQ na hora do diagnóstico.

**Hipótese da causa raiz do achado 2:** a extração usa janela `UpdatedAt.After/Before` fixa (padrão: últimas 6h + 5min de overlap, `get_time_range()` em `main.py`). Uma sessão que fica `Pendente` **sem ninguém nunca tocar nela de novo** não tem seu `updatedAt` "empurrado" pra dentro de uma janela futura — se a run que deveria pegá-la falhar ou atrasar por qualquer motivo, ela nunca mais é revisitada, porque a próxima run já pulou pra uma janela mais recente. Isso é uma classe de bug conhecida em ingestão incremental por `updatedAt` com janela deslizante: **não há garantia de "exactly-once eventual" quando o timestamp não muda.**

**Achado 3 (menor, mas registrar):** `--allow-unauthenticated` nas 3 functions — qualquer um com a URL consegue invocar o extractor sem autenticação. Não é o foco deste redesenho, mas vale corrigir junto.

---

## Desenho da v2

### Princípio: parar de confiar só em polling por janela de tempo

A API do WTS Chat tem **webhooks nativos** (`GET /v1/webhook/event` lista os tipos, `POST /v1/webhook/subscription` cria a assinatura) cobrindo exatamente as entidades que interessam:

```
SESSION_NEW · SESSION_UPDATE · SESSION_COMPLETE
CONTACT_NEW · CONTACT_UPDATE · CONTACT_TAG_UPDATE
PANEL_CARD_NEW · PANEL_CARD_UPDATE · PANEL_CARD_STEP_CHANGE · PANEL_CARD_NOTE_NEW · PANEL_CARD_NOTE_UPDATE
```

**Arquitetura proposta: webhook como fonte primária + polling como rede de segurança (reconciliação), não o contrário do que existe hoje.**

```
WTS Chat ──(webhook POST)──> Cloud Run receptor ──> tabela landing (append-only, raw JSON + event_id)
                                                            │
                                                    job de MERGE (mesmo padrão id+updatedAt
                                                    já usado hoje, reaproveitar)
                                                            ▼
                                                   tabelas curadas raw_frontcrm.*

Polling diário (GET com janela larga, ex. 48h) ──> mesma landing table ──> mesmo MERGE
   (pega o que o webhook perdeu por downtime/erro de rede — rede de segurança, não fonte única)
```

Por que isso resolve o achado 2: o webhook dispara **no evento de criação**, não depende de alguém "tocar" o registro depois. Um card/sessão criado às 00h06 chega no landing às 00h06, independente do que aconteça com ele depois. O polling continua existindo, mas como reconciliação com janela generosa (48h, não 6h) — rodando 1x/dia, não como a única fonte.

**Trade-off assumido conscientemente:** isso exige expor um endpoint HTTP público (Cloud Run) pro WTS Chat conseguir chamar de fora — vale revisitar a decisão de `--allow-unauthenticated` das functions atuais nesse mesmo momento (webhook precisa aceitar POST externo sem auth de usuário, mas pode validar assinatura/secret do próprio WTS Chat se a API oferecer, e as functions de polling não precisam mais ser públicas).

### Entidades — o que extrair (adiciona 2 novas ao que já existe)

| Entidade | Endpoint | Status | Observação |
|---|---|---|---|
| Canais | `GET /chat/v1/channel` | mantém, já existe | baixo volume, sem urgência de webhook |
| Contatos | `GET /core/v1/contact` + webhook `CONTACT_*` | reforça com webhook | é a chave de match com Hotmart (telefone) |
| Sessões de atendimento | `GET /chat/v1/session` + webhook `SESSION_*` | reforça com webhook | já valida contra o relatório da Larissa (achado 2) |
| **Painéis (pipeline)** | `GET /v2/panel` (base `https://api.wts.chat/crm`) | **novo** | metadado do funil: etapas (`steps[]`), `type` SALES/MANAGEMENT, `autoLossDays` |
| **Cards do pipeline (deals)** | `GET /v2/panel/card` + webhook `PANEL_CARD_*` | **novo, é o gap que gerou a desconfiança** | `stepId`, `status` (OPEN/WON/LOST/ARCHIVED), `monetaryAmount`, `contactIds`, `sessionId`, `lostReason` |

`panel/card` traz `sessionId` e `contactIds` diretos — é a ponte natural pra juntar pipeline ↔ atendimento ↔ contato numa única linha, sem precisar de match difuso logo de cara pra essa junção interna (o match difuso por telefone só entra na hora de cruzar com a Hotmart).

### Schema novo — `raw_frontcrm.panels` e `raw_frontcrm.panel_cards`

Seguir o mesmo padrão dos scripts atuais (`prepare_*_for_bq` + `MERGE` por `id`/`updatedAt`), com os campos do `PublicPanelCardDTOV2`:

```
id, createdAt, updatedAt, companyId, panelId, panelTitle, stepId, stepTitle, stepPhase,
position, title, description, key, number, dueDate, isOverdue, tagIds, sessionId,
monetaryAmount, responsibleUserId, responsibleUser, contactIds, contacts, customFields,
metadata, status, lostReason, loaded_at
```

`panels` guarda o cadastro de etapas (`steps[]`) — necessário pra traduzir `stepId` em nome de etapa sem precisar de join constante com a API.

### Estratégia de match Hotmart × Front CRM (retomando a ATA de 09/09)

Ordem de prioridade pro join, do mais confiável pro mais frágil:
1. `panel_card.contactIds` → `contact.phoneNumber` (dentro do próprio Front CRM, sem ambiguidade)
2. `contact.phoneNumber` (normalizado: só dígitos, com DDI) → telefone do comprador na Hotmart
3. Fallback por nome (fuzzy match) só quando (2) não bate — é aqui que entra a sugestão de usar IA pra volume diário baixo, como combinado na call de 09/09

**Medir, não estimar:** antes de qualquer decisão de arquitetura de match, rodar o mesmo tipo de diagnóstico feito hoje (diff exato por ID/telefone) numa amostra real, pra ter a taxa de erro de verdade — é a "entrega número um" já combinada com a Victoria/Larissa.

### Validação — reaproveitar o padrão do harness do Hotmart V2

O mesmo método usado neste diagnóstico (exportar relatório do dia, extrair IDs reais da URL de cada linha, comparar 1:1 contra o BQ) vira **rotina de validação diária automatizada** antes de declarar a v2 confiável — mesmo espírito do harness que validou o agente Hotmart V2 (gabarito real, não estimado, rodadas consecutivas até bater uma meta). Proposta: gerar esse relatório via API (não depender de export manual da Larissa) e rodar o diff todo dia, alertando se a taxa de match cair abaixo de um limiar.

---

## Em aberto / decisões pendentes

- **Onde roda o receptor de webhook** — Cloud Run é o candidato natural (já usado no case Hotmart V2 pra UI), mas fica no projeto `permadata-455520` (Lake) ou em `permai-agentes`? Teoricamente é ingestão de dado bruto, então faz mais sentido no Lake — mas exige acesso IAM lá, que hoje eu não tenho (bloqueou até checar Cloud Scheduler nesta sessão).
- **Segurança do endpoint de webhook** — confirmar na doc do WTS Chat se existe assinatura/secret pra validar que o POST realmente veio deles (não achei isso na leitura de hoje, procurar antes de expor o endpoint).
- **`--allow-unauthenticated` das functions de polling** — corrigir junto, não é urgente mas é dívida de segurança barata de resolver agora que estamos mexendo.
- **Janela do polling de reconciliação** — proposta inicial 48h, mas isso é chute; ajustar depois de ver quantos "buracos" tipo o achado 2 aparecem numa amostra maior.
- **Quem grava a curadoria (`raw_frontcrm.panel_cards`) — reaproveitar a SA `integrador-dados-permadata` existente ou criar uma nova escopada só pra essa frente?**

## Próximos passos reais

1. Confirmar com o Guilherme se este desenho resolve a desconfiança dele (pipeline extraído de verdade + garantia de não perder "pendente" parado) antes de escrever qualquer código.
2. Rodar o diagnóstico de match Hotmart×Front CRM numa amostra real, usando o link direto `contactIds → phoneNumber` do próprio Front CRM primeiro (mais barato que já ter os cards extraídos manualmente via API antes de codar o pipeline inteiro).
3. Confirmar segurança do webhook antes de expor endpoint público.
