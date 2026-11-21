from datetime import date
from unittest import TestCase

from query_dates import ReceiptQuery, parse_receipt_query


class ReceiptDateTest(TestCase):
    reference = date(2026, 1, 1)

    def test_relative_day_across_year_boundary(self):
        self.assertEqual(
            parse_receipt_query("Покажи чеки, полученные вчера.", self.reference),
            ReceiptQuery("чеки", date(2025, 12, 31)),
        )

    def test_supported_absolute_formats(self):
        for date_phrase in ("20 ноября 2025 года", "20 ноября", "20.11.2025", "2025-11-20"):
            with self.subTest(date_phrase=date_phrase):
                self.assertEqual(
                    parse_receipt_query(f"Заказы от {date_phrase}", self.reference).day,
                    date(2025, 11, 20),
                )

    def test_invalid_date_and_range_do_not_force_an_exact_day(self):
        for query in ("Оплата 31 февраля 2026", "Оплатить до 25 января", "Счета со вчера на сегодня"):
            with self.subTest(query=query):
                self.assertEqual(parse_receipt_query(query, self.reference), ReceiptQuery(query))
