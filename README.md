usage:

评测优化计划见 [docs/evaluation-optimization-plan.md](docs/evaluation-optimization-plan.md)。

```shell
python -m pip install -r requirements.txt
```

```shell
python -u -m download output
```

```shell
python -u -m evaluate
```

```shell
python -m report --port 8800
```

Judge 校准样本和操作说明见 [calibration/README.md](calibration/README.md)。当前评测 CSV 会分别记录调用、JSON 格式、目标语言、业务规则和 Judge 状态；`translation_structured` 表示翻译调用是否启用 Bedrock Structured Outputs，`translation_score` 是 MQM-lite 错误经固定权重计算出的语言质量分，`score` 暂时作为兼容别名保留。

当前 `haiku-4-5-opt` 方案对测试 Prompt `7ZJL56AKIU` 显式启用 Structured Outputs，Schema 为 `{"c": string}`。格式能力是方案指标的一部分，因此 Schema 被拒绝或输出不可解析时不会在业务层自动降级、修复或重试。后续 GPT-5.6 Luna 的 Bedrock 方案应将该开关保持为 `False`，只通过 Prompt 约束输出格式。

报告会用 `dataset + src + tgt + raw + ref` 识别同一样本，展示方案两两之间的配对胜/平/负、平均分差及配对 bootstrap 95% 置信区间。只有两个方案都有评分的共同样本才进入质量分比较，缺失覆盖会单独显示；数据集、语言方向和结构化错误类型可在配对明细中查看。
