# Diagnostic query controls

These eight queries are a small, manually curated diagnostic set over five mailboxes that do not occur in the public development query set. They cover paraphrasing, a spelling error, multiple constraints, named entities, a topical search, and two cases where a date inside a message must not be mistaken for its receipt date.

`qrels.jsonl` is a hand-built relevance control, not an organizer-provided gold set. Its predicates are intentionally transparent and limited: invoice messages naming Kuzma Shubin, penalty messages naming Eremey Sukhanov, buyer-cancelled orders, the monitor-cleaning product, missing-field database errors, and two individually inspected event-date messages. The broad predicates can mark many similar messages relevant, so scores are diagnostic and must not be presented as an official or general benchmark result. On the event-plus-receipt-date query, the old parser left both dates unparsed and returned the target at rank 24; the updated parser filters to the receipt date and returns it at rank 1.

Run with `python evaluate.py --suite controls`. Public and control results are reported separately, each split into queries with and without an explicitly parsed receipt-date filter.
