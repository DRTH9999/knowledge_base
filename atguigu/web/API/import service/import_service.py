import shutil
import uuid
from pathlib import Path
import fastapi
import uvicorn
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from starlette.middleware.cors import CORSMiddleware
from datetime import datetime
from atguigu.config.config import MinioConfig
from atguigu.import_process.main_graph import MainGraphRunner
from atguigu.tool.logger import logger
from atguigu.tool.minio_client_tool import get_minio_client
from atguigu.tool.task_utils import add_running_task, add_done_task, get_task_info, update_task_status, \
    TASK_STATUS_PROCESSING, TASK_STATUS_COMPLETED, TASK_STATUS_FAILED


# 服务初始化
app = FastAPI(
    title="掌柜智库导入模块对应的接口服务",
    description="导入模块各个api接口服务",
    version="0.0.1"
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 执行 graph 的后台任务函数
def run_main_graph(task_id: str, local_dir: str, local_file_path: str):
    try:
        # 构造 Graph 初始状态
        init_state = {
            "task_id": task_id,
            "local_dir": local_dir,
            "local_file_path": local_file_path
        }

        # 设置整体任务状态为处理中
        update_task_status(task_id, TASK_STATUS_PROCESSING)

        # 执行 Graph
        MainGraphRunner.create_and_run(init_state)

        # 设置整体任务状态为完成
        update_task_status(task_id, TASK_STATUS_COMPLETED)

    except Exception as e:
        logger.error(f"执行graph异常，task_id={task_id}")
        update_task_status(task_id, TASK_STATUS_FAILED)


# 上传接口
# 接收两个关键对象: - file ：前端上传的文件；- background_tasks ：FastAPI 提供的后台任务调度对象
@app.post("/upload")
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(..., description="上传的文件对象")):

    # 第一步: 生成task_id  uuid, 生成唯一任务标识
    task_id = str(uuid.uuid4())

    # 第二步: 创建上传文件的状态追踪
    # 这一步把 upload_file 放入当前任务的运行节点列表
    add_running_task(task_id, "upload_file")  # 本质就是把upload_file放入正在执行的列表的中

    # 第三步：创建本地日期目录
    # 接收文件并且保准到指定位置
    local_dir = rf"D:\output\{datetime.now().strftime('%Y%m%d')}"

    # 第四步: 接收文件, 拼接本地文件路径
    local_dir_obj = Path(local_dir)
    if not local_dir_obj.exists():
        local_dir_obj.mkdir(parents=True, exist_ok=True)
    local_file_path = str(local_dir_obj / file.filename)

    # 第五步: 保存上传文件
    with open(local_file_path, "wb") as f:
        shutil.copyfileobj(file.file, f, 1024 * 1024)
    logger.info(f"文件上传成功，保存路径为：{local_file_path}")

    # 第六步：备份文件到 MinIO
    minio_client = get_minio_client()
    minio_client.fput_object(
        bucket_name=MinioConfig.minio_bucket_name,
        object_name=f"pdf_file/{datetime.now().strftime('%Y%m%d')}/{task_id}/{file.filename}",
        file_path=local_file_path
    )
    logger.info(
        f"文件上传到minio成功，保存路径为：pdf_file/{datetime.now().strftime('%Y%m%d')}/{task_id}/{file.filename}")

    # 第七步：更新上传文件的状态追踪, 标记上传节点完成
    add_done_task(task_id, "upload_file")  # 本质就是把upload_file从正在执行的列表中移除，添加到已完成列表中

    # 第八步：调用后台任务, 链接graph, 执行整个graph任务
    background_tasks.add_task(run_main_graph, task_id=task_id, local_dir=local_dir, local_file_path=local_file_path)

    # 第九步：返回上传响应, 最主要的就是task_id
    # 这里返回数据主要需要task_id，其余的数据需要与前端页面对比，前端页面需要但是没有的，就需要返回，如果前端需要但是已经存在了
    # 说明前端人员已经完成这个数据的返回, 不需要再返了
    return {"task_id": task_id, "file_size": file.size, "file_name": file.filename}

# 查询任务状态, 接口根据 task_id 查询任务信息
@app.get("/status/{task_id}")
async def get_status(task_id: str = fastapi.Path(..., description="任务ID")):
    return get_task_info(task_id)


if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8000)


"""
# 轮询是什么?
轮询是前端按照固定时间间隔不断发起普通 HTTP 请求, 每一次都是独立的 HTTP 请求和响应。


#主要负责四件事：
    - 接收前端上传的 PDF 或 Markdown 文件。
    - 为本次导入任务生成唯一的 task_id 。
    - 将文件保存到本地，并备份到 MinIO。
    - 通过后台任务启动 RAG 文档处理 Graph，最后提供任务状态查询接口。
    
    
这个 Python 文件是 RAG 项目的知识库导入接口服务，基于 FastAPI 实现。
它通过 /upload 接收前端上传的 PDF 或 Markdown 文件，
首先生成 UUID 形式的 task_id ，然后将文件保存到本地并备份到 MinIO。
上传完成后，接口使用 FastAPI 后台任务异步启动 MainGraphRunner ，避免长时间阻塞 HTTP 请求。

Graph 的初始状态包含 task_id 、本地目录和文件路径。
入口节点根据文件后缀决定是先执行 PDF 转 Markdown，还是直接处理 Markdown。
之后统一经过 Markdown 图片处理、文档切分、主体名称识别、BGE 向量生成和 Milvus 入库。
每个节点通过统一的节点基类记录运行状态、完成状态和耗时。
外层通过 task_id 维护整个任务的 processing、completed 和 failed 状态，前端则通过 /status/{task_id} 查询任务进度。


# task_id 的本质是一次异步导入任务的全链路关联 ID，是用来关联上传记录、后台 Graph、节点状态、日志、MinIO 文件和前端查询的唯一标识。
代表“一次完整的文件导入任务”

"""