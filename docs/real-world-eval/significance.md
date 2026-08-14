# A/B Statistical Significance Analysis (full sample, fixed code sandbox)

> Full-size real evaluation (C-Eval 61 / THUCNews 120 / HumanEval 60), bootstrap n=2000, 95% CI.
> Pairing: DeepSeek V4 Flash (Qiniu) vs DeepSeek V3 (Qiniu).

## C-Eval QA

- V4 Flash: 86.89% (95% CI [78.7%, 95.1%])
- V3: 70.49% (95% CI [59.0%, 82.0%])
- Mean diff: +16.39% (CI [+4.9%, +27.9%])
- bootstrap p = 0.0070, McNemar p = 0.0162
- Conclusion: SIGNIFICANT

## THUCNews Classification

- V4 Flash: 89.17% (95% CI [83.3%, 94.2%])
- V3: 84.17% (95% CI [77.5%, 90.0%])
- Mean diff: +5.00% (CI [+0.0%, +10.8%])
- bootstrap p = 0.0690, McNemar p = 0.1489
- Conclusion: NOT significant

## HumanEval Coding

- V4 Flash: 95.00% (95% CI [88.3%, 100.0%])
- V3: 100.00% (95% CI [100.0%, 100.0%])
- Mean diff: -5.00% (CI [-11.7%, +0.0%])
- bootstrap p = 0.0680, McNemar p = 0.2482
- Conclusion: NOT significant
