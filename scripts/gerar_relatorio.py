# -*- coding: utf-8 -*-
"""
Replica o relatório "[FRONT] Relatório de atendimentos" (FrontCRM / wts.chat)
usando a API pública em vez de exportar manualmente pela interface.

Uso:
    export FLW_TOKEN="pn_xxxxxxxxxxxxxxxxxxxxxxxxx"
    python gerar_relatorio.py 2026-09-09

Gera: Relatorio_atendimentos_<data>.xlsx na pasta atual.

Documentação completa: README.md nesta mesma pasta.
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import requests
import openpyxl
from openpyxl.styles import Font

BASE_URL = "https://api.wts.chat/chat/v2/session"
BRT = timezone(timedelta(hours=-3))
PAGE_SIZE = 100

HEADER = [
    "Protocolo", "Quem iniciou", "Contato/Nome", "Contato/Telefone", "Contato/Instagram",
    "Contato/Tags", "Usuário/Nome", "Canal/Chave", "Canal/Plataforma", "Equipe",
    "Data criação", "Data início atendimento", "Data primeira resposta", "Data última interação",
    "Data conclusão", "Tempo de espera", "Tempo de atendimento", "Situação", "Classificação",
    "Classificação/Descrição", "Classificação/Valor", "UTM/Origem", "UTM/Campanha", "UTM/Título",
    "UTM/Conteudo", "UTM/UrlReferencia", "Ultima Review/Nivel de Satisfação",
    "Ultima Review/Comentário", "Endereço conversa", "Concluído automaticamente",
]


def fetch_sessions(token, protocol_prefix):
    """Busca todas as sessões cujo número de protocolo comece com protocol_prefix (YYYYMMDD)."""
    headers = {"Authorization": f"Bearer {token}"}
    items = []
    page = 1
    while True:
        params = {
            "PageNumber": page,
            "PageSize": PAGE_SIZE,
            "OrderBy": "createdAt",
            "OrderDirection": "DESCENDING",
            "IncludeDetails": [
                "AgentDetails", "DepartmentsDetails", "ContactDetails",
                "ChannelTypeDetails", "ClassificationDetails", "ChannelDetails",
            ],
        }
        resp = requests.get(BASE_URL, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        page_items = data.get("items", [])
        items.extend(page_items)

        # A API ordena por createdAt desc, então o número de protocolo também
        # decresce dentro da mesma sequência. Assim que o último item da página
        # já ficou abaixo do prefixo do dia buscado, os dias seguintes só terão
        # protocolos ainda menores — pode parar.
        if page_items and page_items[-1].get("number", "") < protocol_prefix:
            break
        if not data.get("hasMorePages"):
            break
        page += 1

    return [i for i in items if (i.get("number") or "").startswith(protocol_prefix)]


def fmt_dt(iso_str):
    if not iso_str:
        return ""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone(BRT)
    return dt.strftime("%d/%m/%Y %H:%M")


def fmt_money(amount):
    if amount is None:
        return ""
    return f"R$ {amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def row_for(item):
    contact = item.get("contactDetails") or {}
    agent = item.get("agentDetails") or {}
    channel = item.get("channelDetails") or {}
    dept = item.get("departmentDetails") or {}
    cls = item.get("classification") or {}
    utm = item.get("utm") or {}
    status = item.get("status")

    tempo_espera = item.get("timeWait") or ""
    tempo_atend = item.get("timeService") or ("" if status == "COMPLETED" else "Não concluído")

    return [
        item.get("number", ""),
        item.get("origin", ""),
        contact.get("name") or "",
        contact.get("phonenumberFormatted") or "",
        contact.get("instagram") or "",
        ", ".join(contact.get("tagsName") or []),
        agent.get("name") or "",
        channel.get("humanId") or "",
        channel.get("platform") or "",
        dept.get("name") or "",
        fmt_dt(item.get("createdAt")),
        fmt_dt(item.get("startAt")),
        fmt_dt(item.get("firstResponseAt")),
        fmt_dt(item.get("lastInteractionDate")),
        fmt_dt(item.get("endAt")),
        tempo_espera,
        tempo_atend,
        item.get("statusDescription") or "",
        cls.get("categoryName") or "",
        cls.get("categoryDescription") or "",
        fmt_money(cls.get("amount")) if cls else "",
        utm.get("source") or "",
        utm.get("campaign") or "",
        utm.get("headline") or "",
        utm.get("content") or "",
        utm.get("referralUrl") or "",
        "",  # Ultima Review/Nivel de Satisfação - não exposto pela API pública
        "",  # Ultima Review/Comentário - não exposto pela API pública
        item.get("previewUrl") or "",
        "",  # Concluído automaticamente - não exposto pela API pública
    ]


def build_report(token, date_str):
    protocol_prefix = date_str.replace("-", "")  # 2026-09-09 -> 20260909
    items = fetch_sessions(token, protocol_prefix)
    items.sort(key=lambda i: i.get("number", ""), reverse=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(HEADER)
    for c in ws[1]:
        c.font = Font(bold=True)
    for it in items:
        ws.append(row_for(it))

    for col in ws.columns:
        length = max((len(str(c.value)) for c in col if c.value), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max(length + 2, 10), 45)

    out_path = f"Relatorio_atendimentos_{date_str}.xlsx"
    wb.save(out_path)
    return out_path, len(items)


def main():
    if len(sys.argv) != 2:
        print("Uso: python gerar_relatorio.py YYYY-MM-DD")
        sys.exit(1)

    date_str = sys.argv[1]
    token = os.environ.get("FLW_TOKEN")
    if not token:
        print("Defina a variável de ambiente FLW_TOKEN com o token da API.")
        sys.exit(1)

    out_path, total = build_report(token, date_str)
    print(f"{total} atendimentos exportados para {out_path}")


if __name__ == "__main__":
    main()
