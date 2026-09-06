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

评测默认分成翻译和 Judge 两个阶段，各自以 8 路有界并发运行，并将逐条结果写入被 Git 忽略的 `.evaluation/<model>/`。中断后重复原命令会跳过已经完成的记录。公开数据文件沿用数据源代码 `no`、`ja`，进入评测后会分别标准化为业务代码 `nb`、`jp`，模型和 Judge 不会收到数据源别名：

```shell
python -u -m evaluate --stage translate --translation-concurrency 8
python -u -m evaluate --stage judge --judge-concurrency 8
```

`--stage all` 会依次执行两个阶段。每次执行会先验证 AWS 身份，失败时不会发起模型调用。限流、瞬时服务故障、网络超时以及 JSON 格式不可用时最多调用 3 次，并使用指数退避和 jitter；有效但质量较差的翻译不会重试。CSV 会记录总尝试与重试次数、首次调用是否返回、首次结果是否可用以及是否通过重试恢复；报告把“第一次即得到可用结果”定义为首次请求成功。Token 和延迟累计全部尝试。修改 Prompt Management Draft 或业务语言代码协议后必须增加 `--no-resume`，避免复用旧配置生成的 checkpoint；最终 CSV 只会在 Judge 阶段完整结束后原子更新。GPT-5.6 Luna 应通过 `--no-structured-output` 运行。

```shell
python -m report --port 8800
```

Judge 校准样本和操作说明见 [calibration/README.md](calibration/README.md)。当前评测 CSV 会分别记录调用、JSON 格式、目标语言、业务规则和 Judge 状态；`translation_structured` 表示翻译调用是否启用 Bedrock Structured Outputs，`translation_score` 是 MQM-lite 错误经固定权重计算出的语言质量分，`score` 暂时作为兼容别名保留。

当前 `haiku-4-5-opt` 方案对测试 Prompt `7ZJL56AKIU` 显式启用 Structured Outputs，Schema 为 `{"c": string}`。Schema 被拒绝时不会自动降级；输出不可解析时会按统一策略重试，并通过首次输出可用率保留格式能力差异。`haiku-4-5` 是复现当前线上 Prompt 与调用方式的对照组，即使模型支持也必须关闭 Structured Outputs。GPT-5.6 Luna 的 Bedrock 方案同样将该开关保持为 `False`，只通过 Prompt 约束输出格式；它使用 `us.openai.gpt-5.6-luna` inference profile，并保留 Prompt Management 中不可调的默认推理行为。

模型结果重建只允许修改和调用测试 Prompt `7ZJL56AKIU`。`1FWKA83D84` 会直接影响线上服务，不得读取、修改或调用；生产 Prompt `FQYN0INDHY` 同样不得修改。每次只配置并运行一个模型，完成后再切换下一个。

报告会用 `dataset + src + tgt + raw + ref` 识别同一样本，展示方案两两之间的配对胜/平/负、平均分差及配对 bootstrap 95% 置信区间。只有两个方案都有评分的共同样本才进入质量分比较，缺失覆盖会单独显示；数据集、语言方向和结构化错误类型可在配对明细中查看。
