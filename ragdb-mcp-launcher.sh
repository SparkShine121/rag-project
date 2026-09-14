#!/bin/bash
# ragdb MCP stdio 启动器（供 Hermes mcp_servers 调用）
# 作用：进入项目根目录（ragdb 从 cwd 发现 ragdb.toml）+ 离线模式 + 直连 venv 入口
{
  echo "=== $(date '+%H:%M:%S') launcher 被调用 ==="
  echo "cwd=$PWD  args=$*"
  echo "PATH=$PATH"
  env | grep -E "^(HOME|USER|HF_|HTTPS?_PROXY|http_proxy|VIRTUAL_ENV)" | sort
} >> /tmp/ragdb_launcher_invocations.log 2>&1
cd "$(dirname "$0")" || exit 1
export HF_HUB_OFFLINE=1
exec .venv/bin/ragdb-mcp
