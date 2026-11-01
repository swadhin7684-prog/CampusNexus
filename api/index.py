import sys
import os

# Put root directory in sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    from backend.app.main import app
except Exception as e:
    import traceback
    err_trace = traceback.format_exc()
    print("FATAL ERROR LOADING BACKEND:", err_trace)
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    app = FastAPI(title="ChronoSync Error Handler")
    @app.get("/{full_path:path}", response_class=HTMLResponse)
    def catch_all(full_path: str = ""):
        return HTMLResponse(
            content=f"""<html><body style="font-family:sans-serif; background:#121212; color:#fff; padding:40px;">
            <h2 style="color:#ff6b6b;">ChronoSync Backend Initialization Error</h2>
            <p>The Python environment encountered an exception during startup:</p>
            <pre style="background:#222; padding:20px; border-radius:8px; overflow:auto; color:#4ade80;">{err_trace}</pre>
            </body></html>""",
            status_code=500
        )
