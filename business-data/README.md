# 业务数据集（Business Data）

本目录存放用于**业务场景评测**的公开数据集。由于单文件体积较大（>19 MB），
已通过 `.gitignore` 排除，不入库；请按下方说明自行下载后放到本目录。

| 文件 | 场景 | 行数 | 说明 | 来源 |
|------|------|------|------|------|
| `Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv` | 客服对话意图分类 | ~27K | 多语言客服意图标注（intent + response），适合做 customer-service 场景评测 | [Bitext Customer Support Dataset](https://www.kaggle.com/datasets/bitext/training-dataset-for-chatbots-response-generation) |
| `online-retail.xlsx` | 电商零售交易分析 | ~540K | 英国在线零售商 2010-2011 交易流水，适合做结构化数据分析类评测 | [UCI Online Retail](https://archive.ics.uci.edu/ml/datasets/Online+Retail+II) |

## 下载方式

```powershell
# Bitext（Kaggle 需登录）
Invoke-WebRequest -Uri "https://www.kaggle.com/datasets/bitext/training-dataset-for-chatbots-response-generation" -OutFile Bitext.zip
# 解压后得到 Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv

# UCI Online Retail（xlsx 版在 Kaggle 镜像）
Invoke-WebRequest -Uri "https://archive.ics.uci.edu/ml/machine-learning-databases/00352/Online%20Retail.xlsx" -OutFile online-retail.xlsx
```

## 使用建议

- Bitext 可用 `qa` / `classification` 基准（intent 精确匹配）；
- online-retail 可构造"数据分析"类提示词，用 `generation` 基准 + 关键词/语义指标；
- 示例导入脚本参考 [sample-data/real-world/upload_real_world.py](../sample-data/real-world/upload_real_world.py) 的写法。
