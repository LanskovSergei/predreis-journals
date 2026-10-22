"""Сборка ZIP-контейнера электронного журнала. ЗАГЛУШКА: описывает шаги согласно ТЗ, стр. 21."""

from __future__ import annotations

from collections.abc import Sequence

from app.core.errors import NotImplementedYetError
from app.core.security import Principal
from app.integrations.predreis.client import Signer
from app.models.documents import EJournal
from app.models.records import MedicalRecord, TechnicalRecord


class ContainerBuilder:
    """Строитель контейнера журнала (документ типа 2)."""

    async def build_package(
        self, journal: EJournal, records: Sequence[MedicalRecord | TechnicalRecord]
    ) -> None:
        """Готовит пакет при «Отправить на подпись».

        TODO: собрать в хранилище файлы журнала:
          1. journal.xml — машиночитаемый журнал (схема утверждается отдельно);
          2. по каждой записи: .xml, .pdf, .sig, .tsp из record_documents;
          3. manifest.xml — состав контейнера, SHA-256 файлов, идентификаторы, даты;
          4. реестр документов (тип, размер, SHA-256, какая подпись к какой записи);
          5. audit-log по записям журнала (экспорт из audit_log, с хеш-цепочкой);
          6. сертификаты УЦ / данные OCSP на момент подписания;
          7. README: версия формата, стандарты, порядок проверки подписей.
        """
        raise NotImplementedYetError("Сборка ZIP-контейнера ещё не реализована")

    async def finalize(self, journal: EJournal, signer: Signer, principal: Principal) -> None:
        """Завершает журнал при подписи СА.

        TODO: подписать journal.xml УКЭП организации через signer (SignatureKind.ORGANIZATION),
        получить TSP, отрендерить журнальный PDF с синей плашкой подписи (шаблон `stamp`
        в _base.html), упаковать итоговый ZIP, посчитать SHA-256, записать ключи
        (xml_key/pdf_key/sig_key/zip_key/zip_sha256) в journal.
        """
        raise NotImplementedYetError("Подпись и упаковка журнала ещё не реализованы")
