# ============================================
# FINSIGHT AI BACKEND - DOCKERFILE
# ============================================

FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set permissions for startup script
RUN chmod +x start.sh

# Create non-root user for security
RUN adduser --disabled-password --gecos '' finsight && \
    chown -R finsight:finsight /app
USER finsight

# Expose port (Railway will override with $PORT)
EXPOSE 8000

# Start the application using startup script
# Note: Railway's railway.toml startCommand will override this CMD
CMD ["./start.sh"]
