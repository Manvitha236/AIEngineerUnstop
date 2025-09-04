"""Convenience launcher so you can just: python run_server.py
Resolves import path confusion (ModuleNotFoundError: app)
"""
from backend.app.main import app  # type: ignore

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)
