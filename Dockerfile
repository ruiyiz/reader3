# Use Alpine Linux with Python
FROM python:3.11-alpine

# Set working directory
WORKDIR /app

# Install system dependencies required for the Python packages
# - gcc, musl-dev, g++: Build tools for compiling Python packages
# - make: Required for building pymupdf
# - clang-dev: Required for pymupdf build process
# - libffi-dev: Required for some Python packages
# - mupdf-tools: Required for pymupdf
RUN apk add --no-cache \
    gcc \
    musl-dev \
    g++ \
    make \
    clang-dev \
    libffi-dev \
    mupdf-tools \
    freetype-dev \
    jpeg-dev \
    zlib-dev

# Install uv package manager
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml .
COPY reader3.py .
COPY server.py .
COPY templates/ templates/

# Install Python dependencies using uv
RUN uv pip install --system -r pyproject.toml

# Create directory for book data
RUN mkdir -p /app/data

# Expose the port
EXPOSE 8123

# Run the server
CMD ["python", "server.py"]
