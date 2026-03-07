FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
# build-essential is often needed for installing certain python packages
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Create directory for Vector DB persistence
RUN mkdir -p /app/data/chroma && chmod -R 777 /app/data

# Expose port
EXPOSE 8000

# Run with python path set
ENV PYTHONPATH=/app

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]