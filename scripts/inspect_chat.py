import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

def inspect():
    conn = sqlite3.connect("services/brain/data/vyom-brain.db")
    c = conn.cursor()
    
    print("=== LAST 25 CONVERSATION TURNS ===")
    c.execute("SELECT role, content, created_at FROM conversation_turns ORDER BY rowid DESC LIMIT 25")
    rows = c.fetchall()
    for role, content, created_at in reversed(rows):
        safe_content = content.encode("utf-8", errors="replace").decode("utf-8")
        print(f"[{role.upper()}] ({created_at}):\n{safe_content}\n" + "-"*40)
        
    print("\n=== LAST 10 TASKS ===")
    c.execute("SELECT id, status, goal, created_at FROM tasks ORDER BY rowid DESC LIMIT 10")
    tasks = c.fetchall()
    for tid, status, goal, created_at in reversed(tasks):
        print(f"TASK {tid} [{status}] ({created_at}): {goal}")

    print("\n=== LAST 10 MEMORIES ===")
    c.execute("SELECT id, type, title, summary, created_at FROM memories ORDER BY rowid DESC LIMIT 10")
    mems = c.fetchall()
    for mid, mtype, title, summary, created_at in reversed(mems):
        print(f"MEM {mid} [{mtype}] ({created_at}): {title} -> {summary[:100]}")

if __name__ == "__main__":
    inspect()
