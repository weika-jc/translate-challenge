# Luna reasoning effort none 评测

使用现有 Prompt Management + Converse 流程、原样 `prompt/gpt-5-6-luna`、同一 1,480 条样本和 Sonnet 4.6 Judge。额外参数仅为 `{"reasoning":{"effort":"none"}}`，不设置缓存参数或 cachePoint。翻译与 Judge 各 8 路并发，沿用原超时和最多 3 次调用策略。

| 指标 | effort none | 原 Luna |
|---|---:|---:|
| 样本数 | 1480 | 1480 |
| 已评分 | 1403 | 1480 |
| 平均分 | 98.91 | 99.11 |
| 调用失败 | 77 | 0 |
| 格式错误 | 0 | 0 |
| Judge 失败 | 0 | 0 |
| 平均延迟（ms） | 1663.07 | 1539.77 |
| P95 延迟（ms） | 3040.21 | 3332.98 |
| 缓存命中率（有 usage 的记录，%） | 97.36 | 97.16 |
| 重试次数 | 188 | 2 |
| 翻译成本估算（USD） | 0.088003 | 0.148816 |

共同可评分样本 1403 条，新方案胜 / 平 / 负：42 / 1299 / 62。配对平均分差（none − 原 Luna）为 -0.21，95% bootstrap 区间 [-0.41, -0.03]。

成本按 API 返回的 usage 估算，包含已返回的重试消耗，不包括 Judge。超时请求可能已产生未返回的消耗，因此该数值不是 AWS 最终账单。缓存命中率分母为有缓存 usage 的记录，质量均分只包含成功评分的样本；失败率和评分覆盖需同时比较。

费率为每百万 tokens：未缓存输入 $0.22、缓存读取 $0.022、缓存写入 $0.275、输出 $1.32。来源：[AWS Luna Geo CRIS 定价](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-luna.html)。

两次评测运行时间不同，服务负载和网络状态可能影响延迟与失败率，不能将所有差异单独归因于 reasoning effort。
