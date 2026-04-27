#!/usr/bin/env bash
set -euo pipefail

declare -a pids=()

cleanup() {
  for pid in "${pids[@]:-}"; do
    kill -9 "$pid" 2>/dev/null || true
  done
}

trap cleanup EXIT INT TERM

cd "$(dirname "$0")/.."

lsof -ti:8000,8001,8002,8010,8020 2>/dev/null | xargs kill -9 2>/dev/null || true
sleep 1

set -a
if [ -f ".env" ]; then
  . .env
fi
set +a

export QUERY_GENERATOR_KNOWLEDGE_OPS_SERVICE_URL=http://127.0.0.1:8010
export QUERY_GENERATOR_TESTING_SERVICE_URL=http://127.0.0.1:8001
export TESTING_SERVICE_REPAIR_SERVICE_URL=http://127.0.0.1:8002
export REPAIR_SERVICE_QUERY_GENERATOR_SERVICE_URL=http://127.0.0.1:8000
export REPAIR_SERVICE_KNOWLEDGE_OPS_REPAIRS_APPLY_URL=http://127.0.0.1:8010/api/knowledge/repairs/apply

export QUERY_GENERATOR_LLM_ENABLED=true
export TESTING_SERVICE_LLM_ENABLED=true
export REPAIR_SERVICE_LLM_ENABLED=true
export REPAIR_SERVICE_GENERATOR_LLM_ENABLED=true

if [ -n "${TESTING_SERVICE_LLM_BASE_URL:-}" ]; then
  export OPENAI_BASE_URL="${TESTING_SERVICE_LLM_BASE_URL}"
fi
if [ -n "${TESTING_SERVICE_LLM_API_KEY:-}" ]; then
  export OPENAI_API_KEY="${TESTING_SERVICE_LLM_API_KEY}"
fi
if [ -n "${TESTING_SERVICE_LLM_MODEL:-}" ]; then
  export OPENAI_MODEL="${TESTING_SERVICE_LLM_MODEL}"
fi

KNOWLEDGE_AGENT_ROOT="${KNOWLEDGE_AGENT_ROOT:-}"
QA_AGENT_ROOT="${QA_AGENT_ROOT:-}"

health_ports=(8000 8001 8002)

if [ -n "${KNOWLEDGE_AGENT_ROOT}" ]; then
  (
    cd "${KNOWLEDGE_AGENT_ROOT}/backend" &&
      APP_HOST=0.0.0.0 APP_PORT=8010 python run_api.py
  ) &
  pids+=("$!")
  health_ports+=(8010)
else
  echo "⚠️  skipping knowledge-agent startup: KNOWLEDGE_AGENT_ROOT not set"
fi

if [ -n "${QA_AGENT_ROOT}" ]; then
  (
    cd "${QA_AGENT_ROOT}" &&
      APP_HOST=0.0.0.0 APP_PORT=8020 TEST_AGENT_HOST=127.0.0.1 TEST_AGENT_QUESTION_PORT=8000 TEST_AGENT_GOLDEN_PORT=8001 .venv/bin/python run_api.py
  ) &
  pids+=("$!")
  health_ports+=(8020)
else
  echo "⚠️  skipping qa-agent startup: QA_AGENT_ROOT not set"
fi

python -m uvicorn services.repair_agent.app.main:app --host 0.0.0.0 --port 8002 &
pids+=("$!")
python -m uvicorn services.testing_agent.app.main:app --host 0.0.0.0 --port 8001 &
pids+=("$!")
python -m uvicorn services.cypher_generator_agent.app.main:app --host 0.0.0.0 --port 8000 &
pids+=("$!")

for _ in $(seq 1 30); do
  ok=0
  for p in "${health_ports[@]}"; do
    if curl -s --max-time 1 "http://127.0.0.1:${p}/health" >/dev/null; then
      ok=$((ok + 1))
    fi
  done
  if [ "$ok" -eq "${#health_ports[@]}" ]; then
    break
  fi
  sleep 1
done

echo "running:"
echo "  cypher-generator-agent    http://127.0.0.1:8000"
echo "  testing-agent            http://127.0.0.1:8001"
echo "  repair-agent      http://127.0.0.1:8002"
if [ -n "${KNOWLEDGE_AGENT_ROOT}" ]; then
  echo "  knowledge-agent          http://127.0.0.1:8010"
fi
if [ -n "${QA_AGENT_ROOT}" ]; then
  echo "  qa-agent                 http://127.0.0.1:8020"
fi
echo
echo "health:"
for p in "${health_ports[@]}"; do
  echo -n "  ${p} -> "
  curl -s --max-time 2 "http://127.0.0.1:${p}/health" 2>/dev/null || echo DOWN
  echo
done
echo
echo "cgs generator:"
curl -s --max-time 2 http://127.0.0.1:8000/api/v1/generator/status || true
echo

wait
