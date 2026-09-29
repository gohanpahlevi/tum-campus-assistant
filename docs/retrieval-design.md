# Why retrieval is keyword matching and not embeddings

This is the write-up from the point in the project where we removed the vector store. It is kept because the decision looks backwards without it.

## What was there first

The first working version ran three search methods against the same knowledge base.

Semantic search embedded the query with sentence-transformers and looked it up in ChromaDB. Keyword search scored term overlap against the entry fields. Hybrid search combined the two scores.

Each returned its own ranking, and the three did not agree.

## Why we dropped it

**The scores were not comparable.** Cosine similarity from the embedding model and the additive keyword score are on different scales. Combining them meant picking a weight, and any weight we picked was a guess that changed which entries won. Nobody could predict the hybrid ranking from the two inputs.

**The corpus is small and curated.** 270 entries, each one a question and answer pair written by hand, already tagged with category, role and keywords. Embeddings earn their cost on large or messy corpora where the useful signal is not in the words. Here the useful signal is in the words, and the tags carry the rest.

**Short institutional terms were the failure case.** A user asking about "LIV" got nothing, even though entries mentioning "LIV library" were in the base. The embedding had no idea what LIV was, so it returned nothing close, and the keyword pass tokenised the entry into whole words and never tested the substring. The fix that worked was not a better model. It was a list of short terms that also match inside a longer string.

**Startup cost was real.** Loading the sentence-transformers model and opening ChromaDB added seconds to container start and a few hundred megabytes of memory. On Cloud Run, where instances start cold, that is paid on the first request after every scale to zero.

## What replaced it

One keyword pass, in `optimized_search` in `backend/chatbot_v2.py`.

The query is expanded through a synonym map, so "hungry" reaches entries about the mensa. Then every entry is scored once. Exact phrase and question-title matches score highest. Category, role and campus matches add to it. Terms in `CRITICAL_KEYWORDS` score again if they appear as a substring, which is the LIV fix.

Ranking is now readable. Given a query and an entry, the score can be worked out by hand, which is what made the remaining relevance problems fixable.

## What this is not

This is the right call for 270 curated entries with hand written tags. It is the wrong call for a corpus that is large, growing, or written by many people who do not share vocabulary. At that point the tags stop being reliable, the synonym map stops being maintainable, and the embedding starts earning its cost.

Nothing here says embeddings do not work. It says they were not what this corpus needed.
