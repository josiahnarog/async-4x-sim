import uvicorn

if __name__ == "__main__":
    print("Tactical UI: http://127.0.0.1:8001/tactical/")
    uvicorn.run("app:app", host="127.0.0.1", port=8001, reload=True)
