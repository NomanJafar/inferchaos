| fault | requests | errors | 429s | budget consumed | peak burn rate | alerts fired | breaker opened after | slow before breaker | fallbacks | recovery |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 840 | 0 | 0 | 0% of the run's budget | 0x | none | – | 0 | 0 | – |
| throttle | 841 | 0 | 0 | 523% of the run's budget | 67x | ticket @ 1s, page @ 4s | 7.1 s | 40 | 44 | 3.2 s |
| kill | 842 | 0 | 0 | 0% of the run's budget | 0x | none | 5.6 s | 0 | 36 | 3.2 s |
| spike | 3361 | 0 | 2324 | 0% of the run's budget | 0x | none | – | 0 | 0 | 3.0 s |
