from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
import pandas as pd
import random
from pymongo import MongoClient
import psycopg2
import email
from email import policy
from email.parser import BytesParser
import base64

# MongoDB and PostgreSQL connection details
MONGO_URI = "mongodb://admin:admin@mongodb:27017/"
POSTGRES_CONN_DETAILS = {
    "dbname": "airflow",
    "user": "airflow",
    "password": "airflow",
    "host": "postgres",
    "port": "5432"
}

# SQL statements for creating tables if they do not exist
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS emails (
    id SERIAL PRIMARY KEY,
    file_path VARCHAR(255),
    message_id VARCHAR(255) UNIQUE,
    date TIMESTAMPTZ,
    sender_email VARCHAR(255),
    subject TEXT,
    content TEXT,
    x_from TEXT,
    x_folder VARCHAR(255),
    x_origin VARCHAR(255),
    x_file_name VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recipients (
    id SERIAL PRIMARY KEY,
    email_id INT REFERENCES emails(id) ON DELETE CASCADE,
    recipient_type VARCHAR(10) CHECK (recipient_type IN ('To', 'Cc', 'Bcc')),
    recipient_email VARCHAR(255)
);


CREATE TABLE IF NOT EXISTS email_metadata (
    id SERIAL PRIMARY KEY,
    email_id INT REFERENCES emails(id) ON DELETE CASCADE,
    key VARCHAR(255),
    value TEXT
);
"""

def create_tables():
    """Create tables in PostgreSQL if they do not exist."""
    conn = psycopg2.connect(**POSTGRES_CONN_DETAILS)
    cur = conn.cursor()
    cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    cur.close()
    conn.close()

def fetch_and_sample_emails():
    # Fetch the CSV data
    url = 'https://raw.githubusercontent.com/tnhanh/data-midterm-17A/refs/heads/main/email.csv'
    df = pd.read_csv(url)
    
    # Randomly sample 200 emails
    sample_df = df.sample(n=200)
    
    # Connect to MongoDB and save the sampled emails
    client = MongoClient(MONGO_URI)
    db = client["emails_db"]
    collection = db["emails"]
    
    # Save each email, checking for duplicates based on 'message_id'
    for _, email_data in sample_df.iterrows():
        email_message = email_data['message']
        parsed_email = {
            "file_path": email_data["file"],
            "message": email_message
        }
        
        # Insert only if this message_id doesn't already exist
        if not collection.find_one({"message": email_message}):
            collection.insert_one(parsed_email)
    
    client.close()
    
def splitEmailAddresses(emailString):
    '''
    The function splits a comma-separated string of email addresses into a unique list.

    Args:
        emailString: A string containing email addresses separated by commas.

    Returns:
        A list of unique email addresses.
    '''
    if emailString:
        addresses = emailString.split(',')
        uniqueAddresses = list(frozenset(map(lambda x: x.strip(), addresses)))
        return uniqueAddresses
    return []

def parse_email(raw_email):
    # Parse the raw email content
    email_message = email.message_from_string(raw_email, policy=policy.default)
    content_parts = []
    metadata = {}

    for part in email_message.walk():
        content_type = part.get_content_type()
        if content_type == 'text/plain':
            # Handle email body
            content_parts.append(part.get_payload())

    # Extract metadata
    for header in email_message.keys():
        metadata[header] = email_message.get(header)

    content = ''.join(content_parts)

    fromAddresses = splitEmailAddresses(email_message.get("From"))
    toAddresses = splitEmailAddresses(email_message.get("To"))
    ccEmail = splitEmailAddresses(email_message.get("Cc"))
    bccEmail = splitEmailAddresses(email_message.get("Bcc"))
    parsed_email = {
        "message_id": email_message.get("Message-ID"),
        "date": email_message.get("Date"),
        "sender_email": fromAddresses[0],
        "to_emails": toAddresses,
        "cc_emails": ccEmail,
        "bcc_emails": bccEmail,
        "subject": email_message.get("Subject"),
        "content": content,
        "metadata": metadata,
        "file_path": "",  
    }

    return parsed_email

def process_and_save_to_postgres():
    # Connect to MongoDB
    client = MongoClient(MONGO_URI)
    db = client["emails_db"]
    emails = db["emails"].find()  

    # Connect to PostgreSQL
    conn = psycopg2.connect(**POSTGRES_CONN_DETAILS)
    cur = conn.cursor()

    for email_doc in emails:
        raw_email = email_doc.get("message")
        file_path = email_doc.get("file_path", "")
        parsed_email = parse_email(raw_email)
        parsed_email["file_path"] = file_path

        # Check for duplicates
        cur.execute("SELECT 1 FROM emails WHERE message_id = %s", (parsed_email["message_id"],))
        if cur.fetchone():
            continue  # Skip if the email already exists in PostgreSQL

        # Insert into emails table
        cur.execute("""
            INSERT INTO emails (file_path, message_id, date, sender_email, subject, content, x_from, x_folder, x_origin, x_file_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """, (
            parsed_email.get("file_path"),
            parsed_email.get("message_id"),
            parsed_email.get("date"),
            parsed_email.get("sender_email"),
            parsed_email.get("subject"),
            parsed_email.get("content"),
            parsed_email["metadata"].get("X-From"),
            parsed_email["metadata"].get("X-Folder"),
            parsed_email["metadata"].get("X-Origin"),
            parsed_email["metadata"].get("X-FileName")
        ))
        
        email_id = cur.fetchone()[0]  

        # Insert recipients into the recipients table
        for recipient_type, recipient_field in [("To", "to_emails"), ("Cc", "cc_emails"), ("Bcc", "bcc_emails")]:
            if parsed_email.get(recipient_field):
                recipients = parsed_email[recipient_field]
                for recipient in recipients:
                    cur.execute("""
                        INSERT INTO recipients (email_id, recipient_type, recipient_email)
                        VALUES (%s, %s, %s);
                    """, (email_id, recipient_type, recipient.strip()))

        # Insert metadata
        for key, value in parsed_email["metadata"].items():
            cur.execute("""
                INSERT INTO email_metadata (email_id, key, value)
                VALUES (%s, %s, %s);
            """, (email_id, key, value))

    # Commit transaction and close connections
    conn.commit()
    cur.close()
    conn.close()
    client.close()

# Set up the DAG
default_args = {
    'owner': 'airflow',
    'start_date': datetime(2024, 11, 12),
    'retries': 1,
}

with DAG(
    'email_pipeline_dag',
    default_args=default_args,
    schedule_interval='*/5 * * * *',  # Every 5 minutes
    catchup=False
) as dag:
    
    create_tables_task = PythonOperator(
        task_id='create_tables',
        python_callable=create_tables
    )

    fetch_and_save_emails_task = PythonOperator(
        task_id='fetch_and_save_to_mongo',
        python_callable=fetch_and_sample_emails
    )

    process_and_save_task = PythonOperator(
        task_id='process_and_save_to_postgres',
        python_callable=process_and_save_to_postgres
    )

    create_tables_task >> fetch_and_save_emails_task >> process_and_save_task
