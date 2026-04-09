const form = document.getElementById('workflow-form');
const statusStrip = document.getElementById('status-strip');
const metaGrid = document.getElementById('meta-grid');
const generatedCypher = document.getElementById('generated-cypher');
const rawView = document.getElementById('raw-view');
const summaryView = document.getElementById('summary-view');
const executionView = document.getElementById('execution-view');

Array.from(document.querySelectorAll('.tab')).forEach((button) => {
  button.addEventListener('click', () => {
    Array.from(document.querySelectorAll('.tab')).forEach((tab) => tab.classList.remove('active'));
    Array.from(document.querySelectorAll('.tab-content')).forEach((tab) => tab.classList.remove('active'));
    button.classList.add('active');
    document.getElementById(`tab-${button.dataset.tab}`).classList.add('active');
  });
});

function setExample(id, question) {
  form.id.value = id;
  form.question.value = question;
}

document.getElementById('fill-normal').addEventListener('click', () => {
  setExample('qa-demo-normal', '查询网络设备及其端口');
});

document.getElementById('fill-ambiguous').addEventListener('click', () => {
  setExample('qa-demo-ambiguous', '帮我看看网络情况');
});

function renderMeta(data) {
  const rows = [
    ['ID', data.id || '-'],
    ['状态', data.status || '-'],
    ['评测状态', data.evaluation_status || '-'],
    ['图谱', data.knowledge_context?.graph_name || '-'],
  ];

  metaGrid.innerHTML = rows.map(([label, value]) => `
    <div>
      <span>${label}</span>
      <strong>${value}</strong>
    </div>
  `).join('');
}

function renderSummary(data) {
  const tags = data.knowledge_context?.loaded_knowledge_tags || [];
  const items = [
    {
      title: '输入问题',
      body: data.question || '-',
      tags: [`id: ${data.id || '-'}`],
    },
    {
      title: '知识包',
      body: data.knowledge_context?.summary || '-',
      tags: tags.map((tag) => `tag: ${tag}`),
    },
    {
      title: '提交测试服务',
      body: `evaluation_status: ${data.evaluation_status || '-'}`,
      tags: [`execution_success: ${data.execution?.success}`],
    },
  ];

  summaryView.innerHTML = items.map((item) => `
    <article class="timeline-item">
      <h3>${item.title}</h3>
      <p>${item.body}</p>
      <div class="tag-row">${item.tags.map((tag) => `<span class="tag">${tag}</span>`).join('')}</div>
    </article>
  `).join('');
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  statusStrip.textContent = '执行中...';

  const payload = {
    id: form.id.value.trim(),
    question: form.question.value.trim(),
  };

  try {
    const response = await fetch('/api/v1/qa/questions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail ? JSON.stringify(data.detail) : '请求失败');
    }

    statusStrip.textContent = `${data.status} / ${data.evaluation_status}`;
    generatedCypher.textContent = data.generated_cypher || '尚未生成';
    executionView.textContent = JSON.stringify(data.execution, null, 2);
    rawView.textContent = JSON.stringify(data, null, 2);
    renderMeta(data);
    renderSummary(data);
  } catch (error) {
    statusStrip.textContent = '执行失败';
    rawView.textContent = String(error);
    summaryView.innerHTML = `<p class="empty">${String(error)}</p>`;
    generatedCypher.textContent = '请求失败';
    executionView.textContent = '{}';
  }
});
