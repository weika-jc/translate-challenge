usage:

```shell
python -m pip install -r requirements.txt
```

```shell
python -u -m download output
```

```shell
BEDROCK_PROMPT_ARN='your-managed-prompt-arn' python -u -m evaluate
```

评测默认分成翻译和 Judge 两个阶段，各自以 8 路有界并发运行，并将逐条结果写入被 Git 忽略的 `.evaluation/<model>/`。中断后重复原命令会跳过已经完成的记录。公开数据文件沿用数据源代码 `no`、`ja`，进入评测后会分别标准化为业务代码 `nb`、`jp`，模型和 Judge 不会收到数据源别名：

```shell
python -u -m evaluate --stage translate --translation-concurrency 8
python -u -m evaluate --stage judge --judge-concurrency 8
```

`--stage all` 会依次执行两个阶段。每次执行会先验证 AWS 身份，失败时不会发起模型调用。限流、瞬时服务故障、网络超时以及 JSON 格式不可用时最多调用 3 次，并使用指数退避和 jitter；有效但质量较差的翻译不会重试。CSV 会记录总尝试与重试次数、首次调用是否返回、首次结果是否可用以及是否通过重试恢复；报告把“第一次即得到可用结果”定义为首次请求成功。Token 仍累计全部尝试以保留真实成本，并分别记录未缓存输入、缓存读取、缓存写入和输出 Token；价格也按四种 Token 的对应费率计算。旧 CSV 没有缓存读写字段时继续沿用原来的缓存读取价估算。延迟只记录最后一次成功的 Bedrock 调用，不包含失败请求、退避等待或更早的重试。若所有调用均未成功返回，延迟留空。修改 Prompt Management Draft 或业务语言代码协议后必须增加 `--no-resume`，避免复用旧配置生成的 checkpoint；最终 CSV 只会在 Judge 阶段完整结束后原子更新。GPT-5.6 Luna 应通过 `--no-structured-output` 运行。

```shell
python -m report --port 8800
```

Judge 校准样本和操作说明见 [calibration/README.md](calibration/README.md)。当前评测 CSV 会分别记录调用、JSON 格式、目标语言、业务规则和 Judge 状态；`translation_structured` 表示翻译调用是否启用 Bedrock Structured Outputs，`translation_score` 是 MQM-lite 错误经固定权重计算出的语言质量分，`score` 暂时作为兼容别名保留。

当前 `haiku-4-5-opt` 方案显式启用 Structured Outputs，Schema 为 `{"c": string}`。Schema 被拒绝时不会自动降级；输出不可解析时会按统一策略重试，并通过首次输出可用率保留格式能力差异。`haiku-4-5` 是复现当前线上 Prompt 与调用方式的对照组，即使模型支持也必须关闭 Structured Outputs。GPT-5.6 Luna 的 Bedrock 方案同样将该开关保持为 `False`，只通过 Prompt 约束输出格式；它使用 `us.openai.gpt-5.6-luna` inference profile，并保留 Prompt Management 中不可调的默认推理行为。

Prompt ARN 和 Prompt ID 不写入仓库。运行评测时通过 `BEDROCK_PROMPT_ARN` 或 `--model-id` 传入；更新 Prompt Management Draft 时通过 `BEDROCK_PROMPT_ID` 或 `--prompt-id` 传入。每次只配置并运行一个实验模型，完成后再切换下一个。对外结果会将 Prompt ARN 记为 `managed-prompt`，不暴露具体资源标识。

查询并交互修改 Prompt Management Draft 的模型参数时使用：

```shell
python -m evaluate.manage_prompt_parameters
```

脚本会交互询问 Prompt ID，默认使用 `aigc` profile 和 `us-west-2`；也可通过 `--prompt-id`（或 `BEDROCK_PROMPT_ID`）、`--profile`、`--region` 传入。启动后会展示当前默认变体的 Prompt 模板与参数，但不会输出完整 ARN/account；使用 `set`、`delete` 或 `luna-defaults` 编辑，输入 `apply` 并二次确认后才会调用 `UpdatePrompt`。只查询可增加 `--show-only`。脚本会在更新前检查 Draft 是否被并发修改，并在更新后确认 Prompt 内容、模型绑定及 KMS 配置未改变。

业务 Prompt 保留在 `prompt/`；评分时使用 `prompt-eval/` 中的同名文件。评分版仅移除了不当言论的整句替换规则和对应示例，其余翻译契约必须与业务版同步。业务 Prompt 变更后运行 `python -m evaluate.evaluation_prompt` 重建评分版，同步测试会拒绝其他差异。

`gpt-5-6-luna-no-reasoning` 是 Luna 的独立实验方案：只在基础 Luna Prompt 中增加“这是直接翻译任务、不需要推理或解释、立即返回 JSON 结果”的指令。该名称描述的是 Prompt 实验变量，不代表 Bedrock 调用参数关闭了模型推理。

报告会用 `dataset + src + tgt + raw + ref` 识别同一样本，展示方案两两之间的配对胜/平/负、平均分差及配对 bootstrap 95% 置信区间。只有两个方案都有评分的共同样本才进入质量分比较，缺失覆盖会单独显示；数据集、语言方向和结构化错误类型可在配对明细中查看。
