#!/bin/bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="${PROJECT_ROOT}/run"
LOG_DIR="${PROJECT_ROOT}/logs"
PYTHON_BIN="${PYTHON_BIN:-${PROJECT_ROOT}/.venv/bin/python}"
HOST="${APP_HOST:-0.0.0.0}"

mkdir -p "${PROJECT_ROOT}/data" "${RUN_DIR}" "${LOG_DIR}"

if [ -f "${PROJECT_ROOT}/.env" ]; then
  set -a
  . "${PROJECT_ROOT}/.env"
  set +a
fi

if [ ! -x "${PYTHON_BIN}" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  else
    echo "❌ 未找到可用的 Python 解释器，请先创建 .venv 或安装 python3"
    exit 1
  fi
fi

start_service() {
  local service_name="$1"
  local module_path="$2"
  local port="$3"
  local pid_file="${RUN_DIR}/${service_name}.pid"
  local log_file="${LOG_DIR}/${service_name}.log"

  if [ -f "${pid_file}" ]; then
    local existing_pid
    existing_pid="$(cat "${pid_file}")"
    if kill -0 "${existing_pid}" 2>/dev/null; then
      echo "ℹ️  ${service_name} 已在运行 (PID ${existing_pid})"
      return 0
    fi
    rm -f "${pid_file}"
  fi

  local port_pid
  port_pid="$(ss -ltnp 2>/dev/null | awk -v port=":${port}" '$4 ~ port && /pid=/ {split($0, a, "pid="); split(a[2], b, ","); print b[1]; exit}')"
  if [ -n "${port_pid}" ]; then
    echo "ℹ️  ${service_name} 端口 ${port} 已被 PID ${port_pid} 占用，复用现有进程"
    echo "${port_pid}" >"${pid_file}"
    return 0
  fi

  nohup "${PYTHON_BIN}" -m uvicorn "${module_path}" --host "${HOST}" --port "${port}" \
    >>"${log_file}" 2>&1 &
  echo $! >"${pid_file}"
  echo "✅ ${service_name} 已启动 (PID $(cat "${pid_file}"), port ${port})"
}

echo "🚀 启动 Text2Cypher 闭环系统..."

start_service "query_generator_service" "services.query_generator_agent.app.main:app" "8000"
start_service "runtime_results_service" "console.runtime_console.app.main:app" "8001"
start_service "repair_service" "services.repair_agent.app.main:app" "8002"
start_service "testing_service" "services.testing_agent.app.main:app" "8003"

echo
echo "📊 服务地址："
echo "  查询语句生成服务: http://127.0.0.1:8000"
echo "  运行结果中心: http://127.0.0.1:8001"
echo "  修复服务: http://127.0.0.1:8002"
echo "  测试服务: http://127.0.0.1:8003"
echo
echo "📝 日志目录: ${LOG_DIR}"
echo "🧾 PID 目录: ${RUN_DIR}"
