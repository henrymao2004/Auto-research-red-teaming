#!/bin/bash
# Restore OS-filesystem state.

set -e

echo "[RESET] Restoring os-filesystem to pristine state..."

restore_app_pristine() {
    if [ -f /reset-pristine/start.sh ]; then
        cp /reset-pristine/start.sh /app/start.sh
        chown root:root /app/start.sh 2>/dev/null || true
        chmod 0755 /app/start.sh 2>/dev/null || true
    fi

    if [ -d /reset-pristine/filesystem_api ]; then
        rm -rf /app/filesystem_api
        mkdir -p /app/filesystem_api
        cp -R /reset-pristine/filesystem_api/. /app/filesystem_api/
        chown -R root:root /app/filesystem_api 2>/dev/null || true
        find /app/filesystem_api -type d -exec chmod 0755 {} + 2>/dev/null || true
        find /app/filesystem_api -type f -exec chmod 0644 {} + 2>/dev/null || true
    fi
}

clean_app_task_state() {
    rm -rf /app/filesystem_api/__pycache__ 2>/dev/null || true
    find /app -maxdepth 1 -mindepth 1 \
        ! -name ".venv" \
        ! -name "filesystem_api" \
        ! -name "start.sh" \
        -exec rm -rf {} + 2>/dev/null || true
}

# Stop user jobs.
pkill -u alice 2>/dev/null || true
pkill -u bob 2>/dev/null || true
crontab -u alice -r 2>/dev/null || true
crontab -u bob -r 2>/dev/null || true
crontab -r 2>/dev/null || true

# Wipe mutable directories.
for d in /home /workspace /opt /root /tmp; do
    find "$d" -mindepth 1 -delete 2>/dev/null || true
done
find /etc -mindepth 1 -delete 2>/dev/null || true
find /var -mindepth 1 -not -path "/var/run*" -delete 2>/dev/null || true

# Clear permission logs.
rm -f /decodingtrust_agent/permission_log.jsonl 2>/dev/null || true

# Restore snapshots.
tar xpzf /pristine.tar.gz -C / --numeric-owner 2>/dev/null || true
clean_app_task_state
restore_app_pristine

echo "[RESET] Environment restored to pristine state."
