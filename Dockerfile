FROM apache/airflow:2.10.2

# Copy requirements.txt to install dependencies
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt
