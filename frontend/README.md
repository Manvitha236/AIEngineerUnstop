## Frontend (React + Vite) Dashboard

### Dev Setup
```
cd frontend
npm install
npm run dev
```
Visit: http://127.0.0.1:5173

### Features
- Live email list (polls every 8s) with priority/sentiment badges
- Email detail view with AI draft response
- Regenerate & edit/save response actions
- Analytics panel (counts + sentiment chart)

### Environment / Proxy
Proxy rules in `vite.config.ts` forward `/api` and `/health` to backend at `127.0.0.1:8000`.

### Next Improvements
- Add filters (priority/sentiment/status) to list
- Toast notifications for mutations
- Auth & role-based access
- Dark mode / theme
- WebSocket or SSE for real-time updates instead of polling# Frontend placeholder

Will contain dashboard (React) for email listing, analytics, and response editing.
