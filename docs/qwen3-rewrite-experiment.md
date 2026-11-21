# Qwen3-1.7B query-rewrite experiment

## Setup

Tested the [Qwen3-1.7B model](https://huggingface.co/Qwen/Qwen3-1.7B) through the [GGUF Q4_K_M quantization](https://huggingface.co/ggml-org/Qwen3-1.7B-GGUF), using llama-cpp-python 0.3.37 on CPU. The source model is 1.7 billion parameters, below the 3-billion limit. The downloaded quantized file is about 1.194 GiB and stays in the ignored `backend/.cache/qwen3-1.7b/` directory. It is not part of the backend requirements or request path.

The model was asked to add short Russian search alternatives while preserving names, IDs, dates, and facts. On seven no-receipt-date diagnostic queries, results were:

| Ranker input | Recall@10 | nDCG@10 | MRR@10 |
| --- | ---: | ---: | ---: |
| Original query | 0.4792 | 0.6100 | 0.6012 |
| Rewrite only | 0.4739 | 0.6489 | 0.7302 |
| Reciprocal-rank union of original and rewrite | 0.4788 | 0.6183 | 0.6476 |

These are hand-labeled development controls, not an independent benchmark. The rewrite-only result improves ordering on this small set, while the union gives a much smaller gain. A few generated rewrites were noisy or added a placeholder such as `[дату]`.

## Latency and decision

With thinking disabled, generation latency over the same seven unique queries was p50 **917 ms**, p95 **1,546 ms**, and maximum **1,546 ms**. The default thinking mode used 1.2–1.7 seconds for short prompts and often spent the output budget on reasoning. These timings are for one CPU request at a time and exclude the search itself. The no-thinking p95 already exceeds the strict 1-second search requirement before adding retrieval/reranking; concurrency would require a separate capacity test.

The experiment shows that a local 1.7B model can produce useful query alternatives, but it does not make search faster and it does not currently satisfy the latency target. Keep it out of synchronous retrieval/reranking. The integrated backend continues using BM25, local 128M Potion embeddings, the deterministic topic ranker, and LightGBM.
