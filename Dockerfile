FROM python:3.12-slim

# Install system deps for mysqlclient
RUN apt-get update && apt-get install -y \
    default-libmysqlclient-dev \
    build-essential \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Collect static files
RUN python manage.py collectstatic --noinput

EXPOSE 8000

# Default command (overridden by docker-compose for workers)
CMD ["gunicorn", "payroll_engine.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]
