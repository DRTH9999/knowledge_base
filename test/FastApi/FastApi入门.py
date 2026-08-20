from fastapi import FastAPI
import uvicorn

app = FastAPI(
    title="FastAPI 入门",
    description="FastAPI 测试后端服务 API 接口服务器",
    version="0.1.0"
)


@app.get("/")
def index():
    return {"message": "test"}


if __name__ == '__main__':
    uvicorn.run(
        app=app,
        host="0.0.0.0",
        port=8000,
    )
