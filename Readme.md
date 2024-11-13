# Email Processing Pipeline

This project is designed to process and store email data using MongoDB and PostgreSQL within an Airflow pipeline.

## Prerequisites

- Ensure Docker and Docker Compose are installed on your system.

## Getting Started

1. Clone this repository to your local machine.
2. Navigate to the project directory.

## How to Run

To start the application, simply run:

```bash
docker compose up -d
```

### Troubleshooting

If you encounter issues with permissions, try the following:

1. Create a `.env` file in the project directory.
2. Add the following line to the `.env` file:

   ```bash
   AIRFLOW_UID=50000
   ```

3. Then re-run the application with:

   ```bash
   docker compose up -d --build
   ```

