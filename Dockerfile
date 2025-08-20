# Use official Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Expose app port (update if your app listens on a different port)
EXPOSE 5300

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5300"]

