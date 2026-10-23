"""SQLite job persistence with atomic claims and token hashes, never raw tokens."""
from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import time


class QueueFull(Exception):
    pass


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        with self.connection() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, title TEXT NOT NULL,
                status TEXT NOT NULL, stage TEXT NOT NULL, message TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL, expires REAL NOT NULL,
                manifest TEXT NOT NULL, events TEXT NOT NULL DEFAULT '[]',
                checks TEXT NOT NULL DEFAULT '[]', artifact TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                delete_requested INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 0)""")
        self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        con = sqlite3.connect(str(self.path), timeout=10)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def create(self, manifest, token, *, retention_hours, max_queue, max_stored_jobs):
        now = time.time()
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            count = con.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running') OR active=1").fetchone()[0]
            total = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            if count >= max_queue or total >= max_stored_jobs:
                raise QueueFull()
            event = {"at": now, "stage": "queued", "message": "资料已接收，等待转换"}
            con.execute("INSERT INTO jobs (id,token_hash,title,status,stage,message,created,updated,expires,manifest,events) VALUES (?,?,?,'queued','queued',?,?,?,?,?,?)", (manifest["id"], token_hash(token), manifest["title"], event["message"], now, now, now + retention_hours * 3600, json.dumps(manifest, ensure_ascii=False), json.dumps([event], ensure_ascii=False)))

    def get(self, job_id):
        with self.connection() as con:
            row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def authenticated(self, job_id, token):
        row = self.get(job_id)
        if not row or row["delete_requested"] or row["expires"] <= time.time():
            return None
        return row if hmac.compare_digest(row["token_hash"], token_hash(token)) else None

    def claim(self):
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            if con.execute("SELECT 1 FROM jobs WHERE active=1 LIMIT 1").fetchone():
                return None
            row = con.execute("SELECT * FROM jobs WHERE status='queued' AND delete_requested=0 AND expires>? ORDER BY created LIMIT 1", (time.time(),)).fetchone()
            if not row:
                return None
            con.execute("UPDATE jobs SET status='running',stage='starting',message='开始读取资料',active=1,updated=? WHERE id=?", (time.time(), row["id"]))
        return self.get(row["id"])

    def event(self, job_id, stage, message, checks=None):
        now = time.time()
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT events,cancel_requested,delete_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["cancel_requested"] or row["delete_requested"]:
                return
            events = json.loads(row["events"])
            events.append({"at": now, "stage": stage, "message": message})
            con.execute("UPDATE jobs SET stage=?,message=?,updated=?,events=? WHERE id=?", (stage, message, now, json.dumps(events[-1000:], ensure_ascii=False), job_id))
            if checks is not None:
                con.execute("UPDATE jobs SET checks=? WHERE id=?", (json.dumps(checks, ensure_ascii=False), job_id))

    def finish(self, job_id, status, message, checks=None, artifact=None):
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT cancel_requested,delete_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return
            if row["cancel_requested"] or row["delete_requested"]:
                status, message, artifact = "cancelled", "任务已取消", None
            con.execute("UPDATE jobs SET status=?,stage=?,message=?,checks=?,artifact=?,active=0,updated=? WHERE id=?", (status, status, message, json.dumps(checks or [], ensure_ascii=False), artifact, time.time(), job_id))
        self.event(job_id, status, message)

    def cancel(self, job_id):
        with self.connection() as con:
            con.execute("UPDATE jobs SET cancel_requested=1,status='cancelled',stage='cancelled',message='任务已取消；正在进行的处理将在检查点停止',artifact=NULL,updated=? WHERE id=? AND status IN ('queued','running')", (time.time(), job_id))

    def retry(self, job_id, max_queue):
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["active"] or row["delete_requested"] or row["status"] not in {"failed", "needs_attention", "cancelled", "interrupted"}:
                return False
            if con.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running') OR active=1").fetchone()[0] >= max_queue:
                raise QueueFull()
            con.execute("UPDATE jobs SET status='queued',stage='queued',message='已重新排队，将复用可用检查点',cancel_requested=0,checks='[]',artifact=NULL,updated=? WHERE id=?", (time.time(), job_id))
        self.event(job_id, "queued", "已重新排队，将复用可用检查点")
        return True

    def request_delete(self, job_id):
        with self.connection() as con:
            con.execute("UPDATE jobs SET delete_requested=1,cancel_requested=1,artifact=NULL WHERE id=?", (job_id,))

    def delete(self, job_id):
        with self.connection() as con:
            con.execute("DELETE FROM jobs WHERE id=? AND active=0", (job_id,))

    def cleanup_candidates(self, now):
        with self.connection() as con:
            con.execute("UPDATE jobs SET delete_requested=1,cancel_requested=1,artifact=NULL WHERE expires<=?", (now,))
            return [dict(row) for row in con.execute("SELECT * FROM jobs WHERE delete_requested=1 AND active=0")]

    def recover_interrupted(self):
        with self.connection() as con:
            con.execute("UPDATE jobs SET status=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'interrupted' END,stage='interrupted',message='服务已重启；可重试并复用已保存检查点',active=0,artifact=NULL,updated=? WHERE active=1 OR status='running'", (time.time(),))
