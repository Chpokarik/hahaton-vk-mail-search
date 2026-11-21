from unittest import TestCase

from receipt_ranking import ReceiptRanker


class ReceiptRankerTest(TestCase):
    def test_related_forms_can_recover_a_candidate(self):
        ranker = ReceiptRanker(["погрузка", "контейнер"], set())

        score = ranker.score(["контейнер", "погрузить"], {}, None)

        self.assertIsNotNone(score)

    def test_matching_action_in_subject_beats_shared_topic(self):
        ranker = ReceiptRanker(["уведомление", "отклонить", "платёж"], set())
        unrelated = ranker.score(["успешный", "оплата", "платёж"], {"оплата": 1}, 1)
        relevant = ranker.score(["операция", "отклонить"], {"отклонить": 1}, 0.7)

        self.assertGreater(relevant, unrelated)

    def test_unrelated_ids_do_not_match_by_prefix(self):
        ranker = ReceiptRanker(["123456789"], set())

        self.assertIsNone(ranker.score(["123456780"], {}, None))
