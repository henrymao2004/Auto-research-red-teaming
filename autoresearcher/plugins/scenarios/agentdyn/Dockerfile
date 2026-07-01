# AgentDyn scenario image. AgentDyn is a fork of AgentDojo, so the
# upstream package is still imported as ``agentdojo``; tools_mcp.py
# imports it at runtime to hydrate the per-suite TaskEnvironment and to
# enumerate the suite's Function list. The base image already provides
# Python + claude-agent-sdk + the in-container runner; we only need to
# layer the upstream AgentDyn fork on top.
FROM ar_claude_code_base:latest

# Pin >=0.1.35 (same release the dataset under clean/ was extracted
# from — see scenario.yaml provenance). The package is pure-Python so
# this is a fast install with no system-deps fan-out.
RUN pip install --no-cache-dir "agentdojo @ git+https://github.com/SaFo-Lab/AgentDyn.git"

LABEL scenario=agentdyn
