REASONS_PT = {
    "kill switch file is present": "kill switch ativo: arquivo KILL_SWITCH encontrado",
    "daily loss limit reached": "limite de perda diaria atingido",
    "weekly loss limit reached": "limite de perda semanal atingido",
    "monthly loss limit reached": "limite de perda mensal atingido",
    "max drawdown reached": "drawdown maximo permitido atingido",
    "max daily trades reached": "limite maximo de trades diarios atingido",
    "no quote balance": "saldo em moeda de cotacao insuficiente",
    "max exposure reached": "exposicao maxima permitida atingida",
    "cycle completed": "ciclo concluido",
    "loop stopped": "loop encerrado",
}


def pt_reason(reason: str) -> str:
    return REASONS_PT.get(reason, reason)
