export const COLUMN_LABELS = {
  USDAMOUNT: '折美元金额（万美元）',
  TRADEDATE: '交易日期',
  TRADESTATUS: '状态',
  SPECIALSTATE: '特殊状态',
  APPID: '产品类型',
  BUYORSELL: '买卖方向',
  BANKID: '机构ID',
  DIPNAME: '机构名称',
  CUSTNAME: '客户名称',
  TOTAL_AMOUNT: '交易量（万美元）',
  TRADE_COUNT: '总笔数',
  HEDGE_RATIO: '套保率',
  DERIVATIVE_AMOUNT: '衍生品交易量（万美元）',
  DERIVATIVE_COUNT: '衍生品笔数',
  同比_CHANGE: '同比变化',
  环比_CHANGE: '环比变化',
}

export const COMPARISON_COLS = new Set(['同比_CHANGE', '环比_CHANGE'])

export const AMOUNT_COLS = new Set(['USDAMOUNT', 'TOTAL_AMOUNT', 'DERIVATIVE_AMOUNT'])

export function formatCellValue(colName, rawValue) {
  if (rawValue == null || rawValue === '') {
    if (colName === 'DIPNAME') return '(未识别)'
    if (AMOUNT_COLS.has(colName)) return '0.00'
    if (colName === 'TRADE_COUNT') return '0'
    return ''
  }
  let display = String(rawValue)
  if (AMOUNT_COLS.has(colName)) {
    const num = Number(rawValue)
    if (!isNaN(num)) {
      display = (num / 10000).toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })
    }
  } else if (colName === 'HEDGE_RATIO') {
    const num = Number(rawValue)
    if (!isNaN(num)) {
      display = num.toFixed(2) + '%'
    }
  } else if (COMPARISON_COLS.has(colName)) {
    const num = Number(rawValue)
    if (!isNaN(num)) {
      const sign = num >= 0 ? '+' : ''
      display = sign + num.toFixed(1) + '%'
    }
  }
  return display
}

export const PRODUCT_TYPE_OPTIONS = [
  { value: 'all', label: '所有交易' },
  { value: 'spot', label: '即期外汇' },
  { value: 'fwd', label: '远期外汇' },
  { value: 'swap', label: '外汇掉期' },
]

export const BUY_SELL_OPTIONS = [
  { value: '', label: '不限' },
  { value: 'B', label: '买入(B)' },
  { value: 'S', label: '卖出(S)' },
]

export const APP_ID_OPTIONS = [
  { value: null, label: '不限' },
  { value: 1, label: '外汇(1)' },
  { value: 2, label: '结售汇(2)' },
]

export const SPECIAL_STATES = [
  { value: '0', label: '正常交易' },
  { value: '1,2,6,7,10,11,15,17', label: '平仓' },
  { value: '4,16', label: '提前交割' },
  { value: '3,5,12,13', label: '展期' },
]

export const DIMENSION_OPTIONS = [
  { value: 'bank', label: '机构名称' },
  { value: 'customer', label: '客户名称' },
  { value: 'customer_id', label: '客户号' },
  { value: 'manager', label: '客户经理ID' },
  { value: 'manager_name', label: '客户经理名称' },
]

export const LIFECYCLE_STATUS_OPTIONS = [
  { value: '', label: '不限' },
  { value: 'not_due', label: '未到期' },
  { value: 'overdue', label: '逾期' },
  { value: 'due_today', label: '已到期' },
  { value: 'unclosed', label: '未完结' },
  { value: 'closed', label: '已完结' },
]

export function lifecycleStatusLabel(v) {
  const map = {
    not_due: '未到期',
    overdue: '逾期',
    due_today: '已到期',
    unclosed: '未完结',
    closed: '已完结',
  }
  return map[v] || ''
}
