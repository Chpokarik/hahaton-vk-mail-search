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

    def test_colloquial_receipt_verbs(self):
        for verb in ("пришёл", "пришел", "пришла", "пришло", "пришли"):
            with self.subTest(verb=verb):
                self.assertEqual(
                    parse_receipt_query(f"Какие заказы {verb} вчера?", self.reference).day,
                    date(2025, 12, 31),
                )

    def test_supported_absolute_formats(self):
        for date_phrase in ("20 ноября 2025 года", "20 ноября", "20.11.2025", "2025-11-20"):
            with self.subTest(date_phrase=date_phrase):
                self.assertEqual(
                    parse_receipt_query(f"Заказы, полученные {date_phrase}", self.reference).day,
                    date(2025, 11, 20),
                )

    def test_invalid_date_and_range_do_not_force_an_exact_day(self):
        for query in (
            "Оплата 31 февраля 2026",
            "Оплатить до 25 января",
            "Счета со вчера на сегодня",
            "письма с 10 по 15 марта",
            "письма с 10 марта по 15 марта",
            "события между 10 и 15 марта",
            "письма, полученные с 10 по 15 марта",
            "письма, полученные с 10 марта по 15 марта",
            "письма, полученные между 10 и 15 марта",
        ):
            with self.subTest(query=query):
                self.assertEqual(parse_receipt_query(query, self.reference), ReceiptQuery(query))

    def test_event_date_is_not_a_receipt_date(self):
        query = "Найди письмо о мероприятии 20 ноября 2025 года"
        self.assertEqual(
            parse_receipt_query(query, self.reference),
            ReceiptQuery("письмо о мероприятии 20 ноября 2025 года"),
        )

    def test_document_date_after_from_is_not_assumed_to_be_receipt_date(self):
        query = "Заказы от 20 ноября 2025 года"
        self.assertEqual(parse_receipt_query(query, self.reference), ReceiptQuery(query))

    def test_receipt_date_is_selected_when_query_mentions_event_date_too(self):
        query = "Покажи письмо о мероприятии 20 ноября 2025 года, полученное 21 ноября 2025 года"
        self.assertEqual(
            parse_receipt_query(query, self.reference),
            ReceiptQuery("письмо о мероприятии 20 ноября 2025 года", date(2025, 11, 21)),
        )

    def test_unanchored_relative_date_is_not_a_receipt_filter(self):
        query = "Найди письмо о встрече вчера"
        self.assertEqual(parse_receipt_query(query, self.reference), ReceiptQuery("письмо о встрече вчера"))
