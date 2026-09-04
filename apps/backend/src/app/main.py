from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Single-user local desktop app: the renderer (Vite dev server or a packaged
# file:// origin) is always cross-origin from this sidecar on 127.0.0.1, and
# nothing outside this machine can reach it, so an open CORS policy here
# doesn't widen the app's actual attack surface.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
