# Replicar o relatório "[FRONT] Relatório de atendimentos" via API

Documentação de como gerar, via API do FrontCRM (wts.chat), o mesmo relatório que hoje é
baixado manualmente pela interface (`[FRONT] Relatório de atendimentos.xlsx`), tendo a
**data** como único filtro.

Script pronto: `gerar_relatorio.py` nesta pasta.

## 1. Pré-requisitos

- Python 3 com `requests` e `openpyxl` instalados (`pip install requests openpyxl`).
- Um token de API válido, gerado em **Ajustes > Integrações > Integração via API** dentro
  do FrontCRM. O token é permanente até ser revogado manualmente lá.

## 2. Autenticação

Documentação oficial: https://flwchat.readme.io/reference/autentica%C3%A7%C3%A3o

Toda requisição precisa do header:

```
Authorization: Bearer <token>
```

O script lê o token da variável de ambiente `FLW_TOKEN` (nunca colocar o token direto no
código ou versionar em git).

## 3. Endpoint usado

Não existe um endpoint de "relatório" pronto — a API não expõe geração de relatórios/exports.
O relatório é reconstruído a partir da listagem de sessões (atendimentos):

```
GET https://api.wts.chat/chat/v2/session
```

Parâmetros usados pelo script:

| Parâmetro | Valor | Motivo |
|---|---|---|
| `PageSize` | 100 (máximo permitido) | minimizar número de páginas |
| `OrderBy` / `OrderDirection` | `createdAt` / `DESCENDING` | permite parar a paginação assim que passa do dia desejado |
| `IncludeDetails` | `AgentDetails, DepartmentsDetails, ContactDetails, ChannelTypeDetails, ClassificationDetails, ChannelDetails` | sem isso a API só devolve IDs (UUID), não nomes |
| `PageNumber` | incrementado a cada chamada | paginação |

Resposta: objeto com `items` (lista de sessões), `totalItems`, `hasMorePages`.

### Por que não filtrar por `CreatedAt.After` / `CreatedAt.Before`

A API oferece filtro de data (`CreatedAt.After`/`CreatedAt.Before`, ISO 8601 UTC), mas o
**número de protocolo** (ex.: `2026090900123`) não segue exatamente o dia local
(America/Sao_Paulo, UTC-3) — parece seguir o dia em UTC. Um teste comparando as duas
abordagens no dia 09/09/2026 mostrou:

- Filtrando por `CreatedAt` convertendo o dia local para UTC: **301** sessões, faltando as
  primeiras ~40 do dia (protocolos `00001`–`00040`).
- Sem filtro de data, paginando tudo e filtrando pelo **prefixo do protocolo**
  (`20260909...`) no lado do cliente: **341** sessões, sequência completa
  `00001`–`00341`.

Por isso o script **não usa filtro de data da API** — ele pagina do mais recente para o mais
antigo e para assim que o protocolo da página cai abaixo do prefixo do dia pedido. Isso é
seguro porque a listagem vem ordenada por `createdAt` decrescente, e o número de protocolo
cresce junto com a data de criação.

## 4. Mapeamento de colunas

| Coluna do relatório | Campo da API | Observação |
|---|---|---|
| Protocolo | `number` | também usado como filtro |
| Quem iniciou | `origin` | já vem como "Contato" / "Empresa" |
| Contato/Nome | `contactDetails.name` | |
| Contato/Telefone | `contactDetails.phonenumberFormatted` | |
| Contato/Instagram | `contactDetails.instagram` | |
| Contato/Tags | `contactDetails.tagsName` | join com `", "` |
| Usuário/Nome | `agentDetails.name` | vazio se não atribuído |
| Canal/Chave | `channelDetails.humanId` | |
| Canal/Plataforma | `channelDetails.platform` | |
| Equipe | `departmentDetails.name` | |
| Data criação | `createdAt` | convertido de UTC para America/Sao_Paulo, `dd/mm/aaaa hh:mm` |
| Data início atendimento | `startAt` | idem |
| Data primeira resposta | `firstResponseAt` | idem |
| Data última interação | `lastInteractionDate` | idem |
| Data conclusão | `endAt` | idem |
| Tempo de espera | `timeWait` | já vem formatado `HH:MM:SS`; vazio se ainda não concluído |
| Tempo de atendimento | `timeService` | idem; texto literal **"Não concluído"** quando `status != COMPLETED` (replica o comportamento do export original) |
| Situação | `statusDescription` | já vem em português (`Pendente`, `Em andamento`, `Concluído`...) |
| Classificação | `classification.categoryName` | |
| Classificação/Descrição | `classification.categoryDescription` | |
| Classificação/Valor | `classification.amount` | formatado como `R$ 0,00` |
| UTM/Origem | `utm.source` | |
| UTM/Campanha | `utm.campaign` | |
| UTM/Título | `utm.headline` | |
| UTM/Conteudo | `utm.content` | |
| UTM/UrlReferencia | `utm.referralUrl` | |
| Ultima Review/Nivel de Satisfação | — | **não exposto** por esta API pública, fica vazio |
| Ultima Review/Comentário | — | **não exposto** por esta API pública, fica vazio |
| Endereço conversa | `previewUrl` | link direto pro atendimento no FrontCRM |
| Concluído automaticamente | — | **não exposto** por esta API pública, fica vazio |

## 5. Limitações conhecidas

- **Satisfação (NPS) e comentário da última review** e **flag de conclusão automática** não
  existem nos campos documentados de `GET /v2/session`. Se esses dados forem necessários,
  é preciso investigar se existe um endpoint interno/não documentado, ou continuar
  exportando esses dois campos manualmente pela interface.
- O relatório baixado manualmente pode ser um **snapshot parcial do dia** (gerado antes do
  fim do dia). O script sempre traz o dia **completo** até o momento da execução — para um
  dia totalmente encerrado, os dados devem bater; para o dia corrente, o script traz mais
  linhas do que um export feito mais cedo no mesmo dia.

## 6. Uso

```bash
export FLW_TOKEN="pn_xxxxxxxxxxxxxxxxxxxxxxxxx"
python gerar_relatorio.py 2026-09-09
```

Gera `Relatorio_atendimentos_2026-09-09.xlsx` na pasta atual, com as mesmas 30 colunas e
formatação do relatório original.
