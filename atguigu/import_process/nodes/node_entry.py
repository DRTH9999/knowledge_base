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
        file_title = local_file_path_obj.stem  # 只有文件名, 没有后缀; .name带有后缀
        suffix = local_file_path_obj.suffix
        print(suffix)

        if suffix.lower() == ".md":
            return {
                "file_title": file_title,
                "md_path":local_file_path,
                "is_md_read_enabled": True,
            }
        elif suffix.lower() == ".pdf":
            return {
                "file_title": file_title,
                "pdf_path":local_file_path,
                "is_pdf_read_enabled": True,
            }

        else:
            logger.error(f"local_file_path 文件后缀 {suffix} 不支持")
            raise ValueError(f"local_file_path 文件后缀 {suffix} 不支持")
# 测试节点
if __name__ == "__main__":
    node = NodeEntry()
    init_state = {
        "local_file_path" : r"E:\260515\knowledge_base\doc\hak180产品安全手册.pdf"
    }
    result = node(init_state)
    logger.info(result)

