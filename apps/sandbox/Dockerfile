# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Install git, npm, pnpm, yarn, bun, ps, curl, and other development tools
RUN apt-get update && \
    apt-get install -y git npm procps curl wget vim build-essential && \
    npm install -g pnpm yarn && \
    curl -fsSL https://bun.sh/install | bash && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install --no-cache-dir poetry

# Copy the pyproject.toml and poetry.lock files to the working directory
COPY pyproject.toml poetry.lock ./

# Install dependencies using Poetry
RUN poetry install --no-root

# Copy the current directory contents into the container at /app
COPY sandbox/ ./sandbox/

# Make port 80 available to the world outside this container
EXPOSE 80
EXPOSE 0-65535

# Define environment variable for Python
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["poetry", "run", "uvicorn", "sandbox.main:app", "--host", "0.0.0.0", "--port", "80"]
