import sqlite3
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

def inspect():
    conn = sqlite3.connect(r"C:\Users\GunjanAdmin\AppData\Local\VYOM\brain\data\vyom-brain.db")
    c = conn.cursor()
    c.execute("SELECT id, status, task_json, created_at FROM tasks ORDER BY rowid DESC LIMIT 10")
    for tid, status, raw, created_at in c.fetchall():
        data = json.loads(raw)
        req = data.get("user_request")
        intent = data.get("intent") or data.get("domain")
        assigned_model = data.get("assigned_model")
        plan = data.get("plan", [])
        result = data.get("result", {})
        print(f"TASK {tid} [{status}] ({created_at}):")
        print(f"  User Request: {req}")
        print(f"  Intent/Domain: {intent}, Model: {assigned_model}")
        print(f"  Plan: {plan}")
        print(f"  Result: {str(result)[:300]}")
        print("="*60)

if __name__ == "__main__":
    inspect()
