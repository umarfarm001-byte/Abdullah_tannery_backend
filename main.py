from fastapi import FastAPI, HTTPException, Depends, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sqlite3
import hashlib
import secrets
import os
import shutil
from datetime import datetime

app = FastAPI(title="Abdullah Tannery API")

# CORS - allow Android app to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for images
os.makedirs("images", exist_ok=True)
app.mount("/images", StaticFiles(directory="images"), name="images")

security = HTTPBearer(auto_error=False)

# ─── Database Setup ────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect("tannery.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_number TEXT UNIQUE NOT NULL,
            article_name TEXT NOT NULL,
            detail TEXT,
            footwear_type TEXT,
            color TEXT,
            size_range TEXT,
            safety_standard TEXT,
            toe_cap_type TEXT,
            sole_type TEXT,
            upper_material TEXT,
            production_date TEXT,
            status TEXT DEFAULT 'Active',
            notes TEXT,
            image_url TEXT,
            source_type TEXT DEFAULT 'admin',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            token TEXT
        )
    """)

    default_hash = hashlib.sha256("admin123".encode()).hexdigest()
    c.execute("""
        INSERT OR IGNORE INTO admins (username, password_hash)
        VALUES ('admin', ?)
    """, (default_hash,))

    conn.commit()
    conn.close()

init_db()

# ─── Models ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class ArticleCreate(BaseModel):
    article_number: str
    article_name: str
    detail: Optional[str] = None
    footwear_type: Optional[str] = None
    color: Optional[str] = None
    size_range: Optional[str] = None
    safety_standard: Optional[str] = None
    toe_cap_type: Optional[str] = None
    sole_type: Optional[str] = None
    upper_material: Optional[str] = None
    production_date: Optional[str] = None
    status: Optional[str] = "Active"
    notes: Optional[str] = None
    image_url: Optional[str] = None
    source_type: Optional[str] = "admin"

class ArticleUpdate(BaseModel):
    article_name: Optional[str] = None
    detail: Optional[str] = None
    footwear_type: Optional[str] = None
    color: Optional[str] = None
    size_range: Optional[str] = None
    safety_standard: Optional[str] = None
    toe_cap_type: Optional[str] = None
    sole_type: Optional[str] = None
    upper_material: Optional[str] = None
    production_date: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    image_url: Optional[str] = None

# ─── Auth Helper ───────────────────────────────────────────────────────────────

def get_current_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = credentials.credentials
    conn = get_db()
    admin = conn.execute(
        "SELECT * FROM admins WHERE token = ?", (token,)
    ).fetchone()
    conn.close()
    if not admin:
        raise HTTPException(status_code=401, detail="Invalid token")
    return dict(admin)

# ─── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "Abdullah Tannery API is running ✅"}

@app.get("/health")
def health():
    return {"status": "ok"}

# ── Auth ──────────────────────────────────────────────────────────────────────
# Matches app: AdminApiService calls /admin/login
@app.post("/admin/login")
@app.post("/api/admin/login")
def login(req: LoginRequest):
    conn = get_db()
    password_hash = hashlib.sha256(req.password.encode()).hexdigest()
    admin = conn.execute(
        "SELECT * FROM admins WHERE username = ? AND password_hash = ?",
        (req.username, password_hash)
    ).fetchone()

    if not admin:
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = secrets.token_hex(32)
    conn.execute(
        "UPDATE admins SET token = ? WHERE id = ?",
        (token, admin["id"])
    )
    conn.commit()
    conn.close()
    return {"token": token, "username": req.username}

@app.post("/admin/logout")
@app.post("/api/admin/logout")
def logout(admin=Depends(get_current_admin)):
    conn = get_db()
    conn.execute("UPDATE admins SET token = NULL WHERE id = ?", (admin["id"],))
    conn.commit()
    conn.close()
    return {"message": "Logged out successfully"}

# ── Article Search ─────────────────────────────────────────────────────────────
# Matches app: TanneryApiService calls /article/search?query=...
@app.get("/article/search")
@app.get("/api/articles/search")
def search_articles(query: Optional[str] = None, q: Optional[str] = None):
    # Accept both ?query= (from app) and ?q= (original)
    search_term = query or q
    if not search_term or len(search_term.strip()) < 1:
        raise HTTPException(status_code=400, detail="Search query required")

    conn = get_db()
    like = f"%{search_term.strip()}%"
    articles = conn.execute("""
        SELECT * FROM articles
        WHERE article_number LIKE ? OR article_name LIKE ?
        ORDER BY article_number
        LIMIT 20
    """, (like, like)).fetchall()
    conn.close()

    if not articles:
        raise HTTPException(status_code=404, detail="No articles found")

    results = [dict(a) for a in articles]

    # Return in format app expects: {found: true, article: {...}}
    return {
        "found": True,
        "article": results[0],
        "total": len(results)
    }

@app.get("/article/{article_number}")
@app.get("/api/articles/{article_number}")
def get_article(article_number: str):
    conn = get_db()
    article = conn.execute(
        "SELECT * FROM articles WHERE article_number = ?",
        (article_number,)
    ).fetchone()
    conn.close()

    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    return dict(article)

# ── Admin Article Management ──────────────────────────────────────────────────

@app.get("/admin/articles")
@app.get("/api/admin/articles")
def list_articles(admin=Depends(get_current_admin)):
    conn = get_db()
    articles = conn.execute(
        "SELECT * FROM articles ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(a) for a in articles]

@app.post("/admin/articles")
@app.post("/api/admin/articles")
def create_article(article: ArticleCreate, admin=Depends(get_current_admin)):
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO articles (
                article_number, article_name, detail, footwear_type, color,
                size_range, safety_standard, toe_cap_type, sole_type,
                upper_material, production_date, status, notes, image_url, source_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            article.article_number, article.article_name, article.detail,
            article.footwear_type, article.color, article.size_range,
            article.safety_standard, article.toe_cap_type, article.sole_type,
            article.upper_material, article.production_date, article.status,
            article.notes, article.image_url, article.source_type
        ))
        conn.commit()
        conn.close()
        return {"message": "Article created successfully", "success": True}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Article number already exists")

@app.put("/admin/articles/{article_number}")
@app.put("/api/admin/articles/{article_number}")
def update_article(article_number: str, article: ArticleUpdate, admin=Depends(get_current_admin)):
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM articles WHERE article_number = ?", (article_number,)
    ).fetchone()

    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Article not found")

    updates = {k: v for k, v in article.dict().items() if v is not None}
    updates["updated_at"] = datetime.now().isoformat()

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [article_number]

    conn.execute(
        f"UPDATE articles SET {set_clause} WHERE article_number = ?", values
    )
    conn.commit()
    conn.close()
    return {"message": "Article updated successfully", "success": True}

@app.delete("/admin/articles/{article_number}")
@app.delete("/api/admin/articles/{article_number}")
def delete_article(article_number: str, admin=Depends(get_current_admin)):
    conn = get_db()
    result = conn.execute(
        "DELETE FROM articles WHERE article_number = ?", (article_number,)
    )
    conn.commit()
    conn.close()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Article not found")

    return {"message": "Article deleted successfully", "success": True}

# ── Image Upload ──────────────────────────────────────────────────────────────

@app.post("/admin/upload-image")
@app.post("/api/admin/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    admin=Depends(get_current_admin)
):
    allowed = ["image/jpeg", "image/png", "image/jpg", "image/webp"]
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Only JPG/PNG images allowed")

    ext = file.filename.split(".")[-1]
    filename = f"{secrets.token_hex(16)}.{ext}"
    filepath = f"images/{filename}"

    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)

    return {"image_url": f"images/{filename}", "success": True}
