#!/bin/bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="${PROJECT_ROOT}/run"

stop_service() {
  local service_name="$1"
  local port="$2"
  local pid_file="${RUN_DIR}/${service_name}.pid"
  local pid=""

  if [ -f "${pid_file}" ]; then
    pid="$(cat "${pid_file}")"
  fi

  if [ -z "${pid}" ] || ! kill -0 "${pid}" 2>/dev/null; then
    pid="$(ss -ltnp 2>/dev/null | awk -v port=":${port}" '$4 ~ port && /pid=/ {split($0, a, "pid="); split(a[2], b, ","); print b[1]; exit}')"
  fi

  if [ -z "${pid}" ]; then
    echo "ℹ️  ${service_name} 没有找到运行进程，跳过"
    rm -f "${pid_file}"
    return 0
  fi

  if kill -0 "${pid}" 2>/dev/null; then
    kill "${pid}"
    for _ in $(seq 1 10); do
      if ! kill -0 "${pid}" 2>/dev/null; then
        break
      fi
      sleep 1
    done
    if kill -0 "${pid}" 2>/dev/null; then
      echo "⚠️  ${service_name} 未及时退出，执行强制终止"
      kill -9 "${pid}"
    fi
    echo "✅ ${service_name} 已停止"
  else
    echo "ℹ️  ${service_name} 进程不存在，清理 PID 文件"
  fi

  rm -f "${pid_file}"
}

echo "🛑 停止 Text2Cypher 闭环系统..."

stop_service "runtime_results_service" "8001"
stop_service "repair_service" "8002"
stop_service "testing_service" "8003"
stop_service "query_generator_service" "8000"
