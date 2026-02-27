# Abdullah Tannery Backend API

## Default Admin Login
- Username: `admin`
- Password: `admin123`

## API Endpoints

### Public
- `GET /` — Health check
- `GET /api/articles/search?q=keyword` — Search articles

### Admin (requires token in header)
- `POST /api/admin/login` — Login
- `POST /api/admin/logout` — Logout
- `GET /api/admin/articles` — List all articles
- `POST /api/admin/articles` — Create article
- `PUT /api/admin/articles/{number}` — Update article
- `DELETE /api/admin/articles/{number}` — Delete article
- `POST /api/admin/upload-image` — Upload image

## Deploy on Railway
1. Push this folder to GitHub
2. Connect repo to Railway.app
3. Deploy automatically
