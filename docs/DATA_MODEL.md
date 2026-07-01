# 資料模型 v0.1

## portfolio.csv

| 欄位 | 型態 | 說明 |
|---|---|---|
| symbol | string | 股票代號，例如 2330、00631L |
| name | string | 股票名稱 |
| market | string | TW=上市，TWO=上櫃 |
| shares | number | 持股股數 |
| avg_cost | number | 平均成本 |
| note | string | 備註 |

## alerts.csv

| 欄位 | 型態 | 說明 |
|---|---|---|
| symbol | string | 股票代號 |
| name | string | 股票名稱 |
| rule_type | string | price、ma20_cross_down、ma20_cross_up、rsi |
| operator | string | >=、>、<=、<、== |
| threshold | number | 門檻值 |
| enabled | boolean | 是否啟用 |
| last_triggered_at | string | 上次觸發時間 |
| note | string | 備註 |

## 未來資料表

### stock_master

- symbol
- name
- market
- industry
- listing_date
- capital

### price_daily

- symbol
- date
- open
- high
- low
- close
- volume

### fundamentals_monthly

- symbol
- month
- revenue
- revenue_mom
- revenue_yoy

### fundamentals_quarterly

- symbol
- quarter
- eps
- gross_margin
- operating_margin
- roe

### institutional_trading

- symbol
- date
- foreign_net_buy
- investment_trust_net_buy
- dealer_net_buy

### dividends

- symbol
- year
- cash_dividend
- stock_dividend
- ex_dividend_date
- yield_at_close

### news

- symbol
- published_at
- source
- title
- url
- ai_summary
- sentiment
