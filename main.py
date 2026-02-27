from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("images", exist_ok=True)
app.mount("/images", StaticFiles(directory="images"), name="images")

security = HTTPBearer(auto_error=False)

# ─── Database ──────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect("tannery.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            article_number  TEXT UNIQUE NOT NULL,
            article_name    TEXT NOT NULL,
            detail          TEXT,
            footwear_type   TEXT,
            color           TEXT,
            size_range      TEXT,
            safety_standard TEXT,
            toe_cap_type    TEXT,
            sole_type       TEXT,
            upper_material  TEXT,
            production_date TEXT,
            status          TEXT DEFAULT 'Active',
            notes           TEXT,
            image_url       TEXT,
            source_type     TEXT DEFAULT 'admin',
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name     TEXT DEFAULT 'Administrator',
            token         TEXT
        )
    """)
    default_hash = hashlib.sha256("admin123".encode()).hexdigest()
    c.execute("""
        INSERT OR IGNORE INTO admins (username, password_hash, full_name)
        VALUES ('admin', ?, 'Administrator')
    """, (default_hash,))
    conn.commit()
    conn.close()

init_db()

# ─── Models ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

# ─── Auth Helper ───────────────────────────────────────────────────────────────

def get_current_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    conn = get_db()
    admin = conn.execute(
        "SELECT * FROM admins WHERE token = ?", (credentials.credentials,)
    ).fetchone()
    conn.close()
    if not admin:
        raise HTTPException(status_code=401, detail="Invalid token")
    return dict(admin)

def row_to_article(row) -> dict:
    """Convert DB row to article dict matching Article.kt model"""
    return {
        "id":              row["id"],
        "article_number":  row["article_number"],
        "article_name":    row["article_name"],
        "detail":          row["detail"],
        "footwear_type":   row["footwear_type"],
        "color":           row["color"],
        "size_range":      row["size_range"],
        "safety_standard": row["safety_standard"],
        "toe_cap_type":    row["toe_cap_type"],
        "sole_type":       row["sole_type"],
        "upper_material":  row["upper_material"],
        "production_date": row["production_date"],
        "status":          row["status"],
        "notes":           row["notes"],
        "image_url":       row["image_url"],
        "source_type":     row["source_type"],
    }

# ─── Health ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "Abdullah Tannery API is running ✅"}

@app.get("/health")
def health():
    return {"status": "ok"}

# ─── Auth ──────────────────────────────────────────────────────────────────────
# App sends: POST admin/login  {username, password}
# App expects: {success, message, token, admin: {username, full_name}}

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
        return {
            "success": False,
            "message": "Invalid username or password",
            "token": None,
            "admin": None
        }

    token = secrets.token_hex(32)
    conn.execute("UPDATE admins SET token = ? WHERE id = ?", (token, admin["id"]))
    conn.commit()
    conn.close()

    return {
        "success": True,
        "message": "Login successful",
        "token":   token,
        "admin": {
            "username":  admin["username"],
            "full_name": admin["full_name"]
        }
    }

@app.post("/admin/logout")
@app.post("/api/admin/logout")
def logout(admin=Depends(get_current_admin)):
    conn = get_db()
    conn.execute("UPDATE admins SET token = NULL WHERE id = ?", (admin["id"],))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Logged out successfully"}

# ─── Article Search (Public) ───────────────────────────────────────────────────
# App sends: GET article/search?query=...
# App expects: {success, found, message, match_type, article}

@app.get("/article/search")
@app.get("/api/articles/search")
def search_articles(query: Optional[str] = None, q: Optional[str] = None):
    search_term = (query or q or "").strip()
    if not search_term:
        return {"success": False, "found": False, "message": "Search query required", "match_type": None, "article": None}

    conn = get_db()
    like = f"%{search_term}%"

    # Try exact match first
    article = conn.execute(
        "SELECT * FROM articles WHERE article_number = ? OR article_name = ?",
        (search_term, search_term)
    ).fetchone()

    match_type = "exact"
    if not article:
        # Try partial match
        article = conn.execute(
            "SELECT * FROM articles WHERE article_number LIKE ? OR article_name LIKE ? ORDER BY article_number LIMIT 1",
            (like, like)
        ).fetchone()
        match_type = "partial"

    conn.close()

    if not article:
        return {
            "success": True,
            "found":   False,
            "message": "No article found",
            "match_type": None,
            "article": None
        }

    return {
        "success":    True,
        "found":      True,
        "message":    None,
        "match_type": match_type,
        "article":    row_to_article(article)
    }

# ─── Single Article ────────────────────────────────────────────────────────────
@app.get("/article/{article_number}")
@app.get("/api/articles/{article_number}")
def get_article(article_number: str):
    conn = get_db()
    article = conn.execute(
        "SELECT * FROM articles WHERE article_number = ?", (article_number,)
    ).fetchone()
    conn.close()
    if not article:
        return {"success": False, "article": None, "message": "Article not found"}
    return {"success": True, "article": row_to_article(article), "message": None}

# ─── Admin: List Articles ──────────────────────────────────────────────────────
# App expects: {success, articles: [...], total, message}

@app.get("/admin/articles")
@app.get("/api/admin/articles")
def list_articles(
    page: int = 1,
    limit: int = 50,
    search: Optional[str] = None,
    admin=Depends(get_current_admin)
):
    conn = get_db()
    if search:
        like = f"%{search}%"
        articles = conn.execute(
            "SELECT * FROM articles WHERE article_number LIKE ? OR article_name LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (like, like, limit, (page - 1) * limit)
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE article_number LIKE ? OR article_name LIKE ?",
            (like, like)
        ).fetchone()[0]
    else:
        articles = conn.execute(
            "SELECT * FROM articles ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, (page - 1) * limit)
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    conn.close()

    return {
        "success":  True,
        "articles": [row_to_article(a) for a in articles],
        "total":    total,
        "message":  None
    }

# ─── Admin: Get Single Article ─────────────────────────────────────────────────
# App sends: GET admin/article/{id}
# App expects: {success, article, message}

@app.get("/admin/article/{article_id}")
def get_admin_article(article_id: int, admin=Depends(get_current_admin)):
    conn = get_db()
    article = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    conn.close()
    if not article:
        return {"success": False, "article": None, "message": "Article not found"}
    return {"success": True, "article": row_to_article(article), "message": None}

# ─── Admin: Create Article (Multipart) ────────────────────────────────────────
# App sends: POST admin/article  multipart form
# App expects: {success, message, article_id}

@app.post("/admin/article")
@app.post("/api/admin/articles")
async def create_article(
    article_number:  str = Form(...),
    article_name:    str = Form(...),
    detail:          Optional[str] = Form(None),
    footwear_type:   Optional[str] = Form(None),
    color:           Optional[str] = Form(None),
    size_range:      Optional[str] = Form(None),
    safety_standard: Optional[str] = Form(None),
    toe_cap_type:    Optional[str] = Form(None),
    sole_type:       Optional[str] = Form(None),
    upper_material:  Optional[str] = Form(None),
    status:          Optional[str] = Form("Active"),
    notes:           Optional[str] = Form(None),
    image:           Optional[UploadFile] = File(None),
    admin=Depends(get_current_admin)
):
    image_url = None
    if image and image.filename:
        ext = image.filename.split(".")[-1]
        filename = f"{secrets.token_hex(16)}.{ext}"
        with open(f"images/{filename}", "wb") as f:
            shutil.copyfileobj(image.file, f)
        image_url = f"images/{filename}"

    conn = get_db()
    try:
        cursor = conn.execute("""
            INSERT INTO articles (article_number, article_name, detail, footwear_type,
                color, size_range, safety_standard, toe_cap_type, sole_type,
                upper_material, status, notes, image_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (article_number, article_name, detail, footwear_type,
              color, size_range, safety_standard, toe_cap_type, sole_type,
              upper_material, status, notes, image_url))
        conn.commit()
        article_id = cursor.lastrowid
        conn.close()
        return {"success": True, "message": "Article created successfully", "article_id": article_id}
    except sqlite3.IntegrityError:
        conn.close()
        return {"success": False, "message": "Article number already exists", "article_id": None}

# ─── Admin: Update Article (Multipart) ────────────────────────────────────────
# App sends: PUT admin/article/{id}  multipart form
# App expects: {success, message, article_id}

@app.put("/admin/article/{article_id}")
@app.put("/api/admin/articles/{article_id}")
async def update_article(
    article_id:      int,
    article_number:  str = Form(...),
    article_name:    str = Form(...),
    detail:          Optional[str] = Form(None),
    footwear_type:   Optional[str] = Form(None),
    color:           Optional[str] = Form(None),
    size_range:      Optional[str] = Form(None),
    safety_standard: Optional[str] = Form(None),
    toe_cap_type:    Optional[str] = Form(None),
    sole_type:       Optional[str] = Form(None),
    upper_material:  Optional[str] = Form(None),
    status:          Optional[str] = Form(None),
    notes:           Optional[str] = Form(None),
    image:           Optional[UploadFile] = File(None),
    admin=Depends(get_current_admin)
):
    conn = get_db()
    existing = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    if not existing:
        conn.close()
        return {"success": False, "message": "Article not found", "article_id": None}

    image_url = existing["image_url"]
    if image and image.filename:
        ext = image.filename.split(".")[-1]
        filename = f"{secrets.token_hex(16)}.{ext}"
        with open(f"images/{filename}", "wb") as f:
            shutil.copyfileobj(image.file, f)
        image_url = f"images/{filename}"

    conn.execute("""
        UPDATE articles SET
            article_number=?, article_name=?, detail=?, footwear_type=?,
            color=?, size_range=?, safety_standard=?, toe_cap_type=?,
            sole_type=?, upper_material=?, status=?, notes=?, image_url=?,
            updated_at=?
        WHERE id=?
    """, (article_number, article_name, detail, footwear_type,
          color, size_range, safety_standard, toe_cap_type,
          sole_type, upper_material, status, notes, image_url,
          datetime.now().isoformat(), article_id))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Article updated successfully", "article_id": article_id}

# ─── Admin: Delete Article ─────────────────────────────────────────────────────
# App sends: DELETE admin/article/{id}
# App expects: {success, message, article_id}

@app.delete("/admin/article/{article_id}")
@app.delete("/api/admin/articles/{article_id}")
def delete_article(article_id: int, admin=Depends(get_current_admin)):
    conn = get_db()
    result = conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
    conn.commit()
    conn.close()
    if result.rowcount == 0:
        return {"success": False, "message": "Article not found", "article_id": None}
    return {"success": True, "message": "Article deleted successfully", "article_id": article_id}

# ─── Image Upload (standalone) ─────────────────────────────────────────────────
@app.post("/admin/upload-image")
@app.post("/api/admin/upload-image")
async def upload_image(file: UploadFile = File(...), admin=Depends(get_current_admin)):
    allowed = ["image/jpeg", "image/png", "image/jpg", "image/webp"]
    if file.content_type not in allowed:
        return {"success": False, "message": "Only JPG/PNG images allowed", "article_id": None}
    ext = file.filename.split(".")[-1]
    filename = f"{secrets.token_hex(16)}.{ext}"
    with open(f"images/{filename}", "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"success": True, "image_url": f"images/{filename}", "message": None, "article_id": None}
