NexusBoard - Module 1 (Project Foundation & User Authentication)
---------------------------------------------------------------

What's included:
- app.py                : Flask application with routes for register/login/dashboard/logout
- templates/            : HTML templates (login.html, register.html, dashboard.html)
- static/style.css      : basic styling for the pages
- create_tables.sql     : SQL script to create required tables
- requirements.txt      : Python dependencies

IMPORTANT: This module uses PostgreSQL (as per the project synopsis).
Please create a PostgreSQL database and set connection credentials before running.

Steps to run (Linux / macOS / Windows with WSL or appropriate shell):
1. Install PostgreSQL and create a database named 'nexusboard' (or choose another name).
2. Run the SQL script to create tables:
   - psql -U postgres -d nexusboard -f create_tables.sql
   (or use pgAdmin to run the script)
3. (Recommended) Create a virtual environment and activate it:
   - python3 -m venv venv
   - source venv/bin/activate   (Linux/macOS)
   - venv\Scripts\activate    (Windows)
4. Install dependencies:
   - pip install -r requirements.txt
5. Configure DB credentials (optional):
   By default app.py reads DB connection info from environment variables:
     DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT
   You can export them in your shell or edit the values in app.py directly.
6. Run the app:
   - python app.py
7. Open browser at: http://127.0.0.1:5000

Default connection settings in app.py (change as needed):
  host=localhost
  database=nexusboard
  user=postgres
  password=12345
  port=5432
