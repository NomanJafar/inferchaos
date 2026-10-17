| fault | requests | errors | 429s | budget consumed | peak burn rate | alerts fired | breaker opened after | slow before breaker | fallbacks | recovery |
|---|---|---|---|---|---|---|---|---|---|---|
| kill (real vLLM on T4) | 1827 | 0 | 0 | 219% of the run's budget | 100x | page @ -59s, ticket @ -59s, ticket @ 222s, page @ 225s | -56.2 s | 0 | 65 | 3.1 s |
