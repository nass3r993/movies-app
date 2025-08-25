# Use the official Python base image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy all files and folders from the current directory to /app in the container
COPY . .

# Create the /instance folder in the container root
RUN mkdir -p /instance

# Install Python dependencies from requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Expose port 5001 to the host
EXPOSE 5001

# Run the app.py script
CMD ["python", "app/app.py"]
