# AgentDyn scenario image. AgentDyn is a fork of AgentDojo and is still
# imported as ``agentdojo``; tools_mcp.py uses it to hydrate the suite
# environment and enumerate its functions.
FROM ar_claude_code_base:latest

RUN pip install --no-cache-dir "agentdojo @ git+https://github.com/SaFo-Lab/AgentDyn.git"

LABEL scenario=agentdyn
