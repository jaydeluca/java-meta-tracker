FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY workflow_state.py .
COPY collect_workflow_metrics.py .

# Create state directory for volume mount
RUN mkdir -p /app/state

CMD ["python", "./collect_workflow_metrics.py"]

