"""
ChronoSync - Root Application Entrypoint for Vercel & Production
"""
import sys
import os

# Ensure the root directory is at the top of sys.path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    from backend.app.main import app
except Exception as e:
    import traceback
    err_trace = traceback.format_exc()
    print("FATAL CHRONOSYNC STARTUP ERROR:\n", err_trace)
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    app = FastAPI(title="ChronoSync Diagnostic Engine")
    @app.get("/{full_path:path}", response_class=HTMLResponse)
    def catch_all(full_path: str = ""):
        return HTMLResponse(
            content=f"""<!DOCTYPE html>
            <html>
            <head><title>ChronoSync - Initialization Diagnostics</title></head>
            <body style="font-family:monospace; background:#0f1411; color:#fff; padding:32px; line-height:1.6;">
              <h2 style="color:#e06c75; margin-bottom:12px;">ChronoSync Cold-Start Exception</h2>
              <p style="color:#abb2bf;">The Python runtime encountered an uncaught exception during startup:</p>
              <pre style="background:#1b221e; border:1px solid #384b30; color:#98c379; padding:20px; border-radius:8px; overflow:auto;">{err_trace}</pre>
            </body>
            </html>""",
            status_code=500
        )
