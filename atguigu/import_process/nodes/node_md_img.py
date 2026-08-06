# atguigu/import_process/nodes/node_md_img.py
import re
import os
import time
import base64
from collections import deque
from pathlib import Path
from langchain.chat_models import init_chat_model
from minio.deleteobjects import DeleteObject
from atguigu.config.config import MinioConfig, LLMConfig
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.logger import logger
from atguigu.tool.json_format_tool import json_format
from atguigu.tool.minio_client_tool import get_minio_client, minio_client


class NodeMDImg(NodeBase):
    """
    Markdown照片处理节点: 多模态图片理解
    """

    name = "node_md_img"

    # 第一步: 获取 Markdown 文件内容
    def get_md_context(self, state: ImportGraphState):
        '''
        从 state 中获取 Markdown 文件路径, 检查路径和文件内容是否有效, 读取全文, 最后返回 "文件内容"和 "路径对象"
        return: md_path_obj, md-content
        '''
        md_path = state.get("md_path", "")
        if not md_path:
            logger.error("md_path为空, 必须提供.")
            raise ValueError("md_path为空, 必须提供.")

        md_path_obj = Path(md_path)  # 通过 Path() 转换得到的 Path 对象.
        # 转换成 Path 对象后, 可以方便地调用路径相关方法
        '''
        md_path_obj.exists()   # 路径是否存在 / md_path_obj.is_file()  # 是否是文件
        md_path_obj.name       # 文件名 / md_path_obj.suffix     # 文件扩展名
        md_path_obj.parent     # 父目录 / md_path_obj.stem      # 不带扩展的文件名
        '''
        if not md_path_obj.exists():  # .exists() 返回布尔值, 路径存在: True, 不存在: False.
            logger.error("Markdown文件不存在.")
            raise FileNotFoundError(f"Markdown文件{md_path}不存在.")

        with open(md_path_obj, "r", encoding="utf-8") as f:
            '''
            # with 上下文管理器. 保证代码块执行完毕后自动关闭文件, 即使中途发生异常, 也会执行清理操作.
            - with 用来管理需要释放的资源, 进入 with 时打开文件, 离开代码块时自动关闭文件.
            - 使用 with 的好处是:
                - 读取成功后自动关闭文件;
                - 读取过程中出现异常也会关闭文件;
                - 不容易忘记调用 f.close()
            # open() 是 Python 内置的文件打开函数.
            # "r": 以只读文本模式打开文件. 文件不存在时会抛出 FileNotFoundError.
            # encoding="utf-8": 按照 UTF-8 编码解析文件内容, 避免中文出现乱码.
            # 'as f' 是把打开的文件对象保存到变量 f 中, f 是常见命名, 代表 file, 不是关键字, 
              也可以改成其他名称, 比如file.
            # read() 会从当前位置读取文件内容. 如果没有指定长度, 就会一次性读取到文件末尾, 并返回字符串.
            该程序后面需要对完整 Markdown 内容进行正则搜索, 所以这里选择 read() 一次读取全文.
            '''
            md_content = f.read()  # .read() 一次性读取文件中的全部文本内容; md_content 保存读取结果;

        if not md_content:  # 这里检查的是 完全为空的文件
            logger.error("Markdown文件内容为空.")
            raise ValueError(f"Markdown文件{md_path}内容为空.")

        return md_path_obj, md_content

    # 第二步: 获取携带上下文的图片列表
    def get_image_with_content_list(self, md_content, image_name_list, images_dir_path_obj):
        """
        - 根据图片名称列表, 在 Markdown 文本中找到每张图片的引用位置, 截取图片前后的文本上下文, 并组装图片的本地路径,
          供后续多模态大模型生成图片摘要.
        - md_content 来源: get_md_content 读取 Markdown 文件, 完整的 Markdown 文本.
        - image_name_list 来源: process 中通过 os.listdir() 获取, 图片文件名列表.
          含义: images 目录下的目录项名称, 通常是文件名字符串
        - images_dir_path_obj 来源: process中构造, 图片目录的 Path 对象
          含义: 图片目录的文件夹路径对象, 是一个表示目录路径的 Path 对象
          用途: 与图片文件名拼接出图片完整路径
        - return : image_with_context_list[], 返回一个列表, 每张有效图片对应一个字典.
        """

        # 遍历图片名字, 获取图片的上下文.
        # 过滤不支持的图片格式
        IMAGE_EXTENSTION = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}  # 定义支持的图片格式
        Max_CONTENT_LENGTH = 250  # 图片前后分别最多提取 250 个字符, "字符"是 Python 字符串中的 Unicode 字符数量
        image_with_content_list = []  # 初始化返回列表, 用于存储处理成功的图片信息.

        for image_name in image_name_list:
            # 将字符串格式的image_name强制转换为 Path对象, 是为了使用 .suffix方法
            if Path(image_name).suffix.lower() not in IMAGE_EXTENSTION:  # Path(image_name) 并不要求文件一定存在, 它只是把字符串解释为路径对象
                logger.warning(f"图片文件{image_name}的格式不支持")  # 过滤不支持的格式
                continue  # 采用的是 过滤式控制流, 而不是抛出异常, 不支持的文件格式”被视为可忽略情况, 不应阻断整个图片处理流程.

            # 构建图片在 Markdown中的正则对象
            '''
            # 构造正则表达式, 是为了判断 Markdown 内容 md_content 中是否引用了指定图片 image_name.
            # 为了准确找到"这张图片对应的完整 Markdown 图片标签", 得到图片标签的位置, 因为后面需要start, end = match.span()
              用 start/end 截取图片前后的文字作为上下文. 只找到文件名的位置不够, 必须知道整个图片标签从哪里开始 / 在哪里结束.
            # re.escape(image_name) 防止文件名被当作正则语法, '.'点号在在正则中表示“任意一个字符”.
            # re.compile() 用于把字符串形式的正则表达式编译为正则表达式对象.
            # .search() 是使用规则搜索文本
            # pattern.search() 的返回值有两种情况: 1.找到匹配, 返回re.Match对象, 包含: 匹配文本/起始位置/结束位置/捕获组信息;
                                                2.没有匹配, 返回None
            # Match 对象记录了: 
                 - 匹配到的具体文本;
                 - 匹配文本在原字符串中的位置;
                 - 正则捕获组的内容.
             # match常见用法: 
                 - match.group()   # 完整匹配内容
                 - match.start()   # 开始索引
                 - match.end()     # 结束索引
                 - match.span()    # (开始索引, 结束索引)
            '''
            pattern = re.compile(r"!\[.*?\]\(.*?" + re.escape(image_name) + r"\)")  # pattern 是 re.pattern 正则表达式对象
            match = pattern.search(md_content)  # 方法search() 会从头到尾扫描md_content, 寻找 第一个符合正则规则的片段.
                                                # - 找到: 返回 re.Match 匹配对象; - 没找到: 返回 None .
            # 匹配结果处理
            if not match:
                logger.warning(f"图片{image_name}未在 Markdown 文件中引用")
                continue

            start, end = match.span()  # 获取匹配到的图片的起始位置和结束位置, .span()返回一个二元组(start, end),
                                       # 代码通过 span() 确定整个 Markdown 图片引用的位置.
            pre_text = md_content[max(0, start - Max_CONTENT_LENGTH):start]  # 提取图片前文, 表示获取图片引用之前的 250 个字符
            post_text = md_content[end:min(len(md_content), end + Max_CONTENT_LENGTH)]  # 提取图片后文, 获取图片引用之后的 250 个字符
            '''
            # 假设: start = 1000, MAX_CONTEXT_LENGTH = 250, 
             则提取: pre_text = md_content[750:1000]
             如果图片位于文件开头位置, 例如 start = 100, 则start - 250 = -150, 通过max(0,-150), 修正为[0, 100)
            # 假设: end = 1000, len(md_content) = 5000, 
             则提取: post_text = md_content[1000, 1250]
             如果图片位于文件结尾位置, 例如 end = 4900, end + 250 = 5150, 通过min(5000, 5150), 修正为[4900, 5000)
            '''

            # 将图片信息和上下文信息组合成图片信息字典, 添加到image_with_content_list[]列表当中
            # 构造完整图片路径
            image_path = str(images_dir_path_obj / image_name)  # 使用pathlib.Path拼接路径后, 再使用str() 强制转换为字符串
            # 转换为字符串, 是为了方便后续图片读取 / Base64 编码或传给模型接口
            # 构造返回字典, 汇总结构化数据
            image_with_content_list.append({  # 返回的是一个 由多个图片信息字典组成的列表.
                "image_name": image_name,
                "image_path": image_path,
                "pre_text": pre_text,
                "post_text": post_text
            })
        return image_with_content_list  # 图片筛选 + Markdown 匹配 + 上下文提取 + 路径组装


    def get_image_with_summary_list(self, image_with_context_list):
        #       根据上面的图片列表，进行大模型调用真正生成摘要
        dq = deque(maxlen=30)
        current_time = time.time()

        llm = init_chat_model(
            model=LLMConfig.llm_default_model,
            model_provider="openai",
            base_url=LLMConfig.openai_api_base,
            api_key=LLMConfig.openai_api_key,
            temperature=LLMConfig.llm_default_temperature,
        )

        image_with_summary_list = []
        for image_with_context in image_with_context_list:
            # 一进来，先去盲清一波过期的请求
            while dq and current_time - dq[0] > 60:
                dq.popleft()

            # 有两种情况，一种是有过期的被清理了有位置，一种是一上来就没有过期的还是满员
            # 判断是不是位置满了，如果满了就需要去等待，如果没有满我们就直接发请求把时间加入
            if dq and len(dq) == dq.maxlen:
                # 代表满员没位置，计算需要等待的时间
                need_wait_time = 60 - (current_time - dq[0])
                if need_wait_time > 0:
                    time.sleep(need_wait_time)  # 真正的等待
                    current_time = time.time()
                    while dq and current_time - dq[0] > 60:
                        dq.popleft()

            dq.append(current_time)

            #           先把图片内容base64编码
            with open(image_with_context.get("image_path"), 'rb') as f:
                image_data = f.read()
                base64_str = base64.b64encode(image_data).decode('utf-8')

            #           给大模型发请求
            #           构造提示词：我们参考阿里云百联给的视觉模型提示

            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                # 这个格式就是base64在使用的时候的规定
                                "url": "data:image/jpeg;base64," + base64_str,
                            },
                        },
                        {"type": "text", "text": f"""
                                        这是一张图片，图片上文部分为"{image_with_context.get("pre_text")}"，
                                        下文部分为"{image_with_context.get("post_text")}"，
                                        请用中文简要总结这张图片的摘要,字数在50字以内。"""
                         },
                    ],
                },
            ]

            res = llm.invoke(messages)
            image_with_summary_list.append({
                "image_name": image_with_context.get("image_name"),
                "image_path": image_with_context.get("image_path"),
                "summary": res.content,
            })
        return image_with_summary_list

    # 第四步: 上传图片到minio, 构造图片的线上url, 放到列表当中
    def get_image_with_summary_and_url_list(self, image_with_summary_list):
        upload_dir = MinioConfig.minio_img_dir  # 图片上传的目录
        minio_client = get_minio_client()

        # 幂等性删除目录中的旧图片
        # 1.获取存储桶当中当前目录的的所有旧照片(prefix=upload_dir代表桶下的目录, 无法到达文件)
        old_image_list = minio_client.list_objects(
            bucket_name=MinioConfig.minio_bucket_name,
            prefix=upload_dir,
            recursive=True
        )

        # 2.调用api批量删除旧图片, delete_object_list参数要求必须是DeleteObject对象列表, 需要把上面的图片列表强制转化成DeleteObject对象
        delete_image_list = [DeleteObject(obj.object_name) for obj in old_image_list]

        errors = minio_client.remove_objects(
            bucket_name=MinioConfig.minio_bucket_name,
            delete_object_list=delete_image_list,
        )

        for error in errors:
            logger.error("error occurred when deleting object", error)

        # 3.批量上传图片
        image_with_summary_and_url_list = []
        for image_with_summary in image_with_summary_list:
            minio_client.fput_object(
                bucket_name=MinioConfig.minio_bucket_name,
                object_name=upload_dir + "/" + image_with_summary.get("image_name"),  # 图片上传的完整路径
                file_path=image_with_summary.get("image_path")
            )

            url = f"http://{MinioConfig.minio_endpoint}/{MinioConfig.minio_bucket_name}/{upload_dir}/{image_with_summary.get("image_name")}"
            image_with_summary_and_url_list.append({
                **image_with_summary,
                "url": url
            })
        return image_with_summary_and_url_list

    def replace_md_image(self, md_content, image_with_summary_and_url_list, md_path_obj):
        for image_with_summary_and_url in image_with_summary_and_url_list:
            pattern = re.compile(r"!\[.*?\]\(.*?" + re.escape(image_with_summary_and_url.get("image_name")) + r"\)")
            # md_content = pattern.sub(f"![{image_with_summary_and_url.get("summary")}]({image_with_summary_and_url.get("url")})", md_content)
            # lambda 匿名函数，可以规避特殊字符，特殊字符也能替换成功
            md_content = pattern.sub(
                lambda _: f"![{image_with_summary_and_url.get("summary")}]({image_with_summary_and_url.get("url")})",
                md_content)

            # 备份新的md文件
        new_md_path_obj = md_path_obj.parent / str(md_path_obj.stem + "_new.md")
        with open(new_md_path_obj, "w", encoding="utf-8") as f:
            f.write(md_content)

        return new_md_path_obj, md_content

    def process(self, state: ImportGraphState):
        # 第一步: 获取 Markdown 文件路径, 检查路径和文件内容是否有效, 读取全文, 最后返回 "文件内容"和 "路径对象"
        md_path_obj, md_content = self.get_md_context(state)
        # 获取 Markdown 的图片所在 images 目录中的图片文件, 图片的存储路径
        image_dir_path_obj = md_path_obj.parent / "images"
        if not image_dir_path_obj.exists():
            return {
                "md_content": md_content
            }

        # 判断图片文件夹是否为空
        image_name_list = os.listdir(image_dir_path_obj)  # os.listdir 列出目录文件夹下的所有文件和文件名
        if not image_name_list:
            logger.error("图片路径为空")

            return {
                "md_content": md_content,
            }

        image_with_content_list = self.get_image_with_content_list(md_content, image_name_list, image_dir_path_obj)

        image_with_summary_list = self.get_image_with_summary_list(image_with_content_list)

        image_with_summary_and_url_list = self.get_image_with_summary_and_url_list(image_with_summary_list)

        new_md_path_obj, md_content = self.replace_md_image(md_content, image_with_summary_and_url_list, md_path_obj)

        return {
            "md_content": md_content,
            "md_path": str(new_md_path_obj)
        }

if __name__ == "__main__":
    node = NodeMDImg()
    init_state = {
        "md_path": r"E:\260515\knowledge_base\outputs\hak180产品安全手册\hak180产品安全手册.md"
    }
    result = node(init_state)
    logger.info(json_format(result))
