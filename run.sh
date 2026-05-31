#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "🚀 CNKI Search — 知网文献检索"
echo "================================"

if [ $# -eq 0 ]; then
    echo ""
    echo "用法:"
    echo '  ./run.sh "关键词"                       默认5年内所有期刊'
    echo '  ./run.sh "关键词" --core-only --years 2020-2025'
    echo '  ./run.sh --batch examples/queries.json'
    echo ""
    read -p "输入搜索关键词: " QUERY
    if [ -z "$QUERY" ]; then exit 1; fi
    python3 -m cnki_search "$QUERY"
else
    python3 -m cnki_search "$@"
fi

echo ""
echo "================================"
echo "结果保存在 results/ 目录"
