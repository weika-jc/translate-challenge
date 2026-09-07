const STATIC_MODE = typeof window.REPORT_DATA !== 'undefined';
const HIDDEN_MODEL_TABS = new Set([
  'gpt-5-6-luna-no-reasoning',
  'nova-pro',
  'deepseek-v3-2',
]);

const state = {
  data: null,
  activeModel: null,
  viewMode: 'single',
  page: 1,
  pageSize: 50,
  charts: {},
  compareSort: { key: 'avgScore', direction: 'desc' },
};

const CHART_COLORS = {
  accent: '#f0a030',
  good: '#3ecf8e',
  muted: '#8b95a8',
  grid: 'rgba(139, 149, 168, 0.15)',
  palette: ['#f0a030', '#3ecf8e', '#5b9cf5', '#c084fc', '#ef5f5f', '#38bdf8', '#f472b6'],
};

Chart.defaults.color = CHART_COLORS.muted;
Chart.defaults.borderColor = CHART_COLORS.grid;
Chart.defaults.font.family = "'DM Sans', sans-serif";

function scoreClass(v) {
  if (v == null) return '';
  if (v >= 80) return 'high';
  if (v >= 60) return 'mid';
  return 'low';
}

function fmt(v, suffix = '') {
  if (v == null) return '—';
  return `${v}${suffix}`;
}

function fmtMoney(v) {
  if (v == null || Number.isNaN(v)) return '—';
  const abs = Math.abs(v);
  const digits = abs >= 100 ? 2 : abs >= 10 ? 3 : 4;
  return `$${v.toFixed(digits)}`;
}

function fmtPct(v) {
  if (v == null || Number.isNaN(v)) return '—';
  return `${v}%`;
}

function fmtSigned(v) {
  if (v == null || Number.isNaN(v)) return '—';
  return `${v > 0 ? '+' : ''}${v}`;
}

function fmtMalformed(summary) {
  const n = summary.malformed_count;
  if (n == null) return '—';
  const ratio = summary.malformed_ratio;
  return ratio != null ? `${n} (${ratio}%)` : String(n);
}

function fmtCallFailed(summary) {
  const n = summary.call_failed_count;
  if (n == null) return '—';
  const ratio = summary.call_failure_ratio;
  return ratio != null ? `${n} (${ratio}%)` : String(n);
}

function fmtIssue(summary, countKey, ratioKey, checkedKey) {
  if (!summary[checkedKey]) return '—';
  const count = summary[countKey] ?? 0;
  const ratio = summary[ratioKey];
  return ratio != null ? `${count} (${ratio}%)` : String(count);
}

function fmtLanguage(summary) {
  if (!summary.language_checked_count) return '—';
  const invalid = fmtIssue(
    summary, 'language_invalid_count', 'language_invalid_ratio', 'language_checked_count',
  );
  return summary.language_unknown_count
    ? `${invalid} · 未判 ${summary.language_unknown_count}`
    : invalid;
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s ?? '';
  return d.innerHTML;
}

function truncate(s, n = 120) {
  if (!s) return '';
  return s.length > n ? s.slice(0, n) + '…' : s;
}

function latencySortKey(label) {
  if (label.startsWith('≥')) return parseInt(label.slice(1), 10);
  return parseInt(label.split('-')[0], 10);
}

async function loadData() {
  if (STATIC_MODE) {
    state.data = window.REPORT_DATA;
  } else {
    const res = await fetch('/api/data');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.data = await res.json();
  }
  if (!state.data.models.length) throw new Error('无数据');
  state.activeModel = state.data.models.find(m => !HIDDEN_MODEL_TABS.has(m.name))?.name
    ?? state.data.models[0].name;
  document.getElementById('loading').classList.add('hidden');
  document.getElementById('content').classList.remove('hidden');
  render();
}

function filterRecordsClient() {
  const dataset = document.getElementById('filter-dataset').value;
  const langPair = document.getElementById('filter-langpair').value;
  const minScore = document.getElementById('filter-min-score').value;
  const maxScore = document.getElementById('filter-max-score').value;
  const q = document.getElementById('filter-q').value.toLowerCase();

  const records = [];
  for (const m of state.data.models) {
    if (state.viewMode === 'single' && m.name !== state.activeModel) continue;
    for (const r of m.records) {
      const item = { ...r, model: m.name };
      if (dataset && item.dataset !== dataset) continue;
      if (langPair && item.lang_pair !== langPair) continue;
      if (minScore && (item.score == null || item.score < Number(minScore))) continue;
      if (maxScore && (item.score == null || item.score > Number(maxScore))) continue;
      if (q && !item.raw.toLowerCase().includes(q) && !item.trans.toLowerCase().includes(q) && !item.ref.toLowerCase().includes(q)) continue;
      records.push(item);
    }
  }
  const total = records.length;
  const start = (state.page - 1) * state.pageSize;
  return {
    total,
    page: state.page,
    page_size: state.pageSize,
    records: records.slice(start, start + state.pageSize),
  };
}

function getModelPrice(modelName) {
  const p = state.data?.pricing?.[modelName];
  return {
    input_per_million: Number(p?.input_per_million ?? 0) || 0,
    output_per_million: Number(p?.output_per_million ?? 0) || 0,
    billing_mode: p?.billing_mode ?? 'standard',
    cached_input_ratio: Number(p?.cached_input_ratio ?? 0.25) || 0.25,
    cache_write_input_ratio: Number(p?.cache_write_input_ratio ?? 1.25) || 1.25,
    cache_read_per_million: p?.cache_read_per_million == null
      ? null : Number(p.cache_read_per_million),
    cache_write_per_million: p?.cache_write_per_million == null
      ? null : Number(p.cache_write_per_million),
  };
}

function calcCost(
  inputTokens,
  outputTokens,
  totalTokens,
  pricing,
  cacheReadInputTokens = null,
  cacheWriteInputTokens = null,
) {
  const inp = inputTokens ?? 0;
  const out = outputTokens ?? 0;
  const pin = pricing.input_per_million ?? 0;
  const pout = pricing.output_per_million ?? 0;

  const cacheMetricsAvailable = cacheReadInputTokens != null || cacheWriteInputTokens != null;
  if (pricing.billing_mode === 'cached_prompt' && cacheMetricsAvailable) {
    const cacheRead = cacheReadInputTokens ?? 0;
    const cacheWrite = cacheWriteInputTokens ?? 0;
    const cacheReadRate = pricing.cache_read_per_million
      ?? pin * (pricing.cached_input_ratio ?? 0.25);
    const cacheWriteRate = pricing.cache_write_per_million
      ?? pin * (pricing.cache_write_input_ratio ?? 1.25);
    return (inp / 1_000_000) * pin
      + (cacheRead / 1_000_000) * cacheReadRate
      + (cacheWrite / 1_000_000) * cacheWriteRate
      + (out / 1_000_000) * pout;
  }

  if (pricing.billing_mode === 'cached_prompt' && totalTokens != null) {
    const total = totalTokens ?? 0;
    const cached = Math.max(0, total - inp - out);
    const cachedRate = pin * (pricing.cached_input_ratio ?? 0.25);
    return (inp / 1_000_000) * pin + (cached / 1_000_000) * cachedRate + (out / 1_000_000) * pout;
  }

  return (inp / 1_000_000) * pin + (out / 1_000_000) * pout;
}

function getActiveModels() {
  if (state.viewMode === 'all') return state.data.models;
  return state.data.models.filter(m => m.name === state.activeModel);
}

function renderTabs() {
  const el = document.getElementById('model-tabs');
  el.innerHTML = '';
  const tabModels = state.data.models.filter(m => !HIDDEN_MODEL_TABS.has(m.name));
  tabModels.forEach(m => {
    const btn = document.createElement('button');
    btn.className = 'model-tab' + (state.viewMode === 'single' && m.name === state.activeModel ? ' active' : '');
    btn.textContent = m.name;
    btn.onclick = () => {
      state.viewMode = 'single';
      state.activeModel = m.name;
      state.page = 1;
      render();
    };
    el.appendChild(btn);
  });
  if (tabModels.length > 1) {
    const allBtn = document.createElement('button');
    allBtn.className = 'model-tab' + (state.viewMode === 'all' ? ' active' : '');
    allBtn.textContent = '全部对比';
    allBtn.onclick = () => {
      state.viewMode = 'all';
      state.page = 1;
      render();
    };
    el.appendChild(allBtn);
  }
}

function aggregateSummary(models) {
  const allRecords = models.flatMap(m => m.records);
  const scores = allRecords.map(r => r.score).filter(v => v != null);
  const latencies = allRecords.map(r => r.latency_ms).filter(v => v != null);
  const tokens = allRecords.map(r => r.total_tokens).filter(v => v != null);
  const avg = arr => arr.length ? Math.round(arr.reduce((a, b) => a + b, 0) / arr.length * 100) / 100 : null;
  const median = arr => {
    if (!arr.length) return null;
    const s = [...arr].sort((a, b) => a - b);
    const mid = Math.floor(s.length / 2);
    return s.length % 2 ? s[mid] : Math.round((s[mid - 1] + s[mid]) / 2 * 100) / 100;
  };
  const retryTracked = models.reduce((n, m) => n + (m.summary.retry_tracked_count ?? 0), 0);
  const cacheTracked = models.reduce((n, m) => n + (m.summary.cache_tracked_count ?? 0), 0);
  const cacheHits = models.reduce((n, m) => n + (m.summary.cache_hit_count ?? 0), 0);
  const cacheWrites = models.reduce((n, m) => n + (m.summary.cache_write_count ?? 0), 0);
  const cacheReadTokens = models.reduce(
    (n, m) => n + (m.summary.cache_read_input_tokens_sum ?? 0), 0,
  );
  const cacheWriteTokens = models.reduce(
    (n, m) => n + (m.summary.cache_write_input_tokens_sum ?? 0), 0,
  );
  const firstCallSuccess = models.reduce((n, m) => n + (m.summary.first_call_success_count ?? 0), 0);
  const firstOutputValid = models.reduce((n, m) => n + (m.summary.first_output_valid_count ?? 0), 0);
  const totalRetries = models.reduce((n, m) => n + (m.summary.total_retries ?? 0), 0);
  return {
    count: allRecords.length,
    avg_score: avg(scores),
    median_score: median(scores),
    min_score: scores.length ? Math.min(...scores) : null,
    max_score: scores.length ? Math.max(...scores) : null,
    std_score: null,
    avg_latency_ms: avg(latencies),
    avg_total_tokens: avg(tokens),
    total_tokens_sum: tokens.length ? tokens.reduce((a, b) => a + b, 0) : null,
    cache_tracked_count: cacheTracked,
    cache_hit_count: cacheHits,
    cache_write_count: cacheWrites,
    cache_hit_ratio: cacheTracked
      ? Math.round(cacheHits / cacheTracked * 10000) / 100 : null,
    avg_cache_read_input_tokens: cacheTracked
      ? Math.round(cacheReadTokens / cacheTracked * 100) / 100 : null,
    avg_cache_write_input_tokens: cacheTracked
      ? Math.round(cacheWriteTokens / cacheTracked * 100) / 100 : null,
    cache_read_input_tokens_sum: cacheTracked ? cacheReadTokens : null,
    cache_write_input_tokens_sum: cacheTracked ? cacheWriteTokens : null,
    malformed_count: models.reduce((n, m) => n + (m.summary.malformed_count ?? 0), 0),
    valid_count: models.reduce((n, m) => n + (m.summary.valid_count ?? 0), 0),
    malformed_ratio: (() => {
      const total = models.reduce((n, m) => n + (m.summary.call_success_count ?? 0), 0);
      const bad = models.reduce((n, m) => n + (m.summary.malformed_count ?? 0), 0);
      return total ? Math.round(bad / total * 10000) / 100 : null;
    })(),
    call_failed_count: models.reduce((n, m) => n + (m.summary.call_failed_count ?? 0), 0),
    call_failure_ratio: (() => {
      const total = models.reduce((n, m) => n + (m.summary.count ?? 0), 0);
      const bad = models.reduce((n, m) => n + (m.summary.call_failed_count ?? 0), 0);
      return total ? Math.round(bad / total * 10000) / 100 : null;
    })(),
    retry_tracked_count: retryTracked,
    first_call_success_count: firstCallSuccess,
    first_call_success_ratio: retryTracked
      ? Math.round(firstCallSuccess / retryTracked * 10000) / 100 : null,
    first_output_valid_count: firstOutputValid,
    first_output_valid_ratio: retryTracked
      ? Math.round(firstOutputValid / retryTracked * 10000) / 100 : null,
    first_request_success_count: firstOutputValid,
    first_request_success_ratio: retryTracked
      ? Math.round(firstOutputValid / retryTracked * 10000) / 100 : null,
    total_retries: totalRetries,
    avg_retries: retryTracked
      ? Math.round(totalRetries / retryTracked * 100) / 100 : null,
    retried_count: models.reduce((n, m) => n + (m.summary.retried_count ?? 0), 0),
    recovered_by_retry_count: models.reduce(
      (n, m) => n + (m.summary.recovered_by_retry_count ?? 0), 0,
    ),
    language_invalid_count: models.reduce((n, m) => n + (m.summary.language_invalid_count ?? 0), 0),
    language_unknown_count: models.reduce((n, m) => n + (m.summary.language_unknown_count ?? 0), 0),
    language_checked_count: models.reduce((n, m) => n + (m.summary.language_checked_count ?? 0), 0),
    language_invalid_ratio: (() => {
      const total = models.reduce((n, m) => n + (m.summary.language_checked_count ?? 0), 0);
      const bad = models.reduce((n, m) => n + (m.summary.language_invalid_count ?? 0), 0);
      return total ? Math.round(bad / total * 10000) / 100 : null;
    })(),
    policy_failed_count: models.reduce((n, m) => n + (m.summary.policy_failed_count ?? 0), 0),
    policy_checked_count: models.reduce((n, m) => n + (m.summary.policy_checked_count ?? 0), 0),
    policy_failure_ratio: (() => {
      const total = models.reduce((n, m) => n + (m.summary.policy_checked_count ?? 0), 0);
      const bad = models.reduce((n, m) => n + (m.summary.policy_failed_count ?? 0), 0);
      return total ? Math.round(bad / total * 10000) / 100 : null;
    })(),
    judge_failed_count: models.reduce((n, m) => n + (m.summary.judge_failed_count ?? 0), 0),
    judge_attempted_count: models.reduce((n, m) => n + (m.summary.judge_attempted_count ?? 0), 0),
    judge_failure_ratio: (() => {
      const total = models.reduce((n, m) => n + (m.summary.judge_attempted_count ?? 0), 0);
      const bad = models.reduce((n, m) => n + (m.summary.judge_failed_count ?? 0), 0);
      return total ? Math.round(bad / total * 10000) / 100 : null;
    })(),
  };
}

function renderOverview() {
  const models = getActiveModels();
  const s = state.viewMode === 'single'
    ? models[0].summary
    : aggregateSummary(models);

  const subtitle = state.viewMode === 'single'
    ? `${models[0].name} · ${s.count} 条记录`
    : `${models.length} 个模型 · ${s.count} 条记录`;

  document.getElementById('subtitle').textContent = subtitle;

  const cards = [
    { label: '平均评分', value: fmt(s.avg_score), cls: `score-${scoreClass(s.avg_score)}` },
    { label: '中位评分', value: fmt(s.median_score), cls: `score-${scoreClass(s.median_score)}` },
    { label: '标准差', value: fmt(s.std_score) },
    { label: '最低 / 最高', value: `${fmt(s.min_score)} / ${fmt(s.max_score)}` },
    { label: '平均延迟', value: fmt(s.avg_latency_ms, ' ms') },
    { label: '平均 Token', value: fmt(s.avg_total_tokens) },
    { label: '总 Token', value: fmt(s.total_tokens_sum) },
    { label: '样本数', value: fmt(s.count) },
    { label: 'Malformed', value: fmtMalformed(s) },
    { label: '调用失败', value: fmtCallFailed(s) },
    { label: '语言错误', value: fmtLanguage(s) },
    { label: '规则失败', value: fmtIssue(s, 'policy_failed_count', 'policy_failure_ratio', 'policy_checked_count') },
    { label: 'Judge 失败', value: fmtIssue(s, 'judge_failed_count', 'judge_failure_ratio', 'judge_attempted_count') },
  ];

  if (s.retry_tracked_count) {
    cards.push(
      { label: '首次请求成功率', value: fmtPct(s.first_request_success_ratio) },
      { label: '首次调用返回率', value: fmtPct(s.first_call_success_ratio) },
      { label: '重试恢复', value: fmt(s.recovered_by_retry_count) },
      { label: '平均重试', value: fmt(s.avg_retries) },
    );
  }

  if (s.cache_tracked_count) {
    cards.push(
      { label: '缓存命中率', value: fmtPct(s.cache_hit_ratio) },
      { label: '缓存读取 Token', value: fmt(s.cache_read_input_tokens_sum) },
      { label: '缓存写入 Token', value: fmt(s.cache_write_input_tokens_sum) },
    );
  }

  document.getElementById('overview-cards').innerHTML = cards.map(c => `
    <div class="card">
      <div class="label">${c.label}</div>
      <div class="value ${c.cls || ''}">${c.value}</div>
    </div>
  `).join('');
}

function renderReliability() {
  const section = document.getElementById('reliability-section');
  const models = getActiveModels();
  const rows = [];
  models.forEach(model => {
    const s = model.summary;
    if (s.retry_tracked_count) {
      rows.push({
        model: model.name,
        stage: '翻译',
        tracked: s.retry_tracked_count,
        firstRequest: s.first_request_success_ratio,
        firstCall: s.first_call_success_ratio,
        retried: s.retried_count,
        recovered: s.recovered_by_retry_count,
        unavailable: (s.call_failed_count ?? 0) + (s.malformed_count ?? 0),
        avgRetries: s.avg_retries,
      });
    }
    if (s.judge_retry_tracked_count) {
      rows.push({
        model: model.name,
        stage: 'Judge',
        tracked: s.judge_retry_tracked_count,
        firstRequest: s.judge_first_request_success_ratio,
        firstCall: s.judge_first_call_success_ratio,
        retried: s.judge_retried_count,
        recovered: s.judge_recovered_by_retry_count,
        unavailable: s.judge_failed_count,
        avgRetries: s.judge_retry_tracked_count
          ? Math.round(s.judge_total_retries / s.judge_retry_tracked_count * 100) / 100
          : null,
      });
    }
  });
  if (!rows.length) {
    section.classList.add('hidden');
    return;
  }
  section.classList.remove('hidden');
  document.querySelector('#reliability-table tbody').innerHTML = rows.map(row => `
    <tr>
      <td><strong>${esc(row.model)}</strong></td>
      <td><span class="badge reliability-stage">${row.stage}</span></td>
      <td class="num">${row.tracked}</td>
      <td class="num"><span class="reliability-value">${fmtPct(row.firstRequest)}</span></td>
      <td class="num"><span class="reliability-value">${fmtPct(row.firstCall)}</span></td>
      <td class="num">${row.retried}</td>
      <td class="num recovered">${row.recovered}</td>
      <td class="num ${row.unavailable ? 'unavailable' : ''}">${row.unavailable}</td>
      <td class="num">${fmt(row.avgRetries)}</td>
    </tr>
  `).join('');
}

function renderCompare() {
  const section = document.getElementById('compare-section');
  if (state.data.models.length < 2) {
    section.classList.add('hidden');
    return;
  }
  section.classList.remove('hidden');
  const tbody = document.querySelector('#compare-table tbody');
  const rows = state.data.models.map(m => {
    const s = m.summary;
    const p = getModelPrice(m.name);
    const totalCost = calcCost(
      s.input_tokens_sum,
      s.output_tokens_sum,
      s.total_tokens_sum,
      p,
      s.cache_read_input_tokens_sum,
      s.cache_write_input_tokens_sum,
    );
    return {
      model: m,
      totalCost,
      sortValues: {
        name: m.name,
        count: s.count,
        avgScore: s.avg_score,
        medianScore: s.median_score,
        scoreRange: s.min_score,
        avgLatency: s.avg_latency_ms,
        p95Latency: s.p95_latency_ms,
        cacheHit: s.cache_hit_ratio,
        lowScore: s.low_score_ratio,
        malformed: s.malformed_count,
        callFailed: s.call_failed_count,
        languageFailed: s.language_invalid_count,
        policyFailed: s.policy_failed_count,
        judgeFailed: s.judge_failed_count,
        totalCost,
      },
    };
  });
  const { key, direction } = state.compareSort;
  const sorted = rows.sort((left, right) => {
    const a = left.sortValues[key];
    const b = right.sortValues[key];
    if (a == null && b == null) return left.model.name.localeCompare(right.model.name);
    if (a == null) return 1;
    if (b == null) return -1;
    const comparison = typeof a === 'string'
      ? a.localeCompare(b)
      : a - b;
    if (comparison) return direction === 'asc' ? comparison : -comparison;
    return left.model.name.localeCompare(right.model.name);
  });
  updateCompareSortHeaders();
  tbody.innerHTML = sorted.map(({ model: m, totalCost }) => {
    const s = m.summary;
    return `<tr>
        <td><strong>${esc(m.name)}</strong></td>
        <td class="num">${s.count}</td>
        <td class="num"><span class="score-pill ${scoreClass(s.avg_score)}">${fmt(s.avg_score)}</span></td>
        <td class="num">${fmt(s.median_score)}</td>
        <td class="num">${fmt(s.min_score)} / ${fmt(s.max_score)}</td>
        <td class="num">${fmt(s.avg_latency_ms, ' ms')}</td>
        <td class="num">${fmt(s.p95_latency_ms, ' ms')}</td>
        <td class="num">${fmtPct(s.cache_hit_ratio)}</td>
        <td class="num">${fmtPct(s.low_score_ratio)}</td>
        <td class="num">${fmtMalformed(s)}</td>
        <td class="num">${fmtCallFailed(s)}</td>
        <td class="num">${fmtLanguage(s)}</td>
        <td class="num">${fmtIssue(s, 'policy_failed_count', 'policy_failure_ratio', 'policy_checked_count')}</td>
        <td class="num">${fmtIssue(s, 'judge_failed_count', 'judge_failure_ratio', 'judge_attempted_count')}</td>
        <td class="num">${fmtMoney(totalCost)}</td>
      </tr>`;
  }).join('');
}

function updateCompareSortHeaders() {
  document.querySelectorAll('#compare-table th[data-sort-key]').forEach(header => {
    const active = header.dataset.sortKey === state.compareSort.key;
    header.setAttribute(
      'aria-sort',
      active ? (state.compareSort.direction === 'asc' ? 'ascending' : 'descending') : 'none',
    );
    const indicator = header.querySelector('.sort-indicator');
    if (indicator) indicator.textContent = active
      ? (state.compareSort.direction === 'asc' ? '↑' : '↓')
      : '↕';
  });
}

function bindCompareSorting() {
  document.querySelectorAll('#compare-table th[data-sort-key] .sort-button').forEach(button => {
    button.addEventListener('click', () => {
      const key = button.closest('th').dataset.sortKey;
      if (state.compareSort.key === key) {
        state.compareSort.direction = state.compareSort.direction === 'asc' ? 'desc' : 'asc';
      } else {
        state.compareSort = {
          key,
          direction: key === 'name' ? 'asc' : 'desc',
        };
      }
      renderCompare();
    });
  });
}

function pairKey(pair) {
  return `${pair.model_a}|||${pair.model_b}`;
}

function orientPair(pair, rowModel, columnModel) {
  const rowIsA = pair.model_a === rowModel;
  const reverse = value => value == null ? null : -value;
  return {
    rowModel,
    columnModel,
    rowWins: rowIsA ? pair.model_a_wins : pair.model_b_wins,
    columnWins: rowIsA ? pair.model_b_wins : pair.model_a_wins,
    ties: pair.ties,
    rowAvg: rowIsA ? pair.model_a_avg_score : pair.model_b_avg_score,
    columnAvg: rowIsA ? pair.model_b_avg_score : pair.model_a_avg_score,
    meanDelta: rowIsA ? pair.mean_score_delta : reverse(pair.mean_score_delta),
    medianDelta: rowIsA ? pair.median_score_delta : reverse(pair.median_score_delta),
    ciLow: rowIsA ? pair.ci95_low : reverse(pair.ci95_high),
    ciHigh: rowIsA ? pair.ci95_high : reverse(pair.ci95_low),
    result: pair.winner === rowModel ? 'win' : pair.winner === columnModel ? 'loss' : 'uncertain',
    commonCount: pair.common_count,
    pairedCount: pair.score_paired_count,
    coverage: pair.score_coverage,
    unscoredCount: pair.unscored_common_count,
    rowOnlyCount: rowIsA ? pair.model_a_only_count : pair.model_b_only_count,
    columnOnlyCount: rowIsA ? pair.model_b_only_count : pair.model_a_only_count,
  };
}

function pairResultText(result) {
  if (result === 'win') return '纵轴模型显著更优';
  if (result === 'loss') return '纵轴模型显著更差';
  return '差异不明确';
}

function pairAriaLabel(pair) {
  return `${pair.rowModel} 相对 ${pair.columnModel}：${pairResultText(pair.result)}，平均分差 ${fmtSigned(pair.meanDelta)}，95% 置信区间 ${fmtSigned(pair.ciLow)} 到 ${fmtSigned(pair.ciHigh)}`;
}

function pairTooltipMarkup(pair) {
  return `
    <div class="tooltip-kicker">纵轴相对横轴</div>
    <div class="tooltip-models">
      <strong>${esc(pair.rowModel)}</strong><span>vs</span><strong>${esc(pair.columnModel)}</strong>
    </div>
    <div class="tooltip-verdict ${pair.result}">
      <i class="legend-dot ${pair.result}"></i>${pairResultText(pair.result)}
    </div>
    <div class="tooltip-metrics">
      <div><span>平均分差</span><strong>${fmtSigned(pair.meanDelta)}</strong></div>
      <div><span>中位数差</span><strong>${fmtSigned(pair.medianDelta)}</strong></div>
      <div><span>95% CI</span><strong>[${fmtSigned(pair.ciLow)}, ${fmtSigned(pair.ciHigh)}]</strong></div>
      <div><span>配对覆盖</span><strong>${pair.pairedCount} / ${pair.commonCount}</strong></div>
    </div>
    <div class="tooltip-scoreline">
      <span><b>${pair.rowWins}</b> 纵轴胜</span>
      <span><b>${pair.ties}</b> 平</span>
      <span><b>${pair.columnWins}</b> 横轴胜</span>
    </div>
    <div class="tooltip-foot">
      配对均分 ${fmt(pair.rowAvg)} / ${fmt(pair.columnAvg)} · 覆盖率 ${fmtPct(pair.coverage)}
      ${pair.unscoredCount ? ` · 未评分 ${pair.unscoredCount}` : ''}
      ${pair.rowOnlyCount || pair.columnOnlyCount ? ` · 独有样本 ${pair.rowOnlyCount} / ${pair.columnOnlyCount}` : ''}
    </div>`;
}

function positionPairTooltip(target) {
  const tooltip = document.getElementById('pair-tooltip');
  const targetRect = target.getBoundingClientRect();
  const tooltipRect = tooltip.getBoundingClientRect();
  const gap = 12;
  let left = targetRect.right + gap;
  if (left + tooltipRect.width > window.innerWidth - gap) {
    left = targetRect.left - tooltipRect.width - gap;
  }
  left = Math.max(gap, Math.min(left, window.innerWidth - tooltipRect.width - gap));
  let top = targetRect.top + targetRect.height / 2 - tooltipRect.height / 2;
  top = Math.max(gap, Math.min(top, window.innerHeight - tooltipRect.height - gap));
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

function showPairTooltip(target, pair) {
  const tooltip = document.getElementById('pair-tooltip');
  tooltip.innerHTML = pairTooltipMarkup(pair);
  tooltip.classList.remove('hidden');
  positionPairTooltip(target);
}

function hidePairTooltip() {
  document.getElementById('pair-tooltip').classList.add('hidden');
}

function pairWinner(pair) {
  if (pair.winner === pair.model_a || pair.winner === 'a') return pair.model_a;
  if (pair.winner === pair.model_b || pair.winner === 'b') return pair.model_b;
  return null;
}

function rankPairwiseModels(models, pairs) {
  const overallScores = new Map(
    state.data.models.map(model => [model.name, model.summary.avg_score]),
  );
  const ranks = new Map(models.map(model => [model, {
    wins: 0,
    losses: 0,
    deltaSum: 0,
    deltaCount: 0,
  }]));
  pairs.forEach(pair => {
    const left = ranks.get(pair.model_a);
    const right = ranks.get(pair.model_b);
    if (!left || !right) return;
    const winner = pairWinner(pair);
    if (winner === pair.model_a) {
      left.wins += 1;
      right.losses += 1;
    } else if (winner === pair.model_b) {
      right.wins += 1;
      left.losses += 1;
    }
    if (pair.mean_score_delta != null) {
      left.deltaSum += pair.mean_score_delta;
      right.deltaSum -= pair.mean_score_delta;
      left.deltaCount += 1;
      right.deltaCount += 1;
    }
  });
  return [...models].sort((a, b) => {
    const left = ranks.get(a);
    const right = ranks.get(b);
    const leftOutcome = left.wins - left.losses;
    const rightOutcome = right.wins - right.losses;
    if (leftOutcome !== rightOutcome) return leftOutcome - rightOutcome;
    const leftDelta = left.deltaCount ? left.deltaSum / left.deltaCount : -Infinity;
    const rightDelta = right.deltaCount ? right.deltaSum / right.deltaCount : -Infinity;
    if (leftDelta !== rightDelta) return leftDelta - rightDelta;
    const leftScore = overallScores.get(a) ?? -Infinity;
    const rightScore = overallScores.get(b) ?? -Infinity;
    if (leftScore !== rightScore) return leftScore - rightScore;
    return a.localeCompare(b);
  });
}

function renderPairwise() {
  const section = document.getElementById('pairwise-section');
  const comparison = state.data.comparisons;
  const pairs = comparison?.pairs || [];
  if (!pairs.length) {
    section.classList.add('hidden');
    return;
  }
  section.classList.remove('hidden');

  const method = comparison.methodology;
  document.getElementById('pairwise-method').textContent =
    `只比较共同且都有评分的样本；精确同分记平局。置信区间使用 ${method.bootstrap_iterations} 次固定种子的配对 bootstrap。矩阵按显著胜场减负场排序，纵轴越靠下整体表现越优。`;

  const models = rankPairwiseModels(
    state.data.models.map(model => model.name),
    pairs,
  );
  const pairMap = new Map();
  pairs.forEach(pair => {
    pairMap.set(`${pair.model_a}|||${pair.model_b}`, pair);
    pairMap.set(`${pair.model_b}|||${pair.model_a}`, pair);
  });

  const matrix = document.getElementById('pairwise-matrix');
  matrix.innerHTML = `
    <thead><tr>
      <th class="matrix-corner" scope="col"><span>纵轴 ↓</span><span>横轴 →</span></th>
      ${models.map(model => `<th class="matrix-column-label" scope="col"><span>${esc(model)}</span></th>`).join('')}
    </tr></thead>
    <tbody>${models.map((rowModel, rowIndex) => `<tr>
      <th class="matrix-row-label" scope="row">${esc(rowModel)}</th>
      ${models.map((columnModel, columnIndex) => {
        if (rowModel === columnModel) {
          return '<td class="matrix-data diagonal" aria-label="同一模型，无需比较"><span>—</span></td>';
        }
        const rawPair = pairMap.get(`${rowModel}|||${columnModel}`);
        if (!rawPair) {
          return '<td class="matrix-data unavailable" aria-label="无配对数据"><span>·</span></td>';
        }
        const oriented = orientPair(rawPair, rowModel, columnModel);
        return `<td class="matrix-data" data-row-index="${rowIndex}" data-column-index="${columnIndex}">
          <button class="matrix-cell ${oriented.result}" type="button"
            data-pair-key="${esc(pairKey(rawPair))}"
            data-row-model="${esc(rowModel)}"
            data-column-model="${esc(columnModel)}"
            aria-label="${esc(pairAriaLabel(oriented))}">
            <span class="matrix-dot" aria-hidden="true"></span>
          </button>
        </td>`;
      }).join('')}
    </tr>`).join('')}</tbody>`;

  matrix.querySelectorAll('.matrix-cell').forEach(cell => {
    const rawPair = pairs.find(pair => pairKey(pair) === cell.dataset.pairKey);
    const oriented = orientPair(rawPair, cell.dataset.rowModel, cell.dataset.columnModel);
    cell.addEventListener('mouseenter', () => showPairTooltip(cell, oriented));
    cell.addEventListener('focus', () => showPairTooltip(cell, oriented));
    cell.addEventListener('mouseleave', hidePairTooltip);
    cell.addEventListener('blur', hidePairTooltip);
  });
}

function destroyChart(id) {
  if (state.charts[id]) {
    state.charts[id].destroy();
    delete state.charts[id];
  }
}

function renderCharts() {
  const models = getActiveModels();
  const isMulti = models.length > 1;

  destroyChart('distribution');
  const distLabels = Object.keys(models[0].summary.score_distribution);
  const distDatasets = models.map((m, i) => ({
    label: m.name,
    data: distLabels.map(k => m.summary.score_distribution[k] ?? 0),
    backgroundColor: CHART_COLORS.palette[i % CHART_COLORS.palette.length] + '99',
    borderColor: CHART_COLORS.palette[i % CHART_COLORS.palette.length],
    borderWidth: 1,
  }));
  state.charts.distribution = new Chart(document.getElementById('chart-distribution'), {
    type: 'bar',
    data: { labels: distLabels, datasets: distDatasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: isMulti } },
      scales: {
        y: { beginAtZero: true, grid: { color: CHART_COLORS.grid } },
        x: { grid: { display: false }, ticks: { maxRotation: 90, minRotation: 45, font: { size: 10 } } },
      },
    },
  });

  destroyChart('dataset');
  const datasets = [...new Set(models.flatMap(m => m.summary.by_dataset.map(d => d.name)))];
  const dsData = models.map((m, i) => ({
    label: m.name,
    data: datasets.map(name => {
      const found = m.summary.by_dataset.find(d => d.name === name);
      return found ? found.avg_score : null;
    }),
    backgroundColor: CHART_COLORS.palette[i % CHART_COLORS.palette.length] + 'cc',
    borderRadius: 4,
  }));
  state.charts.dataset = new Chart(document.getElementById('chart-dataset'), {
    type: 'bar',
    data: { labels: datasets, datasets: dsData },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: isMulti } },
      scales: {
        y: { min: 0, max: 100, grid: { color: CHART_COLORS.grid } },
        x: { grid: { display: false } },
      },
    },
  });

  destroyChart('langpair');
  const pairMap = {};
  models.forEach(m => {
    m.summary.by_lang_pair.forEach(p => {
      if (!pairMap[p.name]) pairMap[p.name] = { total: 0, sum: 0 };
      pairMap[p.name].total += p.count;
      pairMap[p.name].sum += (p.avg_score || 0) * p.count;
    });
  });
  const topPairs = Object.entries(pairMap)
    .map(([name, v]) => ({ name, avg: Math.round(v.sum / v.total * 100) / 100, count: v.total }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 15);

  state.charts.langpair = new Chart(document.getElementById('chart-langpair'), {
    type: 'bar',
    data: {
      labels: topPairs.map(p => p.name),
      datasets: [{
        label: '平均分',
        data: topPairs.map(p => p.avg),
        backgroundColor: CHART_COLORS.accent + 'cc',
        borderRadius: 4,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { min: 0, max: 100, grid: { color: CHART_COLORS.grid } },
        y: { grid: { display: false } },
      },
    },
  });

  destroyChart('latency');
  const latencyLabels = [...new Set(models.flatMap(m => Object.keys(m.summary.latency_distribution || {})))];
  latencyLabels.sort((a, b) => latencySortKey(a) - latencySortKey(b));
  const latencyData = models.map((m, i) => ({
    label: m.name,
    data: latencyLabels.map(k => m.summary.latency_distribution?.[k] ?? 0),
    backgroundColor: CHART_COLORS.palette[i % CHART_COLORS.palette.length] + '99',
    borderColor: CHART_COLORS.palette[i % CHART_COLORS.palette.length],
    borderWidth: 1,
  }));
  state.charts.latency = new Chart(document.getElementById('chart-latency'), {
    type: 'bar',
    data: { labels: latencyLabels, datasets: latencyData },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: isMulti } },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: '样本数' },
          grid: { color: CHART_COLORS.grid },
        },
        x: {
          title: { display: true, text: '延迟 (ms)' },
          grid: { display: false },
          ticks: { maxRotation: 45, minRotation: 45, font: { size: 10 } },
        },
      },
    },
  });
}

function populateFilters() {
  const model = state.viewMode === 'single' ? state.activeModel : null;
  const records = model
    ? state.data.models.find(m => m.name === model).records
    : state.data.models.flatMap(m => m.records);

  const datasets = [...new Set(records.map(r => r.dataset))].sort();
  const pairs = [...new Set(records.map(r => r.lang_pair))].sort();

  const dsEl = document.getElementById('filter-dataset');
  const lpEl = document.getElementById('filter-langpair');
  const curDs = dsEl.value;
  const curLp = lpEl.value;

  dsEl.innerHTML = '<option value="">全部</option>' +
    datasets.map(d => `<option value="${esc(d)}"${d === curDs ? ' selected' : ''}>${esc(d)}</option>`).join('');
  lpEl.innerHTML = '<option value="">全部</option>' +
    pairs.map(p => `<option value="${esc(p)}"${p === curLp ? ' selected' : ''}>${esc(p)}</option>`).join('');
}

async function loadRecords() {
  const data = STATIC_MODE
    ? filterRecordsClient()
    : await (async () => {
        const params = new URLSearchParams({
          page: state.page,
          page_size: state.pageSize,
        });
        if (state.viewMode === 'single') params.set('model', state.activeModel);

        const dataset = document.getElementById('filter-dataset').value;
        const langPair = document.getElementById('filter-langpair').value;
        const minScore = document.getElementById('filter-min-score').value;
        const maxScore = document.getElementById('filter-max-score').value;
        const q = document.getElementById('filter-q').value;

        if (dataset) params.set('dataset', dataset);
        if (langPair) params.set('lang_pair', langPair);
        if (minScore) params.set('min_score', minScore);
        if (maxScore) params.set('max_score', maxScore);
        if (q) params.set('q', q);

        const res = await fetch(`/api/records?${params}`);
        return res.json();
      })();
  renderRecords(data);
}

function renderRecords(data) {
  const statusText = r => {
    if (r.call_success === false) return '调用失败';
    if (r.trans_valid === false) return '格式错误';
    if (r.judge_success == null && r.policy_pass == null && r.language_valid == null) return '旧协议';
    const issues = [];
    if (r.language_valid === false) issues.push('语言错误');
    if (r.language_valid == null) issues.push('语言未判');
    if (r.policy_pass === false) issues.push('规则失败');
    if (r.policy_warnings?.length) issues.push('规则提醒');
    if (r.judge_success === false) issues.push('Judge 失败');
    if (r.judge_success === true && r.judge_acceptable === false) issues.push('Judge 不接受');
    return issues.length ? issues.join(' / ') : '通过';
  };
  const attemptText = r => {
    if (r.call_attempts == null) return '—';
    if (r.recovered_by_retry === true) return `${r.call_attempts} 次 · 恢复`;
    return `${r.call_attempts} 次`;
  };
  const attemptTitle = r => {
    if (r.call_attempts == null) return '旧结果未记录尝试次数';
    const firstCall = r.first_call_success === true ? '已返回' : '未返回';
    const firstOutput = r.first_output_valid === true ? '可用' : '不可用';
    return `首次调用${firstCall}；首次结果${firstOutput}；重试 ${r.call_retries ?? 0} 次`;
  };
  const tokenTitle = r => {
    if (r.cache_read_input_tokens == null && r.cache_write_input_tokens == null) {
      return `输入 ${r.input_tokens ?? '—'}；输出 ${r.output_tokens ?? '—'}`;
    }
    return `未缓存输入 ${r.input_tokens ?? 0}；缓存读 ${r.cache_read_input_tokens ?? 0}；缓存写 ${r.cache_write_input_tokens ?? 0}；输出 ${r.output_tokens ?? 0}`;
  };
  const tbody = document.getElementById('records-body');
  tbody.innerHTML = data.records.map(r => `
    <tr>
      <td><span class="badge dataset">${esc(r.dataset)}</span></td>
      <td><span class="badge lang">${esc(r.lang_pair)}</span></td>
      <td class="text-cell" title="${esc(r.raw)}">${esc(truncate(r.raw))}</td>
      <td class="text-cell" title="${esc(r.ref)}">${esc(truncate(r.ref))}</td>
      <td class="text-cell" title="${esc(r.trans)}">${esc(truncate(r.trans))}</td>
      <td><span class="score-pill ${scoreClass(r.score)}">${fmt(r.score)}</span></td>
      <td><span class="badge status">${esc(statusText(r))}</span></td>
      <td title="${esc(attemptTitle(r))}"><span class="badge attempts${r.recovered_by_retry === true ? ' recovered' : ''}">${esc(attemptText(r))}</span></td>
      <td>${fmt(r.latency_ms, ' ms')}</td>
      <td title="${esc(tokenTitle(r))}">${fmt(r.total_tokens)}</td>
      <td>${fmtMoney(calcCost(
        r.input_tokens,
        r.output_tokens,
        r.total_tokens,
        getModelPrice(r.model),
        r.cache_read_input_tokens,
        r.cache_write_input_tokens,
      ))}</td>
    </tr>
  `).join('') || '<tr><td colspan="11" style="text-align:center;color:var(--muted)">无匹配记录</td></tr>';

  const totalPages = Math.max(1, Math.ceil(data.total / data.page_size));
  document.getElementById('page-info').textContent =
    `第 ${data.page} / ${totalPages} 页，共 ${data.total} 条`;
  document.getElementById('prev-page').disabled = data.page <= 1;
  document.getElementById('next-page').disabled = data.page >= totalPages;
}

function bindFilters() {
  let debounce;
  const onFilter = () => {
    state.page = 1;
    loadRecords();
  };
  ['filter-dataset', 'filter-langpair', 'filter-min-score', 'filter-max-score'].forEach(id => {
    document.getElementById(id).addEventListener('change', onFilter);
  });
  document.getElementById('filter-q').addEventListener('input', () => {
    clearTimeout(debounce);
    debounce = setTimeout(onFilter, 300);
  });
  document.getElementById('prev-page').addEventListener('click', () => {
    if (state.page > 1) { state.page--; loadRecords(); }
  });
  document.getElementById('next-page').addEventListener('click', () => {
    state.page++; loadRecords();
  });
}

function render() {
  renderTabs();
  renderOverview();
  renderReliability();
  renderCompare();
  renderPairwise();
  renderCharts();
  populateFilters();
  loadRecords();
}

loadData().catch(err => {
  document.getElementById('loading').textContent = '加载失败: ' + err.message;
});
bindFilters();
bindCompareSorting();
