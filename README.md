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

Judge 校准样本和操作说明见 [calibration/README.md](calibration/README.md)。当前评测 CSV 会分别记录调用、JSON 格式、目标语言、业务规则和 Judge 状态；`translation_score` 是 MQM-lite 错误经固定权重计算出的语言质量分，`score` 暂时作为兼容别名保留。
