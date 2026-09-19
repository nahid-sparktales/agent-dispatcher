---
name: retrieval-rag
description: Build and fix retrieval that actually returns the right passage — structure-aware chunking, one pinned embedding model, lexical plus vector search fused, reranking, and a recall measurement that is run separately from the generator. Use when a RAG system answers wrong or vaguely, when an index is being designed or reindexed, or when someone proposes a prompt change to fix what is really a retrieval miss. Not for prompt or output-quality work once the right passage is already in context, not for agent memory design, and not for choosing a vector database.
---

# Retrieval for RAG

Most "the model hallucinated" reports are retrieval failures wearing a generation costume. The
gold passage was never in the context window, and no prompt edit can fix that. The first job is
always to find out which half is broken.

## When this fires

A system retrieves documents and feeds them to a model, and the answers are wrong, thin, or
unsourced — or an index is being built or rebuilt. It does not fire when the correct passage is
demonstrably in context and the model still answers badly; that is a generation problem.

## Procedure

1. **Split the failure before fixing anything.** Take 10 real failing questions. For each, check
   whether the passage that answers it appears in the retrieved set at all. Retrieved and answered
   wrong is a generation problem; never retrieved is a retrieval problem. Do not proceed on a
   guess — this one check redirects most of the work.
2. **Build the evaluation set before touching the index.** 30–50 real questions, each labelled
   with the id(s) of the passage that answers it. Get them from real logs where possible. Without
   this set every later change is a reshuffle you cannot tell from an improvement.
3. **Chunk on the document's own structure** — headings, sections, list items, function or code
   blocks — wherever structure exists. Fall back to fixed-size windows only for unstructured prose,
   with enough overlap that a sentence is not cut in half.
4. **Make each chunk self-describing.** Prepend the document title and heading path to the text
   that gets embedded. A chunk retrieved alone must still say what it is about; "it depends on the
   previous section" is invisible to the retriever and to the model.
5. **Store the metadata you will need at query time**: stable chunk id, source document and URI,
   heading path, position, timestamp, and any tenant or permission key. You cannot filter on what
   you did not index, and adding a field later means a reindex.
6. **Pin one embedding model and record it with the index** — name, version, dimension, and
   whether vectors are normalized. Queries and documents must be embedded by the same model, with
   the same query/document prefix convention if that model asks for one. Changing the model
   invalidates every stored vector: that is a reindex, not a config tweak.
7. **Add lexical search next to the vector search.** Embeddings miss exact tokens — error codes,
   identifiers, rare product names, negation. Run a keyword index (BM25 or the database's own
   full-text search) over the same chunks.
8. **Fuse the two result lists by rank, not by raw score.** Scores from a vector index and a
   keyword index are not on a common scale. Reciprocal rank fusion needs no tuned weights and is
   the correct default; introduce weights only after measuring that fusion alone is not enough.
9. **Retrieve wide, then rerank narrow.** Pass roughly the top 50 fused results through a
   reranking model (a cross-encoder scores query and passage together, unlike the bi-encoder that
   built the index) and keep only the handful the generator sees. After hybrid search this is
   usually the largest single gain left.
10. **Filter by permission at query time**, as part of the search, not afterwards and never by
    asking the model to stay quiet about what it read. A chunk the requester may not read must not
    enter the prompt. If the index has no tenant or permission key, stop and raise it — that is a
    data boundary, not a tuning detail.
11. **Measure retrieval on its own**, generator switched off: recall@k (is the labelled passage
    anywhere in the top k) at the exact k you will pass to the model, plus MRR or nDCG for
    ordering. Record the number before and after each change, on the same query set.
12. **Then measure generation with retrieval held fixed**: is every claim supported by a retrieved
    passage, do the citations point at the passage that actually carries the claim, and is the
    answer right. Changing both layers in one run tells you nothing about either.
13. **Decide what happens when nothing is relevant.** Below a score threshold, return "not found"
    rather than the nearest chunk. A confident answer over irrelevant context is the dominant
    hallucination source in RAG.
14. **Re-run the whole set after every change** to chunking, embedding, fusion or reranking. These
    interact: a chunking change moves recall, and a reranker tuned against the old chunks may not
    survive it.

## Checklist

- [ ] Failing questions classified as retrieval miss or generation miss, with evidence
- [ ] Labelled query set exists, and predates the changes being measured
- [ ] Chunks carry their heading path and a stable id
- [ ] Embedding model, version and dimension recorded alongside the index
- [ ] Lexical search present and fused with vector search by rank
- [ ] Reranking applied between wide retrieval and the generator's k
- [ ] Permission or tenant filtering happens inside the query
- [ ] recall@k measured at the real k, before and after, on the same set
- [ ] Generation measured separately, with retrieval frozen
- [ ] A no-answer path exists and was exercised

## Failure handling

- **Gold passage never appears at any k** — the problem is chunking, the embedding model, or
  missing content. Prompt edits and reranking cannot recover a passage retrieval never returned.
- **Recall is high but answers are still wrong** — stop tuning retrieval. The remaining problem is
  the prompt, the context ordering, or the model.
- **Improvement shows only on hand-picked queries** — that is not evidence. Report the full-set
  delta or report nothing.
- **Reindexing is required** — say so plainly, with the cost and the downtime, and ask before
  starting one on a live index. Dropping or overwriting a production index is destructive: propose
  it, do not perform it unprompted.
- **The corpus changed under you** — an eval run against a different snapshot is not comparable.
  Record the corpus version with every number.

## Evidence to report

The query set size and where the questions came from; recall@k and MRR or nDCG before and after,
at the k actually used, with the embedding model, reranker, fusion method and corpus snapshot
named; the queries that still fail and what is missing for each; and, when generation was
measured, that it was measured with retrieval frozen. "Retrieval improved" without a number and a
query set is an impression, not a result.
