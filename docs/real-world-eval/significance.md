# A/B Statistical Significance Analysis (full sample)

> Full-size real evaluation (C-Eval 61 / THUCNews 120 / HumanEval 60), bootstrap n=2000, 95% CI.
> Pairing: DeepSeek V4 Flash (Qiniu) vs DeepSeek V3 (Qiniu).

## C-Eval QA

- Paired rows: 61
- V4 Flash: 86.89% (95% CI [78.7%, 95.1%])
- V3: 70.49% (95% CI [59.0%, 82.0%])
- Mean diff: +16.39% (95% CI [+4.9%, +27.9%])
- bootstrap p = 0.0070, McNemar p = 0.0162
- Conclusion: SIGNIFICANT

## THUCNews Classification

- Paired rows: 120
- V4 Flash: 89.17% (95% CI [83.3%, 94.2%])
- V3: 84.17% (95% CI [77.5%, 90.0%])
- Mean diff: +5.00% (95% CI [+0.0%, +10.8%])
- bootstrap p = 0.0690, McNemar p = 0.1489
- Conclusion: NOT significant

## HumanEval Coding

- Paired rows: 60
- V4 Flash: 58.33% (95% CI [46.7%, 70.0%])
- V3: 65.00% (95% CI [53.3%, 76.7%])
- Mean diff: -6.67% (95% CI [-13.3%, -1.7%])
- bootstrap p = 0.0250, McNemar p = 0.1336
- Conclusion: SIGNIFICANT
