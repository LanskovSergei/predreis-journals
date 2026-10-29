"""Вид договора организации и журналы, которые для неё ведутся (решение заказчика).

«мед» — только медосмотры, «тех» — только техконтроль (оба только на бумаге),
«медтех» — оба журнала (бумага и ЭПЛ). Журнала, которого нет в договоре, у организации нет:
записи не создаются, клиент его не видит. Вид договора не указан (у организаций из платформы
его нет: ЭПЛ всегда «медтех») — ведутся оба журнала.
"""

from __future__ import annotations

from app.domain.enums import ContractType, JournalKind

_JOURNALS = {
    ContractType.MED: frozenset({JournalKind.MEDICAL}),
    ContractType.TECH: frozenset({JournalKind.TECHNICAL}),
    ContractType.MEDTECH: frozenset({JournalKind.MEDICAL, JournalKind.TECHNICAL}),
}
ALL_JOURNALS = frozenset({JournalKind.MEDICAL, JournalKind.TECHNICAL})


def journals_for(contract: ContractType | None) -> frozenset[JournalKind]:
    """Журналы, которые ведутся по договору."""
    return ALL_JOURNALS if contract is None else _JOURNALS[contract]


def journal_allowed(contract: ContractType | None, kind: JournalKind) -> bool:
    """Ведётся ли журнал этого вида по договору организации."""
    return kind in journals_for(contract)


CONTRACT_EXCLUDES_MESSAGE = {
    JournalKind.MEDICAL: "По договору организации медосмотры не ведутся (договор «тех»)",
    JournalKind.TECHNICAL: "По договору организации техконтроль не ведётся (договор «мед»)",
}
