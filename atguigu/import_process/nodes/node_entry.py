# atguigu/import_process/nodes/node_entry.py
from pathlib import Path
from atguigu.tool.logger import logger
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState


class NodeEntry(NodeBase):
    """
    入口节点：任务分发
    """

    name = "node_entry"

    def process(self, state: ImportGraphState):
        # 防御性编程
        local_file_path = state.get("local_file_path")
        if not local_file_path:
            # 判断路径字符串是否提供
            logger.error("local_file_path 必须提供, 不能为空")
            raise ValueError("local_file_path 必须提供, 不能为空")

        local_file_path_obj = Path(local_file_path)
        if not local_file_path_obj.exists():
            # 判断路径字符串对应的文件是否存在
            logger.error(f"{local_file_path} 不存在")
            raise ValueError(f"{local_file_path} 不存在")

        logger.info(f"local_file_path 文件开始进行入口判断.")

        # 接下来要判断文件是 md文档 还是 pdf文档 还是其它格式, 进行state赋值, 后期可以根据这些值进行路由, 添加条件边.
        file_title = local_file_path_obj.stem  # .stem 得到的只有文件名, 没有后缀; .name带有后缀
        suffix = local_file_path_obj.suffix
        print(suffix)

        if suffix.lower() == ".md":
            return {
                "file_title": file_title,
                "md_path": local_file_path,
                "is_md_read_enabled": True,
            }
        elif suffix.lower() == ".pdf":
            return {
                "file_title": file_title,
                "pdf_path": local_file_path,
                "is_pdf_read_enabled": True,
            }

        else:
            logger.error(f"local_file_path 文件后缀 {suffix} 不支持")
            raise ValueError(f"local_file_path 文件后缀 {suffix} 不支持")


# 测试节点
if __name__ == "__main__":
    node = NodeEntry()
    init_state = {
        "local_file_path": r"E:\260515\knowledge_base\doc\hak180产品安全手册.pdf"
    }
    result = node(init_state)
    logger.info(result)

"""
# 
这个文件实现了 RAG 导入流程中的“入口校验和任务分发”。
它从上游传入的状态对象中获取本地文件路径，校验路径是否存在，然后根据文件扩展名判断输入是 Markdown 还是 PDF，
并将文件标题、文件路径以及对应的路由标志写回状态，供 LangGraph 的条件边决定后续进入哪个处理节点。


# 它主要做三件事：
    - 校验输入文件路径是否提供、文件是否存在；
    - 从路径中提取不带扩展名的文件标题和文件后缀；
    - 根据 .md 或 .pdf 选择后续处理分支。
    
    
# 当前实际流程入口来自上传接口。上传接口先保存文件，然后构造初始状态：在 import_service.py
    {
        "task_id": task_id,
        "local_dir": local_dir,
        "local_file_path": local_file_path
    }
    
    
# NodeEntry 相当于将外部上传文件转换成内部 RAG 流程能够理解的状态信息。后续图路由函数, 会根据这些标志位选择目标节点


# 详细执行步骤
1. 获取本地文件路径
2. 校验文件路径是否存在
3. 根据文件扩展名判断输入是 Markdown 还是 PDF
4. 将文件标题、文件路径以及对应的路由标志写回状态


#
node_entry.py实现的是 RAG 导入图的入口节点，主要负责输入校验、文件格式识别和流程路由。
它从 `ImportGraphState` 中读取 `local_file_path`，先检查路径是否提供、对应文件是否存在，
然后使用 `pathlib.Path` 提取文件标题和扩展名。
对于 Markdown 文件，它返回 `file_title`、`md_path` 和 `is_md_read_enabled=True`，后续直接进入 Markdown 图片处理节点；
对于 PDF 文件，它返回 `file_title`、`pdf_path` 和 `is_pdf_read_enabled=True`，
后续先进入 PDF 转 Markdown 节点，再复用 Markdown 的处理链路。
这个节点本身不负责切片、Embedding 或 Milvus 入库，而是把外部文件转换成后续 RAG 节点可以消费的结构化状态。


# 关键结论

- `NodeEntry` 是输入校验和格式分发节点，不是内容处理节点。
- 上游输入主要是上传接口生成的 `local_file_path`。
- 下游通过 `is_md_read_enabled` 或 `is_pdf_read_enabled` 进行条件路由。
- Markdown 直接进入图片处理；PDF 先转换成 Markdown，再进入统一处理链路。
- 当前实现可以进一步加强文件类型校验、路径安全、状态一致性、幂等导入和失败恢复。

"""
