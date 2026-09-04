# Judge 校准

本目录用于校准“Judge 模型 + Prompt/rubric + 输出协议 + 程序计分公式”这一整套自动评判系统。

运行在线校准前需保证 `aigc` profile 可用；凭证过期时先执行 `aws sso login --profile aigc`。

`human-labels.csv` 已使用当前 `bingofrenzy-translator` Draft 重新翻译；实际模型和 Prompt ARN 记录在匿名映射文件中。需要再次刷新候选时运行：

```shell
python -m evaluate.calibration refresh-human \
  --prompt-arn arn:aws:bedrock:us-west-2:686465264859:prompt/7ZJL56AKIU
```

## 人工标注

`human-labels.csv` 是匿名候选译文表，`human-label-map.csv` 保存候选与模型的对应关系。标注时不要查看 map 文件或旧分数，避免模型身份和旧 Judge 分数影响判断。

只填写以下四列：

- `acceptable`：`yes` 或 `no`。新一轮采用宽松口径：存在 `major/critical` 时填 `no`，只有 `none/minor` 时填 `yes`；
- `worst_severity`：`none`、`minor`、`major` 或 `critical`；
- `primary_category`：有错误时填写 `accuracy`、`fluency`、`tone`、`terminology` 或 `preservation`；无错误时留空；
- `note`：可选，一句话说明。

先用 `dev` 行调整 Judge。调整完成后，再单独运行一次 `holdout`；不要根据 holdout 结果继续改同一版 Prompt，否则它不再是留出验证集。

```shell
python -m evaluate.calibration run-human --split dev
python -m evaluate.calibration run-human --split holdout --output calibration/human-holdout-results.csv
```

初始验收目标：可接受性一致率不低于 85%，人工标记 `major/critical` 的召回率不低于 90%。

当前 Judge Prompt 已在 dev 上完成调整并冻结。16 条 `holdout` 已严格运行一次，但未通过验收；本批 holdout 不再用于调整当前 Prompt。后续若继续调优，需要先复核标注口径并重新划分新的留出集，才能再次宣称是独立验证。

面向最终业务结论的校准仍需等待真实数据。新一轮不再使用当前 Prompt 中从少量 dev 个例归纳出的针对性规则；`minor` 只作为弱信号和小幅扣分，不参与可接受性验收。

在真实业务数据到位前，第二轮使用现有带参考译文数据验证宽松协议。100 条样本的标注、排除项和最终结论位于 `calibration/round2/`；冻结配置已经通过第二轮 holdout 的临时宽松门槛。真实业务数据到位后，需要另建业务校准集重新验证。

## 自动损坏对照

`contrastive.jsonl` 以参考译文作为较好候选，自动构造原文照抄、数字替换、占位符/emoji 删除或内容删除的较差候选。`contrastive-seeds.jsonl` 额外覆盖当前公开数据缺少的业务边界。重建并运行：

```shell
python -m evaluate.calibration build-contrastive
python -m evaluate.calibration run-contrastive
```

结果同时报告 `judge_accuracy`（只比较 LLM 质量分）和 `system_accuracy`（先比较语言/策略硬失败数量，再比较 LLM 质量分）。验收目标以整套系统的 `system_accuracy >= 95%` 为准，同时观察 `judge_accuracy` 判断 LLM 本身的改进空间。该测试适合做 Prompt 回归检查，但不能替代人工判断自然改写是否可接受。
