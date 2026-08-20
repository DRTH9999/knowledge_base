import json
import time
import uuid
import uvicorn
from fastapi import FastAPI, Path, Body, BackgroundTasks
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse
from atguigu.query_process.main_graph import MainGraphRunner
from atguigu.tool.mongo_client_tool import get_history_list, clear_history_list
from atguigu.tool.task_utils import update_task_status, TASK_STATUS_PROCESSING, get_task_info, TASK_STATUS_COMPLETED, \
    TASK_STATUS_FAILED, create_queue, put_data, get_data

# 创建 FastAPI 应用
app = FastAPI(
    title="检索模块对应的接口",
    description="检索模块对应的前端接口",
    version="0.1.0"
)

# 配置 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 第一步：健康检查接口
# 前端或部署系统发送：GET /health
# - FastAPI 匹配到 health 函数。
# - 函数直接返回一个字典。
# - FastAPI 自动将字典转换成 JSON。
# - HTTP 状态码为 200。
@app.get("/health")
async def health():
    return {"aa": "bb"}  # 返回什么都可以, 因为前端只是在判断请求是不是成功, response.ok为true ok只要状态是200即可


# 第二步：历史记录查询接口, 查询会话历史
@app.get("/history/{session_id}")  # 接口接收路径参数 session_id
async def get_history(session_id: str = Path(..., description="会话ID")):  # 接收会话 ID
    print(session_id)
    # 查询 MongoDB, 将会话 ID 传给 MongoDB 工具，获取当前会话最近的历史记录
    history_list = get_history_list(session_id)

    # 转换数据库对象
    history_list = [
        {
            "_id": str(item.get("_id")),  # MongoDB ID 序列化
            "role": item.get("role", ""),
            "text": item.get("text", ""),
            "rewritten_query": item.get("rewritten_query", ""),
            "item_names": item.get("item_names", ""),
            "image_urls": item.get("image_urls", []),
            "ts": item.get("ts", ""),
            "session_id": item.get("session_id", "")
        }
        for item in history_list
    ]

    # 按照时间排序
    history_list.sort(key=lambda a: a.get("ts"))

    # 返回前端
    return {"items": history_list}  # 返回数据时, 前端已经完成的情况下, 要看前端页面需要的是什么


# 第三步：清空历史记录
@app.delete("/history/{session_id}")
async def delete_history(session_id: str = Path(..., description="会话ID")):
    clear_history_list(session_id)
    return {"msg": "删除成功"}


# 第四步：书写后台任务调用graph
# queue_dict = {}

def run_main_graph(task_id, original_query, session_id):
    create_queue(task_id)  # 创建队列

    try:
        init_state = {
            "task_id": task_id,
            "original_query": original_query,
            "session_id": session_id,
            # "q":q
        }
        # 更新总状态，放到队列，sse后期就可以从队列当中取出更新的数据状态推送给前端
        update_task_status(task_id, TASK_STATUS_PROCESSING)

        put_data(task_id, event="progress", data=get_task_info(task_id))

        MainGraphRunner.create_and_run(init_state)

        # 更新总状态，放到队列，sse后期就可以从队列当中取出更新的数据状态推送给前端
        update_task_status(task_id, TASK_STATUS_COMPLETED)

        put_data(task_id, event="progress", data=get_task_info(task_id))

    except Exception as e:
        # 更新总状态，放到队列，sse后期就可以从队列当中取出更新的数据状态推送给前端
        update_task_status(task_id, TASK_STATUS_FAILED)

        put_data(task_id, event="error", data=get_task_info(task_id))
        raise e


# 定义查询请求格式
# 这个模型规定 /query 接口必须接收两个字段：query 和 session_id
class QueryParams(BaseModel):
    query: str = Field(..., description="查询内容")
    session_id: str = Field(..., description="会话ID")

# 提交 RAG 查询任务
@app.post("/query")
async def query(background_tasks: BackgroundTasks, query_params: QueryParams = Body(..., description="查询请求体参数")):
    # 创建task_id 后期需要追踪
    task_id = str(uuid.uuid4())
    original_query = query_params.query
    session_id = query_params.session_id

    # 调后台接口任务去执行graph
    background_tasks.add_task(run_main_graph, task_id, original_query, session_id)

    return {
        "task_id": task_id,
        "original_query": original_query,
        "session_id": session_id
    }

# 从队列生成 SSE 数据
def generate_stream(task_id):
    while True:
        item = get_data(task_id)
        time.sleep(0.1)
        yield f"event: {item.get("event")}\n"
        yield f"data: {json.dumps(item.get("data"), ensure_ascii=False)}\n\n"

# 提供 SSE 接口
@app.get("/stream/{task_id}")
async def stream(task_id: str = Path(..., description="任务ID")):

    return StreamingResponse(
        generate_stream(task_id),
        media_type="text/event-stream"
    )


if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8001)

"""
# SSE 是什么
SSE 是浏览器发起一次 HTTP GET 请求，后端保持连接不关闭，有新消息时主动写入响应流


# 总结:
负责的是一个基于 FastAPI、LangGraph、Milvus 和大模型的企业知识库问答服务。 
query_service.py 作为接口层，接收用户问题和会话 ID，为每次查询生成唯一 task_id，并通过后台任务启动 LangGraph 查询流程。
查询图首先结合会话历史进行商品实体识别和问题改写，然后根据商品确认结果决定是否需要澄清；
确认成功后并行执行本地向量检索、HyDE 检索和网络搜索，再通过 RRF 和 Cross-Encoder 重排序构建高质量上下文，
最后调用大模型流式生成答案。
接口层通过任务队列和 SSE 将节点进度、增量答案以及异常状态实时推送给前端。
"""
