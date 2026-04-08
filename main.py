from fastapi import FastAPI

app = FastAPI(title="License Server")

@app.get("/")
def root():
    return {"ok": True, "message": "license server is running"}

@app.get("/health")
def health():
    return {"status": "healthy"}
