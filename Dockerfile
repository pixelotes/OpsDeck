FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code into the container at /app
COPY . .

# Make the entrypoint script executable
RUN chmod +x ./entrypoint.sh

# Set the entrypoint for the container
ENTRYPOINT ["./entrypoint.sh"]