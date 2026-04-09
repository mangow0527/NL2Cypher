const form = document.getElementById('golden-form');
const banner = document.getElementById('banner');
const chips = document.getElementById('chips');
const statusView = document.getElementById('status-view');
const evaluationView = document.getElementById('evaluation-view');
const issueView = document.getElementById('issue-view');
const lookupIdInput = document.getElementById('lookup-id');

function renderChips(items) {
  chips.innerHTML = items.map((item) => `<span class="chip">${item}</span>`).join('');
}

function fillGoldenExample() {
  form.id.value = 'qa-demo-normal';
  form.cypher.value = 'MATCH (ne:NetworkElement)-[:HAS_PORT]->(p:Port) RETURN ne.name AS device_name, p.name AS port_name, p.status AS port_status LIMIT 20';
  form.answer.value = '[{"id":"ne-1","name":"edge-router-1"}]';
  form.difficulty.value = 'L3';
  lookupIdInput.value = 'qa-demo-normal';
}

document.getElementById('fill-golden').addEventListener('click', fillGoldenExample);

document.getElementById('lookup-evaluation').addEventListener('click', async () => {
  const id = lookupIdInput.value.trim();
  if (!id) {
    banner.textContent = '请先输入 id';
    return;
  }
  await loadEvaluation(id);
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  banner.textContent = '提交 Golden 中...';
  const payload = {
    id: form.id.value.trim(),
    cypher: form.cypher.value.trim(),
    answer: JSON.parse(form.answer.value.trim()),
    difficulty: form.difficulty.value.trim(),
  };

  try {
    const response = await fetch('/api/v1/qa/goldens', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail ? JSON.stringify(data.detail) : '请求失败');
    }

    banner.textContent = `Golden 已接收: ${data.status}`;
    renderChips([
      `id: ${data.id}`,
      `status: ${data.status}`,
      `verdict: ${data.verdict || '-'}`,
      `ticket: ${data.issue_ticket_id || '-'}`,
    ]);
    lookupIdInput.value = data.id;
    await loadEvaluation(data.id, data.issue_ticket_id);
  } catch (error) {
    banner.textContent = '提交失败';
    evaluationView.textContent = String(error);
    issueView.textContent = '{}';
  }
});

async function loadEvaluation(id, issueTicketId = '') {
  const response = await fetch(`/api/v1/evaluations/${encodeURIComponent(id)}`);
  const data = await response.json();
  evaluationView.textContent = JSON.stringify(data, null, 2);
  banner.textContent = `已加载 ${id} 的评测状态`;
  if (issueTicketId) {
    await loadIssue(issueTicketId);
  } else {
    issueView.textContent = '{}';
  }
}

async function loadIssue(ticketId) {
  if (!ticketId) {
    issueView.textContent = '{}';
    return;
  }
  const response = await fetch(`/api/v1/issues/${encodeURIComponent(ticketId)}`);
  const data = await response.json();
  issueView.textContent = JSON.stringify(data, null, 2);
}

async function loadStatus() {
  try {
    const response = await fetch('/api/v1/status');
    const data = await response.json();
    statusView.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    statusView.textContent = String(error);
  }
}

loadStatus();
