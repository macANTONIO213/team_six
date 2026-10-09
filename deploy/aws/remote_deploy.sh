#!/bin/bash
# Runs ON the EC2 instance (via SSM Run Command) from the extracted release folder.
#   remote_deploy.sh <bucket> <release-folder> <precompute: auto|always|never>
set -euo pipefail
BUCKET="$1"; NEW="$2"; MODE="${3:-auto}"
cd "$NEW"
echo "== sync REPH data (private bucket, same AWS account)"
aws s3 sync "s3://$BUCKET/data/" /opt/argus/data/ --only-show-errors
echo "== install dependencies"
/opt/argus/venv/bin/pip install --quiet --upgrade pip
/opt/argus/venv/bin/pip install --quiet -r requirements.txt
set -a; . /opt/argus/argus.env; set +a
if [ "$MODE" = "always" ] || { [ "$MODE" = "auto" ] && [ ! -f /opt/argus/state/cache/triage_model.joblib ]; }; then
  echo "== precompute (identity graph, ownership, features, model)"
  /opt/argus/venv/bin/python -m core.precompute
fi
echo "== switch release"
rm -rf /opt/argus/app.old
[ -d /opt/argus/app ] && mv /opt/argus/app /opt/argus/app.old
mv "$NEW" /opt/argus/app
chown -R argus:argus /opt/argus
systemctl restart argus
for i in $(seq 1 30); do
  if curl -sf http://localhost:8501/_stcore/health >/dev/null; then echo "== healthy after ${i}s"; break; fi
  sleep 1
done
cd /opt/argus/app && sudo -u argus env $(grep -v '^#' /opt/argus/argus.env | xargs) /opt/argus/venv/bin/python -m scripts.smoke_test | tail -n 20
echo "== deployed $(date -u +%FT%TZ)"
