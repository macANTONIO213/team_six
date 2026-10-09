#!/bin/bash
# ARGUS EC2 bootstrap (Amazon Linux 2023). Runs once at first boot.
# Installs Python 3.12, creates the argus service user and venv, and starts a
# placeholder Streamlit app on :8501 so hosting can be verified before the
# first real release is pushed with deploy/aws/deploy.ps1 (SSM Run Command).
set -euxo pipefail
exec > >(tee -a /var/log/argus-bootstrap.log) 2>&1

dnf -y install python3.12 python3.12-pip tar gzip || dnf -y install python3.11 python3.11-pip tar gzip
PY="$(command -v python3.12 || command -v python3.11)"

id argus >/dev/null 2>&1 || useradd --system --create-home --home-dir /opt/argus --shell /sbin/nologin argus
mkdir -p /opt/argus/app /opt/argus/data /opt/argus/state/cache /opt/argus/releases

"$PY" -m venv /opt/argus/venv
/opt/argus/venv/bin/pip install --quiet --upgrade pip
/opt/argus/venv/bin/pip install --quiet streamlit

if [ ! -f /opt/argus/app/app.py ]; then
cat > /opt/argus/app/app.py <<'EOF'
import streamlit as st
st.title("ARGUS bootstrap OK")
st.write("EC2 + Streamlit on :8501 is reachable. The real release is deployed via SSM.")
EOF
fi

if [ ! -f /opt/argus/argus.env ]; then
cat > /opt/argus/argus.env <<'EOF'
ARGUS_DATA_DIR=/opt/argus/data
ARGUS_CACHE_DIR=/opt/argus/state/cache
ARGUS_DB_PATH=/opt/argus/state/argus.db
ARGUS_LLM_PROVIDER=bedrock
ARGUS_LLM_MODEL=au.anthropic.claude-sonnet-4-6
ARGUS_LLM_FAST_MODEL=au.anthropic.claude-haiku-4-5-20251001-v1:0
AWS_REGION=ap-southeast-2
AWS_DEFAULT_REGION=ap-southeast-2
EOF
fi

chown -R argus:argus /opt/argus

cat > /etc/systemd/system/argus.service <<'EOF'
[Unit]
Description=ARGUS investigation copilot (Streamlit)
After=network-online.target
Wants=network-online.target

[Service]
User=argus
Group=argus
WorkingDirectory=/opt/argus/app
EnvironmentFile=-/opt/argus/argus.env
ExecStart=/opt/argus/venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true --browser.gatherUsageStats false
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now argus
echo "ARGUS bootstrap complete"
