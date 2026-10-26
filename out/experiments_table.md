| variant | change | judge | tokens / successful task | of which cached | thinking | calls / task | sec / task | $ / successful task | cost index |
|---|---|---|---|---|---|---|---|---|---|
| baseline | (baseline) | 8/8 | 30,034 | 0 (0.0%) | 567 | 2.38 | 9.4 | 0.02511 | 100 |
| thinking_medium | thinking=medium | 8/8 | 29,169 | 0 (0.0%) | 362 | 2.5 | 7.6 | 0.02382 | 95 |
| thinking_low | thinking=low | 8/8 | 20,908 | 0 (0.0%) | 195 | 2.0 | 5.6 | 0.01689 | 67 |
| static_first | layout=static_first | 8/8 | 25,181 | 17,096 (70.2%) | 612 | 2.0 | 8.4 | 0.00981 | 39 |
| no_glossary | glossary=False | 8/8 | 72,134 | 0 (0.0%) | 2,755 | 4.75 | 29.7 | 0.06392 | 255 |
| best | layout=static_first, thinking=low | 8/8 | 19,530 | 16,402 (84.9%) | 0 | 2.0 | 7.1 | 0.00419 | 17 |
| model_argon | model=gemini-4-argon | 8/8 | 21,828 | 0 (0.0%) | 237 | 2.0 | 14.3 | 0.04733 | 188 |
| model_claude | model=claude-sonnet-5-5 | 8/8 | 27,894 | 0 (0.0%) | 0 | 2.0 | 3.4 | 0.07225 | 288 |
| claude_static_first | model=claude-sonnet-5-5, layout=static_first | 8/8 | 28,413 | 15,085 (53.8%) | 11 | 2.0 | 3.4 | 0.03897 | 155 |
