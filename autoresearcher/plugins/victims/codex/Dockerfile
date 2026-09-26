# Codex victim sandbox image.
FROM ar_claude_code_base:latest

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install Node and codex CLI.
USER root
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g @openai/codex

# AgentDyn tools are served in-container by scenario_mcp_stdio.py.
RUN pip install --no-cache-dir "agentdojo @ git+https://github.com/SaFo-Lab/AgentDyn.git"

COPY docker/runner_core.py /app/runner_core.py
COPY docker/runner.py /app/runner.py
COPY docker/scenario_mcp_stdio.py /app/scenario_mcp_stdio.py

RUN chown -R agent:agent /app

USER agent
WORKDIR /work

ENTRYPOINT ["python3", "/app/runner.py"]
