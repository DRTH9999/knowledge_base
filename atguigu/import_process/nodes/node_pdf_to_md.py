# atguigu/import_process/nodes/node_pdf_to_md.py

import requests
import time
import requests
import zipfile
import shutil
from pathlib import Path
from atguigu.config.config import MineruConfig
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_format_tool import json_format
from atguigu.tool.logger import logger


class NodePDFToMD(NodeBase):
    """
    PDF 转 Markdown 节点：PDF结构化解析
    """

    name = "node_pdf_to_md"

    def check_path(self, state):
        pdf_path = state.get("pdf_path", '')

        # 校验 PDF 路径是否提供
        if not pdf_path:
            logger.error("未提供PDF路径")
            raise ValueError("未提供PDF路径")

        # 校验 PDF 文件是否存在
        pdf_path_obj = Path(pdf_path)
        if not pdf_path_obj.exists():
            logger.error("PDF文件不存在")
            raise FileNotFoundError(f"PDF文件不存在：{pdf_path}")

        # 校验输出目录是否存在, 如果输出目录不存在, 则自动创建.
        local_dir = state.get("local_dir", '')
        if not local_dir:
            logger.error("未提供输出目录路径")
            raise ValueError("未提供输出目录路径")

        local_dir_obj = Path(local_dir)
        if not local_dir_obj.exists():
            local_dir_obj.mkdir(parents=True, exist_ok=True)


        # pdf_path: 原始 PDF 路径字符串; local_dir_obj: 输出目录的 Path 路径对象; pdf_path_obj: PDF 文件的 Path 路径对象
        return pdf_path, local_dir_obj, pdf_path_obj

    def upload_pdf(self, pdf_path, pdf_path_obj):
        import requests
        token = MineruConfig.mineru_token
        url = "https://mineru.net/api/v4/file-urls/batch"
        header = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        data = {
            "files": [
                {"name": f"{pdf_path_obj.name}", "data_id": "abcd"}
            ],
            "model_version": "vlm"
        }
        file_path = [f"{pdf_path}"]

        # 向 MinerU 申请文件上传地址, 并分别校验 HTTP 状态和业务状态
        response = requests.post(url, headers=header, json=data)
        if response.status_code != 200:
            logger.error("上传PDF文件请求失败")
            raise Exception(f"上传PDF文件请求失败：{pdf_path}")

        logger.info("上传PDF文件请求成功")

        # 判断业务响应是否成功, 如果成功则获取 batch_id
        result = response.json()
        if result["code"] != 0:
            logger.error("上传PDF文件请求数据失败")
            raise Exception("上传PDF文件请求数据失败")
        logger.info("上传PDF文件请求数据成功")

        # 提取批次 ID 和预签名上传地址
        # batch_id 本次解析批次的唯一 ID, file_urls 用于上传文件的临时 URL
        batch_id = result["data"]["batch_id"]
        urls = result["data"]["file_urls"]

        for i in range(0, len(urls)):
            # 使用 PUT 上传 PDF 内容. 申请上传地址的请求和真正上传文件的请求是两次不同的 HTTP 操作
            with open(file_path[i], 'rb') as f:
                res_upload = requests.put(urls[i], data=f)
                if res_upload.status_code == 200:
                    logger.info(f"{urls[i]}上传成功")
                else:
                    logger.error(f"{urls[i]}上传失败")
        return batch_id

    def get_md_zip_url(self, batch_id):

        token = MineruConfig.mineru_token
        batch_id = batch_id

        # 需要根据 batch_id 查询任务状态
        url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
        header = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        # 设置超时时间
        '''
        直接计算从开始轮询到当前的总耗时，会包含：
        - HTTP 请求时间
        - MinerU 处理等待时间
        - time.sleep(5) 的轮询间隔
        '''
        total_time = 300
        use_time = 0

        while True:
            start_time = time.time()
            try:
                res = requests.get(url, headers=header)
                if res.status_code != 200:  # 判断 HTTP 是否成功
                    logger.error("获取PDF文件处理结果请求失败")
                    raise Exception("获取PDF文件处理结果请求失败")

                result = res.json()
                if result["code"] != 0:  # 判断业务状态是否成功
                    logger.error("获取PDF文件处理结果请求数据失败")
                    raise Exception("获取PDF文件处理结果请求数据失败")

                # 读取文档解析状态
                data = result["data"]["extract_result"][0]
                if data["state"] != "done":
                    logger.info("PDF文件处理中，等待重试")
                    raise Exception("PDF文件处理中，等待重试")

                # 解析完成后返回压缩包地址
                # MinerU 返回的是一个包含解析结果的 ZIP 下载地址，不是直接返回 Markdown 内容
                zip_url = data["full_zip_url"]
                return zip_url

            except Exception as e:
                logger.error(f"PDF文件处理异常，等待重试{e}")
                end_time = time.time()
                use_time += end_time - start_time
                if use_time > total_time:
                    raise Exception(f"PDF文件处理超时,请稍后再试")
                continue

    # 下载、解压并读取 Markdown 文件内容
    def download_zip_handler(self, md_zip_url, local_dir_obj, pdf_path_obj):

        # 第一步：下载 ZIP 文件
        md_zip_res = requests.get(md_zip_url)
        if md_zip_res.status_code != 200:
            logger.error("下载PDF文件处理结果zip压缩包请求失败")
            raise Exception(f"下载PDF文件处理结果zip压缩包请求失败")

        # 第二步：读取二进制内容
        # ZIP 文件是二进制数据，所以不能用文本模式处理。
        md_zip_content = md_zip_res.content

        # 第三步：构造 ZIP 保存路径
        md_zip_path_obj = local_dir_obj / f"{pdf_path_obj.stem}.zip"

        # 将响应内容写入本地
        # 读写文件是二进制, 不需要加encoding="utf-8".
        with open(md_zip_path_obj, 'wb') as f:
            f.write(md_zip_content)  # 将内存中的 ZIP 二进制内容持久化到磁盘

        # 第五步：构造解压目录, 解压zip文件
        unzip_file_content = zipfile.ZipFile(md_zip_path_obj)

        # 解压地址, 构造解压的目的地路径
        unzip_file_path_obj = local_dir_obj / f"{pdf_path_obj.stem}"

        # 判断解压目录是否存在. 如果存在则删除, 然后再创建
        if unzip_file_path_obj.exists():
            shutil.rmtree(unzip_file_path_obj)
        unzip_file_path_obj.mkdir(parents=True, exist_ok=True)

        # 第六步：解压文件
        # 落盘, 真正把解压的内容, 放到指定目录
        unzip_file_content.extractall(unzip_file_path_obj)

        # 第七步：重命名 Markdown 文件
        # 解压完成后, 原本的md文件叫 full.md, 需要重命名
        origin_md_path_obj = unzip_file_path_obj / "full.md"
        new_md_path_obj = origin_md_path_obj.with_name(f"{pdf_path_obj.stem}.md")  # 在内存当中改了，我们还得落盘
        origin_md_path_obj.rename(new_md_path_obj)

        # 读取 Markdown 内容
        # 读取Markdown文件内容 存储state
        with open(new_md_path_obj, 'r', encoding="utf-8") as f:
            md_content = f.read()

        # - Markdown 全文内容；- Markdown 文件路径。
        return md_content, new_md_path_obj

    def process(self, state: ImportGraphState):

        # 第一大步: 校验pdf路径的存在
        pdf_path, local_dir_obj, pdf_path_obj = self.check_path(state)

        # 第二大步: 上传 pdf 到 MinerU , 获取 batch_id
        batch_id = self.upload_pdf(pdf_path, pdf_path_obj)

        # 第三大步: 等待 MinerU 处理完成, 需要轮询给 MinerU 发请求, 获取一个压缩包zip的url
        md_zip_url = self.get_md_zip_url(batch_id)

        # 第四大步: 下载zip压缩文件, 解压, 重命名, 把文件的内容读取保存state
        md_content, new_md_path_obj = self.download_zip_handler(md_zip_url, local_dir_obj, pdf_path_obj)

        return {
            "md_path": str(new_md_path_obj),  # new_md_path_obj 是 Path 对象, 必须先转换为字符串, 才能被 json.dumps() 正常序列化
            "md_content": md_content
        }


if __name__ == '__main__':
    node = NodePDFToMD()
    init_state = {
        "pdf_path": r"E:\260515\knowledge_base\doc\hak180产品安全手册.pdf",
        "local_dir": r"E:\260515\knowledge_base\outputs"
    }
    result = node(init_state)
    logger.info(json_format(result))


"""
# 这个文件实现了 RAG 文档导入流程中的 PDF 转 Markdown 节点。
这个节点接收入口节点传递的 pdf_path 和输出目录 local_dir ，
首先校验路径，然后调用 MinerU 的批量上传接口, 申请预签名 URL，再通过 PUT 上传 PDF 文件。
由于 MinerU 采用异步解析模式，上传完成后会返回 batch_id ，节点根据这个 ID 轮询查询解析状态，直到任务完成并获得结果 ZIP 的下载地址。
随后节点下载 ZIP 文件，保存到本地并解压，从中找到 full.md ，将其重命名为和原 PDF 同名的 Markdown 文件，读取 Markdown 内容，
最后通过 md_path 和 md_content 返回给下游的图片处理节点和文档切片节点。


# 概述: 
  接收上游节点识别出的 PDF 文件路径，将 PDF 上传到 MinerU 文档解析服务，轮询等待解析完成，下载解析结果压缩包，
  解压并读取 Markdown 文件，最后把 Markdown 路径和内容传给下游节点。
  
# 任务描述: 
RAG 系统通常不能直接对 PDF 做高质量的向量检索。需要先把 PDF 中的：- 标题 - 段落 - 表格 - 图片 - 图片说明 - 文档层级关系
转换成结构化的 Markdown，再进行图片处理、文本切片、向量化和入库。
因此，这个节点实际上是“文档导入链路”的格式转换和数据准备节点。


# 上游节点是 node_entry.py
入口节点会接收：
    {
        "local_file_path": ..."
    }
    
其中：
- pdf_path ：PDF 原始文件路径。
- local_dir ：解析结果的输出目录。


# check_path(): 
  校验PDF路径是否存在, 以及输出目录是否存在, 如果不存在则创建, 返回PDF路径, 输出目录路径, PDF路径对象
  
  upload_pdf() :
  申请上传地址并上传 PDF 文件, 返回 batch_id, 表示上传成功
  - MinerU 的上传流程不是直接把 PDF 作为普通表单上传，而是分成两个阶段：申请上传地址并上传 PDF 文件，然后轮询等待解析完成，最后下载解析结果。
  第一阶段：申请文件上传地址
  第二阶段：判断 HTTP 请求是否成功
  第三阶段：判断业务响应是否成功
  第四阶段：提取批次 ID 和预签名上传地址
      MinerU 返回：
    - batch_id ：本次解析批次的唯一 ID。
    - file_urls ：用于上传文件的临时 URL。
  第五阶段：使用 PUT 上传 PDF 内容
  
  get_md_zip_url() : 
  轮询 MinerU 解析状态, 等待解析完成, 返回 zip 压缩包的下载地址
  - 上传完成后，MinerU 不会立刻返回 Markdown，而是异步解析 PDF 文件并生成 Markdown 文件。因此需要根据 batch_id 查询任务状态：
  - MinerU 返回的是一个包含解析结果的 ZIP 下载地址，不是直接返回 Markdown 内容。
  
  download_zip_handler() : 
  - 下载 zip 压缩文件, 解压, 重命名, 读取 Markdown 文件内容，返回 Markdown 内容和路径
  - 
  第一步：下载 ZIP 文件
  第二步：读取二进制内容
  第三步：构造 ZIP 保存路径
  第四步：将响应内容写入本地
  第五步：构造解压目录 
  第六步：解压 ZIP 文件
  第七步：重命名 Markdown 文件
  第八步：读取 Markdown 文件内容
  第九步：返回 Markdown 文件内容和路径
"""
