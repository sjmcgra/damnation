FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app.py .
COPY config.py .
COPY dam*.py .
COPY templates templates/
COPY static static/

# Create directory for DAM data
RUN mkdir -p /dam_data/thumbnails

# Expose port
EXPOSE 5500

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV GIT_SSH_COMMAND="ssh -i /root/.ssh/id_ed25519 -o StrictHostKeyChecking=no"

# Setup SSH configuration
RUN mkdir -p /root/.ssh && chmod 700 /root/.ssh

CMD ["python", "-u", "app.py"]