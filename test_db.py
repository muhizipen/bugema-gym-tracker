import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), "gym.db")
print("Connecting to:", db_path)

conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER,
        full_name TEXT NOT NULL,
        phone TEXT,
        weight_kg REAL,
        height_cm TEXT,
        session TEXT,
        checkin_time TEXT NOT NULL,
        updated_at TEXT,
        FOREIGN KEY (member_id) REFERENCES members (member_id)
    )
""")
conn.commit()
print("Attendance table verified successfully!")

# Ensure plans
website_plans = [
    ("Student Daily Pass", 0, 2000.0),
    ("Monthly Standard", 1, 30000.0),
    ("Semestrial Subscription", 4, 120000.0),
    ("Annual Unlimited", 12, 360000.0)
]
for name, months, price in website_plans:
    c.execute("SELECT plan_id FROM plans WHERE name = ?", (name,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO plans (name, duration_months, price) VALUES (?, ?, ?)", (name, months, price))
        print("Inserted plan:", name)
    else:
        print("Plan already exists:", name, "ID:", row[0])
conn.commit()

c.execute("SELECT * FROM plans")
print("\nAll Current Plans:")
for row in c.fetchall():
    print(" ", dict(row) if hasattr(row, 'keys') else row)

conn.close()
print("\nDatabase operations completed successfully!")
