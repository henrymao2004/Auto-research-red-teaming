# dtagent scenario image.
FROM ar_claude_code_base:latest

LABEL scenario=dtagent

# Install bridge dependencies.
USER root
RUN pip3 install --no-cache-dir --timeout 120 --retries 5 \
    fastmcp \
    httpx \
    pyyaml \
    requests \
    ujson \
    numpy \
    faiss-cpu \
    "psycopg[binary]" \
    google-cloud-bigquery
# Backend wiring defaults.
ENV SALESFORCE_BASE_URL=http://host.docker.internal:8080 \
    SALESFORCE_GRANT_TYPE=client_credentials \
    SALESFORCE_CLIENT_ID=17817554-086b-83d1-bf9d-69026221f529 \
    SALESFORCE_CLIENT_SECRET=mcp-secret-123 \
    HOSPITAL_HOST=host.docker.internal \
    HOSPITAL_PORT=12001

USER agent
