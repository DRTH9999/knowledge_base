from fastapi import FastAPI
import uvicorn
from fastapi.params import Path




app = FastAPI()

@app.get("/")

def index():
        return {"message": "Hello World"}

# 接收路径参数,
@app.get("/testpath/{id}/{name}/{age}")
def testpath(
        id: int,
        name: str,
        age: int = Path(..., title="年龄", description="请输入年龄", ge=0, le=150)
):
        return {"id": id, "name": name, "age": age}



if __name__ == '__main__':
    uvicorn.run(
        app=app,
        host="0.0.0.0",
        port=8000,
    )