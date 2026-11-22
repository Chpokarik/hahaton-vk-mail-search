"""Generate a small, deterministic synthetic mailbox for public demos."""

from __future__ import annotations

import json
import zipfile
from datetime import date, timedelta
from pathlib import Path


SUBJECTS = (
    "Счет за интернет",
    "Бронирование гостиницы",
    "Доставка заказа",
    "Встреча команды",
    "Оплата билета",
    "Отчет по проекту",
    "Подтверждение записи",
    "Договор аренды",
    "Заказ оборудования",
    "Перенос мероприятия",
)
TEXTS = (
    "Проверьте документ и подтвердите получение сообщения.",
    "Оплата прошла успешно, квитанция доступна в личном кабинете.",
    "Свяжитесь с менеджером, если потребуется изменить детали.",
    "Срок ответа указан в приложении к этому сообщению.",
    "Мы отправили обновленную информацию по вашему запросу.",
    "Номер заявки и дополнительные сведения находятся ниже.",
    "Спасибо за обращение, хорошего дня и удачной недели.",
)


def build(path: Path, documents: int, mailboxes: int) -> None:
    anchor = date(2026, 1, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
        with archive.open("documents.jsonl", "w") as stream:
            for number in range(documents):
                mailbox_number = number % mailboxes
                subject = SUBJECTS[(number * 7 + mailbox_number) % len(SUBJECTS)]
                body = " ".join(TEXTS[(number + index * 3) % len(TEXTS)] for index in range(4))
                received = anchor - timedelta(days=(number * 17 + mailbox_number) % 300)
                message = {
                    "doc_id": f"demo-{number:07d}",
                    "synthetic_user": f"demo-box-{mailbox_number:03d}",
                    "doc_dt": received.isoformat(),
                    "doc": f"Тема: {subject}\n\n{body} Код письма DEMO-{number:07d}.",
                }
                stream.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        archive.writestr(
            "manifest.json",
            json.dumps({"documents": documents, "mailboxes": mailboxes, "synthetic": True}),
        )


if __name__ == "__main__":
    build(Path("/tmp/mail-demo.zip"), documents=10_000, mailboxes=50)
