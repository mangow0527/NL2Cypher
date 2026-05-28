const taskMeta = document.getElementById('task-meta');
const overviewGrid = document.getElementById('overview-grid');
const pipelineView = document.getElementById('pipeline-view');

const cgaStageTitles = {
  graph_model_loader: '语义模型加载',
  input_clarification_gate: '输入澄清门',
  question_decomposer: '问题结构化拆解',
  candidate_retrieval: '语义候选召回',
  literal_resolver: '字面值解析',
  grounded_understanding: '语义落地理解',
  semantic_binder: '语义绑定计划',
  semantic_validator: '语义正确性校验',
  repair_controller: '修复与澄清决策',
  dsl_builder: '受限 DSL 构建',
  dsl_parser: 'DSL 解析',
  cypher_compiler: 'Cypher 编译',
  cypher_self_validation: 'Cypher 自校验',
  output: '服务输出',
};

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function pretty(value) {
  if (value === null || value === undefined || value === '') {
    return '未提供';
  }
  if (typeof value === 'string') {
    return value;
  }
  return JSON.stringify(value, null, 2);
}

function tone(status) {
  switch (status) {
    case 'passed':
    case 'pass':
    case 'generated':
    case 'success':
    case 'ok':
    case 'applied':
    case true:
      return 'ok';
    case 'failed':
    case 'fail':
    case 'service_failed':
    case 'apply_failed':
    case 'rejected':
    case false:
      return 'danger';
    case 'running':
    case 'generation_failed':
    case 'unsupported_query_shape':
    case 'clarification_required':
    case 'waiting_human_review':
    case 'apply_paused':
      return 'warn';
    case 'cancelled':
    case 'skipped':
    case 'not_sent':
    case 'not_recorded':
    case 'not_started':
    case 'not_repairable':
      return 'neutral';
    default:
      return 'neutral';
  }
}

function setPipelineMessage(message) {
  pipelineView.innerHTML = `<p class="empty">${escapeHtml(message)}</p>`;
}

function metricCard(label, value, status = null) {
  return `
    <article class="overview-card">
      <div>
        <h3>${escapeHtml(label)}</h3>
        <p>${escapeHtml(value ?? '未提供')}</p>
      </div>
      ${status === null ? '' : `<span class="status-pill tone-${tone(status)}">${escapeHtml(status)}</span>`}
    </article>
  `;
}

function optionalMetricCard(label, value, status = null) {
  if (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length)) {
    return '';
  }
  return metricCard(label, value, status);
}

function codeBlock(value) {
  return `<pre>${escapeHtml(pretty(value))}</pre>`;
}

function cypherOverviewCard(label, value, status = null) {
  return `
    <article class="overview-card cypher-overview-card">
      <div>
        <h3>${escapeHtml(label)}</h3>
        ${codeBlock(value)}
      </div>
      ${status === null ? '' : `<span class="status-pill tone-${tone(status)}">${escapeHtml(status)}</span>`}
    </article>
  `;
}

function inlineValue(value) {
  if (value === null || value === undefined || value === '') {
    return '未记录';
  }
  if (Array.isArray(value)) {
    return `${value.length} 条`;
  }
  if (typeof value === 'object') {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

const stageMetricLabels = {
  llm_call_count: ['LLM 调用', '次'],
  candidate_count: ['候选召回', '个'],
  literal_count: ['字面值', '个'],
  operation_count: ['DSL 操作', '个'],
  checked_rule_count: ['校验规则', '条'],
  retry_count: ['重试', '次'],
  repair_attempt_count: ['修复轮次', '轮'],
};

function formatStageMetricKey(key) {
  const mapped = stageMetricLabels[key];
  if (mapped) {
    return mapped;
  }
  return [String(key).replace(/_/g, ' '), ''];
}

function formatStageMetricValue(value) {
  if (value === true) {
    return '是';
  }
  if (value === false) {
    return '否';
  }
  if (Array.isArray(value)) {
    return `${value.length}`;
  }
  if (value && typeof value === 'object') {
    return JSON.stringify(value);
  }
  return String(value);
}

function formatStageMetrics(metrics) {
  if (!metrics || typeof metrics !== 'object' || Array.isArray(metrics)) {
    return '无阶段指标';
  }
  const parts = Object.entries(metrics)
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => {
      const [label, unit] = formatStageMetricKey(key);
      return `${label}: ${formatStageMetricValue(value)}${unit}`;
    });
  return parts.length ? parts.join(' · ') : '无阶段指标';
}

const stageFieldHints = {
  __default: {
    input: {
      _summary: '这里展示该阶段收到的上游结构化数据。',
    },
    output: {
      _summary: '这里展示该阶段处理完成后传给下游的结构化结果。',
    },
    metrics: {
      _summary: '这里展示该阶段的计数指标、错误和警告。',
      metrics: '阶段内部记录的计数或统计值。',
      errors: '阶段执行时产生的错误列表。为空表示没有错误。',
      warnings: '阶段执行时产生的警告列表。为空表示没有警告。',
    },
  },
  graph_model_loader: {
    input: {
      _summary: '这里记录本次 CGA 读取哪一份图语义模型。',
      model_path: '语义模型 YAML 文件路径。CGA 会基于这份模型做对象召回、语义校验和 Cypher 编译。',
    },
    output: {
      _summary: '这里记录语义模型加载后的模型版本和规模。',
      model_name: '语义模型名称，用来标识本次使用的是哪套业务语义层。',
      model_checksum: '模型内容校验值，用来确认语义模型版本是否一致。',
      vertices: '点类型数量，也就是模型里定义了多少类图节点。',
      edges: '边/关系类型数量，也就是模型里定义了多少类图关系。',
      path_patterns: '命名路径模板数量，用来复用常见多跳图查询路径。',
    },
  },
  input_clarification_gate: {
    input: {
      _summary: '这里展示进入流水线前的原始问题和输入检查信息。',
      question: '用户提交的自然语言问题。',
    },
    output: {
      _summary: '这里展示问题是否足够清楚、是否可以进入后续语义生成流程。',
      status: '输入检查结果。pass 表示可以继续，clarification_required 表示问题本身需要先澄清。',
      reason_code: '触发拦截或澄清的原因代码。',
      clarification: '需要向用户提出的澄清问题。',
    },
  },
  question_decomposer: {
    input: {
      _summary: '这里展示发给问题拆解阶段的自然语言问题。',
      question: '用户提交的自然语言问题。',
    },
    output: {
      _summary: '这里展示 LLM 对问题的结构化拆解结果。',
      intent_type: '问题意图类型，例如查询列表、统计、Top-N 或路径查询。',
      target_concepts: '问题中提到的业务对象，例如服务、隧道、网元。',
      literal_candidates: '问题中可能需要解析成字段值的词，例如 Gold、down、某个设备 ID。',
      relation_phrases: '表示两个业务对象如何连接的关系短语。例如“服务使用隧道”中的“使用”，会帮助系统匹配 SERVICE_USES_TUNNEL 这类边。',
      relation_mentions: '表示两个业务对象如何连接的关系短语。例如“隧道穿过网元”中的“穿过”，会帮助系统匹配 PATH_THROUGH 这类边。',
      relationships_mentioned: '表示两个业务对象如何连接的关系短语。例如“服务使用隧道”中的“使用”，会帮助系统匹配 SERVICE_USES_TUNNEL 这类边。',
      filter_phrases: '从问题中抽取出的过滤条件短语，例如“带宽为 140”“Gold 级别”。',
      substantive_terms: '对查询语义有实际影响的词，后续必须被语义绑定、解释或明确处理。',
      stopword_terms: '礼貌用语、连接词或语气词，通常不参与语义覆盖校验。',
      modality_terms: '表达不确定、推测或要求程度的词，例如“大概”“应该”“可能”。',
      time_terms: '时间或时间范围表达，例如“最近”“2024 年”“过去 7 天”。',
      unparsed_terms: '未被前面类别吸收的残留实质词；如果非空，通常意味着需要澄清或生成失败。',
      filters: '问题中表达的过滤条件。',
      output_shape: '用户期望的返回形态，例如列表、计数或表格。',
      llm_calls: '本阶段的 LLM 调用记录，包含提示词和原始返回。',
    },
  },
  candidate_retrieval: {
    output: {
      _summary: '这里展示语义层召回到的候选对象，供后续 LLM 在候选集合内选择。',
      candidates: '召回的语义候选列表，可能包含点、边、属性、指标或路径模板。',
      semantic_id: '语义对象的稳定标识。',
      score: '召回相似度或匹配分数。',
    },
  },
  literal_resolver: {
    output: {
      _summary: '这里展示字面值解析结果，例如把 “Gold” 解析成某个枚举值。',
      raw_literal: '用户问题里的原始字面值。',
      resolved: '是否成功解析到语义层或 value-index 中的确定值。',
      resolved_value: '解析后的标准值。',
      expected: '期望匹配的语义字段。',
      error_code: '解析失败原因。',
      alternatives: '可供用户选择的候选值。',
      value_index_miss: '是否因为 value-index 没有命中而失败。',
    },
  },
  grounded_understanding: {
    output: {
      _summary: '这里展示 LLM 在候选集合内做出的语义选择。',
      query_shape: '被识别出的查询形态。',
      selected_vertices: '最终选择的点类型。',
      selected_edges: '最终选择的边/关系类型。',
      selected_properties: '最终选择的属性字段。',
      assumptions: '系统在高置信场景下做出的假设。',
    },
  },
  semantic_binder: {
    output: {
      _summary: '这里展示稳定的语义绑定计划，供校验器和 DSL 构建器使用。',
      query_shape: '查询形态。',
      bindings: '自然语言片段到语义对象的绑定结果。',
      filters: '已绑定到具体字段和值的过滤条件。',
      projections: '准备返回给用户的字段或对象。',
    },
  },
  semantic_validator: {
    output: {
      _summary: '这里展示语义正确性校验结果。',
      is_valid: '语义绑定是否通过校验。',
      errors: '语义错误，例如类型不匹配、字面值无法解析或覆盖缺失。',
      warnings: '不阻断生成的风险提示。',
      assumptions: '系统继续执行时采用的假设。',
    },
  },
  repair_controller: {
    input: {
      _summary: '这里展示校验失败或不确定时，修复决策器收到的上下文。',
      validator_errors: '语义校验器产生的错误列表。',
      repair_history: '此前修复尝试的历史，用来避免震荡。',
    },
    output: {
      _summary: '这里展示系统决定继续修复、反问用户还是终止。',
      decision: '系统决策，例如 ask_user、retry_llm 或 generation_failed。',
      reason_code: '做出该决策的主要原因。',
      clarification: '需要展示给用户的澄清反问。',
      assumptions: '如果继续执行，需要向用户说明的假设。',
    },
  },
  dsl_builder: {
    output: {
      _summary: '这里展示由语义绑定计划构建出的受限 DSL。',
      schema_version: 'DSL schema 版本。',
      query_shape: 'DSL 表达的查询形态。',
      operations: 'DSL 操作序列，例如匹配、过滤、聚合、排序。',
      projection: 'DSL 要返回的字段或对象。',
    },
  },
  dsl_parser: {
    output: {
      _summary: '这里展示 DSL 解析结果，确认 DSL 结构可以被编译器消费。',
      query_shape: '解析后的查询形态。',
      operation_count: '解析出的 DSL 操作数量。',
      errors: 'DSL 结构错误。',
    },
  },
  cypher_compiler: {
    output: {
      _summary: '这里展示 DSL 编译成 Cypher 后的结果。',
      cypher: '最终生成的 Cypher 查询文本。',
      parameters: 'Cypher 参数字典，用于承载过滤值。',
      expected_return_aliases: '编译器期望 RETURN 中出现的字段别名。',
    },
  },
  cypher_self_validation: {
    output: {
      _summary: '这里展示不连接数据库前的 Cypher 静态自校验结果。',
      valid: 'Cypher 是否通过自校验。',
      errors: '阻断提交的静态错误，例如写操作、未知 label 或 RETURN 形态不一致。',
      warnings: '不阻断提交的风险提示。',
      checked_rules: '本次执行过的校验规则。',
    },
  },
  output: {
    output: {
      _summary: '这里展示 CGA 最终对外输出的状态。',
      status: '最终状态，例如 generated、clarification_required 或 generation_failed。',
      has_dsl: '是否已经生成 DSL。',
      has_cypher: '是否已经生成可提交的 Cypher。',
      clarification: '如果需要反问用户，这里记录澄清内容。',
    },
  },
};

function stageFieldHint(stageKey, section) {
  return {
    ...(stageFieldHints.__default?.[section] || {}),
    ...(stageFieldHints[stageKey]?.[section] || {}),
  };
}

function payloadFieldKeys(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return [];
  }
  return Object.keys(payload).filter((key) => key !== '_summary');
}

function renderStageSectionHelp(stage, section, payload) {
  const hints = stageFieldHint(stage.key, section);
  const keys = payloadFieldKeys(payload);
  const knownKeys = keys.slice(0, 12);
  const items = knownKeys.map((key) => {
    const description = hints[key] || `该字段由 ${stage.title_zh || cgaStageTitles[stage.key] || stage.key || '当前'} 阶段记录，保留原始 trace 字段名。`;
    return `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(description)}</dd></div>`;
  });
  if (!items.length && !hints._summary) {
    return '';
  }
  const extraCount = Math.max(0, keys.length - knownKeys.length);
  return `
    <aside class="field-help">
      <h4>字段说明</h4>
      ${hints._summary ? `<p>${escapeHtml(hints._summary)}</p>` : ''}
      ${
        items.length
          ? `<dl>${items.join('')}${
              extraCount ? `<div><dt>其他字段</dt><dd>${escapeHtml(`还有 ${extraCount} 个字段，请参考下方原始 JSON。`)}</dd></div>` : ''
            }</dl>`
          : `<p>下方没有结构化字段，或本阶段没有额外记录。</p>`
      }
    </aside>
  `;
}

function humanAnswerType(value) {
  const labels = {
    free_text: '自由文本回答',
    single_choice: '单选',
    multi_choice: '多选',
    confirmation: '确认',
  };
  return labels[value] || value || '';
}

function humanDecision(value) {
  const labels = {
    ask_user: '请求用户澄清',
    continue_with_assumption: '带假设继续',
    retry_llm: '回灌 LLM 修正',
    generation_failed: '生成失败',
    unsupported_query_shape: '不支持的查询形态',
  };
  return labels[value] || value || '';
}

function humanReason(value) {
  const labels = {
    literal_unresolved: '字面值无法解析',
    ambiguous_binding: '语义绑定存在歧义',
    coverage_missing: '问题中有实质词未覆盖',
    type_mismatch: '语义类型不匹配',
    unsupported_query_shape: '不支持的查询形态',
  };
  return labels[value] || value || '';
}

function compactParts(parts) {
  return parts.filter((part) => part !== null && part !== undefined && part !== '').join(' · ');
}

function optionLabel(option) {
  if (option && typeof option === 'object') {
    return option.label || option.summary || option.description || option.value || option.id || JSON.stringify(option);
  }
  return String(option ?? '');
}

function formatAlternatives(alternatives) {
  if (!Array.isArray(alternatives) || !alternatives.length) {
    return '';
  }
  return `候选：${alternatives.map(optionLabel).filter(Boolean).join('、')}`;
}

function renderClarificationList(title, items, formatter) {
  if (!Array.isArray(items) || !items.length) {
    return '';
  }
  return `
    <h3>${escapeHtml(title)}</h3>
    <div class="clarification-list">
      ${items.map((item) => formatter(item)).join('')}
    </div>
  `;
}

function renderClarificationItem(primary, meta, alternatives = '') {
  return `
    <article class="clarification-item">
      <strong>${escapeHtml(primary || '未命名项')}</strong>
      ${meta ? `<small>${escapeHtml(meta)}</small>` : ''}
      ${alternatives ? `<small>${escapeHtml(alternatives)}</small>` : ''}
    </article>
  `;
}

function renderUnresolvedItem(item = {}) {
  const meta = compactParts([
    item.expected ? `期望语义：${item.expected}` : '',
    item.code ? `原因：${item.code}` : '',
    item.value_index_miss ? 'value-index 未命中' : '',
  ]);
  return renderClarificationItem(item.term || item.literal || item.raw_literal, meta, formatAlternatives(item.alternatives));
}

function renderValidationError(item = {}) {
  const meta = compactParts([
    item.code ? `代码：${item.code}` : '',
    item.action ? `动作：${item.action}` : '',
    item.literal ? `字面值：${item.literal}` : '',
    item.property ? `期望语义：${item.property}` : '',
  ]);
  return renderClarificationItem(item.message || item.reason || item.code, meta, formatAlternatives(item.alternatives));
}

function renderClarificationBlock(clarification) {
  if (!clarification || typeof clarification !== 'object') {
    return '';
  }
  const options = Array.isArray(clarification.options) ? clarification.options : [];
  const sourceStage =
    clarification.source_stage_label_zh ||
    cgaStageTitles[clarification.source_stage] ||
    cgaStageTitles[clarification.source_step] ||
    clarification.source_stage ||
    clarification.source_step;
  const fieldCards = [
    optionalMetricCard('澄清问题', clarification.question_zh || clarification.question || clarification.user_message),
    optionalMetricCard('系统决策', humanDecision(clarification.decision), clarification.decision),
    optionalMetricCard('触发原因', humanReason(clarification.reason_code)),
    optionalMetricCard('触发阶段', sourceStage),
    optionalMetricCard('回答方式', humanAnswerType(clarification.expected_answer_type)),
  ].join('');
  const optionBlock = options.length
    ? `
      <h3>澄清选项</h3>
      <div class="clarification-options">${options
        .map((option) => `<span>${escapeHtml(optionLabel(option) || '未命名选项')}</span>`)
        .join('')}</div>
    `
    : clarification.no_option_reason
      ? `
        <h3>澄清选项</h3>
        <p class="empty">${escapeHtml(clarification.no_option_reason)}</p>
      `
      : '';
  return `
    <section class="clarification-box">
      <h3>澄清反问</h3>
      ${fieldCards ? `<div class="field-grid">${fieldCards}</div>` : ''}
      ${renderClarificationList('未解析项', clarification.unresolved_items, renderUnresolvedItem)}
      ${renderClarificationList('校验错误', clarification.validation_errors, renderValidationError)}
      ${optionBlock}
    </section>
  `;
}

function emptyCypherText(value) {
  return value ? value : '未生成可评测 Cypher';
}

function generationCypherText(section) {
  if (section.generation_status === 'clarification_required') {
    return '需要澄清';
  }
  return emptyCypherText(section.generated_cypher || section.parsed_cypher);
}

function tableCellValue(value) {
  if (value === null || value === undefined || value === '') {
    return '未记录';
  }
  if (typeof value === 'object') {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

function renderTraceTable(table = {}) {
  const columns = Array.isArray(table.columns) ? table.columns : [];
  const rows = Array.isArray(table.rows) ? table.rows : [];
  if (!columns.length) {
    return '';
  }
  const colgroup = columns
    .map((column) => {
      const width = Number(column.width || 0);
      return width > 0 ? `<col style="width: ${width}px" />` : '<col />';
    })
    .join('');
  const emptyRow = `
    <tr>
      <td class="empty-cell" colspan="${columns.length}">未记录</td>
    </tr>
  `;
  return `
    <div class="trace-table-block">
      <h3>${escapeHtml(table.title_zh || '明细表')}</h3>
      <div class="trace-table-shell">
        <table class="trace-table">
          <colgroup>${colgroup}</colgroup>
          <thead>
            <tr>${columns.map((column) => `<th>${escapeHtml(column.label_zh || column.key || '字段')}</th>`).join('')}</tr>
          </thead>
          <tbody>
            ${
              rows.length
                ? rows
                    .map(
                      (row) => `
                        <tr>${columns
                          .map((column) => `<td>${escapeHtml(tableCellValue(row?.[column.key]))}</td>`)
                          .join('')}</tr>
                      `,
                    )
                    .join('')
                : emptyRow
            }
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function renderOverview(detail) {
  const summary = detail.summary || {};
  const pipeline = detail.pipeline || {};
  const generator = pipeline.cypher_generator_agent || {};
  const testing = pipeline.testing_agent || {};
  const goldenCypher = generator.golden_cypher || testing.golden_cypher;
  const generatedCypher = generator.generated_cypher || generator.parsed_cypher || testing.actual_cypher;
  taskMeta.textContent = `${summary.id || detail.id} · ${summary.question || '未提供问题文本'}`;
  overviewGrid.innerHTML = [
    metricCard('自然语言问题', summary.question || '未提供'),
    metricCard('难度', summary.difficulty || '未标注'),
    metricCard('当前尝试次数', summary.attempt_no || 0),
    metricCard('生成状态', summary.generation_status || '未提供', summary.generation_status),
    metricCard('最终结论', summary.final_verdict || detail.final_verdict, summary.final_verdict || detail.final_verdict),
    metricCard('当前阶段', summary.current_stage || 'pending'),
    metricCard('澄清反问', summary.clarification_summary || '未触发澄清'),
    metricCard('更新时间', summary.updated_at || detail.updated_at || '未提供'),
    cypherOverviewCard('标准 Cypher', goldenCypher || '未提供'),
    cypherOverviewCard('生成 Cypher', generationCypherText({ ...generator, generated_cypher: generatedCypher })),
  ].join('');
}

function renderCgaFlowSummary(flow = {}, section = {}) {
  const summary = flow.summary || {};
  return `
    <h3>CGA 全流程</h3>
    <div class="field-grid">
      ${metricCard('Trace ID', flow.trace_id || '未记录')}
      ${metricCard('Trace Schema', flow.schema_version || section.trace_schema_version || '未记录')}
      ${metricCard('最终状态', flow.final_status || section.generation_status || '未记录', flow.final_status || section.generation_status)}
      ${metricCard('语义模型', summary.semantic_model || '未记录')}
      ${metricCard('当前阶段', summary.current_stage_title_zh || summary.current_stage || '未记录')}
      ${metricCard('LLM 调用数', summary.llm_call_count ?? 0)}
      ${metricCard('开始时间', flow.started_at || '未记录')}
      ${metricCard('结束时间', flow.finished_at || '未记录')}
    </div>
  `;
}

function renderCgaFlowStages(flow = {}) {
  const stages = Array.isArray(flow.stages) ? flow.stages : [];
  const table = {
    title_zh: 'GraphTrace v1 阶段明细',
    columns: [
      { key: 'title_zh', label_zh: '阶段', width: 180 },
      { key: 'key', label_zh: 'stage key', width: 220 },
      { key: 'status', label_zh: '状态', width: 120 },
      { key: 'duration_ms', label_zh: '耗时 ms', width: 100 },
      { key: 'metrics_summary', label_zh: '阶段指标', width: 420 },
      { key: 'error_summary', label_zh: '错误 / 警告', width: 520 },
    ],
    rows: stages.map((stage) => ({
      ...stage,
      title_zh: stage.title_zh || cgaStageTitles[stage.key] || stage.key,
      metrics_summary: formatStageMetrics(stage.metrics),
      error_summary: [stage.errors?.length ? `errors=${stage.errors.length}` : '', stage.warnings?.length ? `warnings=${stage.warnings.length}` : '']
        .filter(Boolean)
        .join(' · ') || '无',
    })),
  };
  return `
    ${renderTraceTable(table)}
    ${stages
      .map(
        (stage) => `
          <details class="trace-substep">
            <summary>
              <span>${escapeHtml(stage.title_zh || cgaStageTitles[stage.key] || stage.key || '未命名阶段')}</span>
              <span class="status-pill tone-${tone(stage.status)}">${escapeHtml(stage.status || 'unknown')}</span>
            </summary>
            <h3>阶段输入</h3>
            ${renderStageSectionHelp(stage, 'input', stage.input)}
            ${codeBlock(stage.input)}
            <h3>阶段输出</h3>
            ${renderStageSectionHelp(stage, 'output', stage.output)}
            ${codeBlock(stage.output)}
            <h3>阶段指标 / 错误 / 警告</h3>
            ${renderStageSectionHelp(stage, 'metrics', { metrics: stage.metrics, errors: stage.errors, warnings: stage.warnings })}
            ${codeBlock({ metrics: stage.metrics, errors: stage.errors, warnings: stage.warnings })}
          </details>
        `,
      )
      .join('')}
  `;
}

function renderCgaLlmCalls(flow = {}) {
  const calls = Array.isArray(flow.llm_calls) ? flow.llm_calls : [];
  if (!calls.length) {
    return `
      <h3>LLM 调用明细</h3>
      <p class="empty">本次 CGA 主链路未触发 LLM 调用，或历史记录未保存 prompt/raw output。</p>
    `;
  }
  return `
    <h3>LLM 调用明细</h3>
    ${calls
      .map(
        (call, index) => `
          <section class="llm-call-card">
            <div class="task-card-head">
              <strong>${escapeHtml(call.stage_title_zh || call.stage || `LLM 调用 ${index + 1}`)}</strong>
              <span class="status-pill tone-${tone(call.status)}">${escapeHtml(call.status || 'unknown')}</span>
            </div>
            <div class="field-grid">
              ${metricCard('Call ID', call.call_id || `llm-${index + 1}`)}
              ${metricCard('Schema', call.schema_name || '未记录')}
              ${metricCard('模型', call.model || '未记录')}
              ${metricCard('Attempt', call.attempt ?? '未记录')}
            </div>
            <h3>发给 LLM 的提示词</h3>
            ${codeBlock(call.prompt || '未记录')}
            <h3>LLM 原始返回</h3>
            ${codeBlock(call.raw_output || '未记录')}
            <h3>解析后输出 / 错误</h3>
            ${codeBlock({ parsed_output: call.parsed_output, error: call.error })}
          </section>
        `,
      )
      .join('')}
  `;
}

function renderCgaArtifacts(flow = {}) {
  const artifacts = flow.artifacts || {};
  return `
    <h3>DSL / Cypher / 自校验</h3>
    <div class="artifact-grid">
      <section>
        <h3>最终 DSL</h3>
        ${codeBlock(artifacts.dsl)}
      </section>
      <section>
        <h3>最终 Cypher</h3>
        ${codeBlock(artifacts.cypher)}
      </section>
      <section>
        <h3>Cypher 编译输出</h3>
        ${codeBlock(artifacts.compiler)}
      </section>
      <section>
        <h3>Cypher 自校验输出</h3>
        ${codeBlock(artifacts.self_validation)}
      </section>
      <section>
        <h3>用户可见说明</h3>
        ${codeBlock(artifacts.user_visible_notices || [])}
      </section>
      <section>
        <h3>失败 / 澄清输出</h3>
        ${codeBlock({ failure: artifacts.failure, clarification: artifacts.clarification })}
      </section>
    </div>
  `;
}

function renderCypherGenerator(section) {
  const flow = section.cga_flow || {};
  const hasFlow = Array.isArray(flow.stages) && flow.stages.length;
  return `
    <details class="pipeline-step" open>
      <summary>
        <span>cypher-generator-agent</span>
        <span class="status-pill tone-${tone(section.generation_status)}">${escapeHtml(section.generation_status || 'unknown')}</span>
      </summary>
      ${renderClarificationBlock(section.clarification)}
      ${
        hasFlow
          ? `
            ${renderCgaFlowSummary(flow, section)}
            ${renderCgaFlowStages(flow)}
            ${renderCgaLlmCalls(flow)}
            ${renderCgaArtifacts(flow)}
          `
          : `
            <h3>CGA 全流程</h3>
            <p class="empty">未读取到 cga_graph_trace_v1 快照。以下仅保留原始生成证据。</p>
            ${codeBlock(section.prompt_markdown)}
          `
      }
      <h3>生成运行 ID</h3>
      ${codeBlock(section.generation_run_id || '未提供')}
    </details>
  `;
}

function renderTestingAgent(section) {
  const grammar = section.grammar || {};
  const executionAccuracy = section.execution_accuracy || {};
  const semanticReview = section.semantic_review || {};
  const secondary = section.secondary_metrics || {};
  const evaluationTone = grammar.score === undefined && executionAccuracy.score === undefined
    ? 'pending'
    : ((grammar.score === 1 && executionAccuracy.score === 1) ? 'passed' : 'failed');
  return `
    <details class="pipeline-step" open>
      <summary>
        <span>testing-agent</span>
        <span class="status-pill tone-${tone(evaluationTone)}">grammar ${escapeHtml(grammar.score ?? '未评测')}</span>
      </summary>
      <div class="field-grid">
        ${metricCard('grammar score', `${grammar.score ?? '未评测'}（0 = 未通过，1 = 通过）`)}
        ${metricCard('grammar 原因', grammar.parser_error || grammar.message || '无')}
        ${metricCard('EX 得分', executionAccuracy.score ?? '未评测')}
        ${metricCard('EX 原因', executionAccuracy.reason || '未提供')}
        ${metricCard('严格比较结果', (section.strict_check || {}).status || 'not_run')}
        ${metricCard('GLEU', secondary.gleu ?? '未计算')}
        ${metricCard('similarity', secondary.similarity ?? '未计算')}
      </div>
      <h3>golden Cypher</h3>
      ${codeBlock(section.golden_cypher)}
      <h3>golden answer</h3>
      ${codeBlock(section.golden_answer)}
      <h3>actual Cypher</h3>
      ${codeBlock(section.actual_cypher)}
      <h3>执行结果</h3>
      ${codeBlock(section.execution)}
      <h3>严格比较差异</h3>
      ${codeBlock((section.strict_check || {}).evidence || section.strict_check)}
      <h3>语义评判 prompt</h3>
      ${codeBlock(semanticReview.prompt)}
      <h3>语义评判原始返回</h3>
      ${codeBlock(semanticReview.raw_output)}
      <h3>语义评判结构化结果</h3>
      ${codeBlock({
        status: semanticReview.status,
        payload: semanticReview.payload,
        judgement: semanticReview.judgement,
        reasoning: semanticReview.reasoning,
        message: semanticReview.message,
      })}
      <h3>improvement</h3>
      ${codeBlock(section.improvement)}
    </details>
  `;
}

function renderRepairAgent(section) {
  const repairState = section.repair_state || {};
  const applyState = section.knowledge_apply_state || {};
  const redispatchState = section.redispatch_state || {};
  const statusLabel = repairState.label_zh || section.status || (section.analysis_id ? 'recorded' : 'not recorded');
  const statusTone = repairState.value || (section.status === 'not_repairable' ? 'not_repairable' : (section.analysis_id ? 'applied' : 'pending'));
  const nonRepairableReason = section.status === 'not_repairable'
    ? `
      <h3>不修复原因</h3>
      ${codeBlock(section.non_repairable_reason || 'repair-agent 判定该问题不是 knowledge-agent 知识缺口。')}
    `
    : '';
  return `
    <details class="pipeline-step" open>
      <summary>
        <span>repair-agent</span>
        <span class="status-pill tone-${tone(statusTone)}">${escapeHtml(statusLabel)}</span>
      </summary>
      <h3>repair 状态</h3>
      <div class="field-grid">
        ${metricCard('诊断状态', `${repairState.label_zh || '未记录'}${repairState.raw_status ? `（原始值：${repairState.raw_status}）` : ''}`, repairState.value)}
        ${metricCard('知识应用状态', `${applyState.label_zh || '未记录'}${applyState.raw_status ? `（原始值：${applyState.raw_status}）` : ''}`, applyState.value)}
        ${metricCard('redispatch 状态', `${redispatchState.label_zh || '未记录'}${redispatchState.reason ? `（原因：${redispatchState.reason}）` : ''}`, redispatchState.value)}
        ${metricCard('applied 原始标记', section.applied ?? '未记录')}
      </div>
      ${repairState.message ? `<h3>诊断状态说明</h3>${codeBlock(repairState.message)}` : ''}
      ${applyState.message ? `<h3>知识应用说明</h3>${codeBlock(applyState.message)}` : ''}
      ${redispatchState.message ? `<h3>redispatch 说明</h3>${codeBlock(redispatchState.message)}` : ''}
      <h3>repair-agent 诊断提示词</h3>
      ${codeBlock(section.llm_prompt_markdown)}
      <h3>repair-agent 原始返回</h3>
      ${codeBlock(section.raw_output)}
      ${nonRepairableReason}
      <h3>发送给 knowledge-agent 的报文</h3>
      ${codeBlock(section.knowledge_agent_request)}
      <h3>knowledge-agent 响应</h3>
      ${codeBlock(section.knowledge_agent_response)}
    </details>
  `;
}

function renderPipeline(detail) {
  const pipeline = detail.pipeline || {};
  pipelineView.innerHTML = [
    renderCypherGenerator(pipeline.cypher_generator_agent || {}),
    renderTestingAgent(pipeline.testing_agent || {}),
    renderRepairAgent(pipeline.repair_agent || {}),
  ].join('');
}

function taskIdFromLocation() {
  const parts = window.location.pathname.split('/').filter(Boolean);
  return decodeURIComponent(parts[parts.length - 1] || '');
}

async function loadTaskDetail() {
  const taskId = taskIdFromLocation();
  if (!taskId) {
    throw new Error('missing task id');
  }
  const response = await fetch(`/api/v1/tasks/${encodeURIComponent(taskId)}`);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const payload = await response.json();
  renderOverview(payload);
  renderPipeline(payload);
}

loadTaskDetail().catch((error) => {
  taskMeta.textContent = `详情加载失败: ${String(error)}`;
  setPipelineMessage(`详情加载失败: ${String(error)}`);
});
