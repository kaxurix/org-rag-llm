FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY static/ ./static/
COPY *.pdf ./datasets/
RUN useradd --create-home archive && mkdir -p /app/data && chown -R archive:archive /app
USER archive
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
