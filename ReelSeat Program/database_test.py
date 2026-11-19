import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()

cur.execute("""
    CREATE TABLE IF NOT EXISTS env_test (
        id SERIAL PRIMARY KEY,
        member_name TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
""")

cur.execute(
    "INSERT INTO env_test (member_name, status) VALUES (%s, %s) RETURNING id;",
    ("Son Nguyen", "DB connection test passed")
)
inserted_id = cur.fetchone()[0]
conn.commit()
print("Saved ID:", inserted_id)

cur.execute("SELECT id, member_name, status, created_at FROM env_test ORDER BY id;")
for row in cur.fetchall():
    print("Retrieved:", row)

cur.close()
conn.close()