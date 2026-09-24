#!/bin/sh
# api 容器启动脚本：先修数据卷属主（named volume 首启为 root），再降级到 joker 用户跑 uvicorn
set -e
mkdir -p /data/storage /data/obsidian-vault
chown -R 1000:1000 /data
exec gosu 1000 uvicorn app.main:app --host 0.0.0.0 --port 8001
