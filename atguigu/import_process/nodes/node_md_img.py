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
        return: md_path_obj, md_content
        '''

        # 从状态中获取 Markdown 路径
        md_path = state.get("md_path", "")
        if not md_path:
            logger.error("md_path为空, 必须提供.")
            raise ValueError("md_path为空, 必须提供.")

        # 通过 Path() 转换得到的 Path 对象
        md_path_obj = Path(md_path)
        # 转换成 Path 对象后, 可以方便地调用路径相关方法
        '''
        md_path_obj.exists()   # 路径是否存在 / md_path_obj.is_file()  # 是否是文件
        md_path_obj.name       # 文件名 / md_path_obj.suffix     # 文件扩展名
        md_path_obj.parent     # 父目录 / md_path_obj.stem      # 不带扩展的文件名
        '''
        if not md_path_obj.exists():  # .exists() 返回布尔值, 路径存在: True, 不存在: False.
            logger.error("Markdown文件不存在.")
            raise FileNotFoundError(f"Markdown文件{md_path}不存在.")

        # 按照 UTF-8 编码读取 Markdown 全文
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
            # 'as f' 是把打开的文件对象保存到变量 f 中, f 是常见命名, 代表 file, 不是关键字, 也可以改成其他名称, 比如file.
            # 如果是 "r", 则 f 的类型：_io.TextIOWrapper, f.read() 的返回类型：str;
              如果是 "rb", 则 rb 的类型：_io.BufferedReader, f.read() 的返回类型：bytes;
              区别不在于类型，而在于打开模式
            # read() 会从当前位置读取文件内容. 如果没有指定长度, 就会一次性读取到文件末尾, 并返回字符串str.
            该程序后面需要对完整 Markdown 内容进行正则搜索, 所以这里选择 read() 一次读取全文.
            '''
            md_content = f.read()  # .read() 一次性读取文件中的全部文本内容, 返回字符串; md_content 保存读取结果;
                                   # readline()   # 读取一行, 返回一行字符串; readlines() 读取所有行, 返回字符串列表 list[str]; readable()   # 判断是否可以读取
        # 检查文件内容是否为空
        if not md_content:
            logger.error("Markdown文件内容为空.")
            raise ValueError(f"Markdown文件{md_path}内容为空.")

        return md_path_obj, md_content

    # 第二步: 获取携带上下文的图片列表
    def get_image_with_content_list(self, md_content, image_name_list, images_dir_path_obj):
        """
        - 根据图片名称列表, 在 Markdown 文本中找到每张图片的引用位置, 截取图片前后的文本上下文, 并组装图片的本地路径,
          供后续多模态大模型生成图片摘要.
        - md_content 来源: get_md_content 读取 Markdown 文件, 完整的 Markdown 文本.

        - image_name_list : images 目录中的文件名列表
          来源: process 中通过 os.listdir() 获取, 图片文件名列表.
          含义: images 目录下的目录项名称, 通常是文件名字符串

        - images_dir_path_obj : images 目录的 Path 对象。
          来源: process中构造
          含义: 图片目录的文件夹路径对象, 是一个表示目录路径的 Path 对象
          用途: 与图片文件名拼接出图片完整路径
        - return : image_with_context_list[], 返回一个列表, 每张有效图片对应一个字典.
        """

        # 遍历图片名字, 获取图片的上下文.
        # 第一步：定义支持的图片格式, 过滤不支持的图片格式
        IMAGE_EXTENSTION = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}  # 定义支持的图片格式

        Max_CONTENT_LENGTH = 250  # 图片前后分别最多提取 250 个字符, "字符"是 Python 字符串中的 Unicode 字符数量

        image_with_content_list = []  # 初始化返回列表, 用于存储处理成功的图片信息.

        for image_name in image_name_list:
            # 将字符串格式的 image_name 强制转换为 Path对象, 是为了使用 .suffix方法
            if Path(image_name).suffix.lower() not in IMAGE_EXTENSTION:  # Path(image_name) 并不要求文件一定存在, 它只是把字符串解释为路径对象
                logger.warning(f"图片文件{image_name}的格式不支持")  # 过滤不支持的格式
                continue  # 采用的是 过滤式控制流, 而不是抛出异常, 不支持的文件格式”被视为可忽略情况, 不应阻断整个图片处理流程.

            # 构建图片在 Markdown中的正则对象
            '''
            # 构造正则表达式, 是为了判断 Markdown 内容 md_content 中是否引用了指定图片 image_name.
            # 为了准确找到"这张图片对应的完整 Markdown 图片标签", 得到图片标签的位置, 因为后面需要start, end = match.span()
              用 start/end 截取图片前后的文字作为上下文. 只找到文件名的位置不够, 必须知道整个图片标签从哪里开始 / 在哪里结束.
            # re.escape(image_name) 防止文件名被当作正则语法, '.'点号在在正则中表示“任意一个字符”.
            # re.compile() 用于把字符串形式的正则表达式 编译为 正则表达式对象.
            # .search() 是使用规则搜索文本
            # pattern.search() 的返回值有两种情况: 
                1.找到匹配, 返回re.Match对象, 包含: 匹配文本/起始位置/结束位置/捕获组信息;
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
            # 第二步：构造 Markdown 图片正则表达式
            pattern = re.compile(r"!\[.*?\]\(.*?" + re.escape(image_name) + r"\)")  # pattern 是 re.pattern 正则表达式对象

            # 第三步：确认图片被 Markdown 引用
            match = pattern.search(md_content)  # 方法search() 会从头到尾扫描 md_content , 寻找 第一个符合正则规则的片段.
                                                # - 找到: 返回 re.Match 匹配对象; - 没找到: 返回 None .
            # 匹配结果处理
            # 如果 images 目录有图片，但是 Markdown 正文没有引用，就不进入后续模型处理
            # images 目录中的物理图片 Markdown 实际引用的业务图片, 只有二者匹配上的图片才会继续处理。
            if not match:
                logger.warning(f"图片{image_name}未在 Markdown 文件中引用")
                continue

            # 第四步：获取图片标签位置
            start, end = match.span()  # 获取 匹配到的图片的起始位置和结束位置, .span()返回一个二元组(start, end),
                                       # 代码通过 span() 确定整个 Markdown 图片引用的位置.

            # 第五步：截取图片前后文
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
            # 第六步：构造本地图片路径
            image_path = str(images_dir_path_obj / image_name)  # 使用 pathlib.Path 拼接路径后, 再使用str() 强制转换为字符串
                                                                # 转换为字符串, 是为了方便后续图片读取 / Base64 编码或传给模型接口
            # 构造返回字典, 汇总结构化数据
            image_with_content_list.append({  # 返回的是一个 由多个图片信息字典组成的列表.
                "image_name": image_name,
                "image_path": image_path,
                "pre_text": pre_text,
                "post_text": post_text
            })

        # 第七步：将图片信息和上下文信息组合成图片信息字典, 添加到image_with_content_list[]列表当中
        return image_with_content_list  # 图片筛选 + Markdown 匹配 + 上下文提取 + 路径组装

    # 第三步: 根据上面的图片列表, 调用大模型, 生成图片摘要
    def get_image_with_summary_list(self, image_with_context_list):
        '''
        这个函数负责真正调用视觉大模型，为每张图片生成摘要。
        :param image_with_context_list: 每个元素都包含：- 图片名称。- 图片本地路径。- 图片前文。- 图片后文。
        '''
        # 滑动窗口限流
        # 第一步：创建请求时间窗口
        dq = deque(maxlen=30)  # 用于保存最近一段时间内的请求时间戳
        current_time = time.time()  # 获取当前时间戳

        # 第二步：初始化视觉模型
        llm = init_chat_model(
            model=LLMConfig.vl_model,
            model_provider="openai",
            base_url=LLMConfig.openai_api_base,
            api_key=LLMConfig.openai_api_key,
            temperature=LLMConfig.llm_default_temperature,
        )

        image_with_summary_list = []
        for image_with_context in image_with_context_list:
            # 第三步：清理过期请求记录, 每处理一张图片，先清理 60 秒以前的请求时间
            while dq and current_time - dq[0] > 60:
                dq.popleft()

            # 第四步：窗口满时等待
            # 有两种情况，一种是有过期的被清理了有位置，一种是没有过期的满员状态
            # 判断是不是位置满了，如果满了就需要去等待，如果没有满我们就直接发请求把时间加入
            if dq and len(dq) == dq.maxlen:
                # 计算最早请求还需要多久才能离开 60 秒窗口，即需要等待的时间：
                need_wait_time = 60 - (current_time - dq[0])
                if need_wait_time > 0:
                    time.sleep(need_wait_time)  # 真正的等待
                    current_time = time.time()
                    while dq and current_time - dq[0] > 60:
                        dq.popleft()

            dq.append(current_time)

            # 第五步：读取图片并转 Base64
            with open(image_with_context.get("image_path"), 'rb') as f:
                image_data = f.read()
                base64_str = base64.b64encode(image_data).decode('utf-8')

            #   给大模型发请求
            #   构造多模态消息, 参考阿里云百联给的视觉模型提示
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

            # 第七步：调用模型
            res = llm.invoke(messages)

            # 原来的上下文结构会转换为摘要结构
            image_with_summary_list.append({
                "image_name": image_with_context.get("image_name"),
                "image_path": image_with_context.get("image_path"),
                "summary": res.content,
            })
        return image_with_summary_list

    # 第四步: 上传图片到minio, 生成图片的线上url, 放到列表当中
    def get_image_with_summary_and_url_list(self, image_with_summary_list):

        # 第一步：取得上传目录和客户端
        upload_dir = MinioConfig.minio_img_dir  # 图片上传的目录
        minio_client = get_minio_client()

        # 第二步：查找上传目录中的旧图片
        # 1.获取存储桶中, 当前目录的的所有旧照片(prefix=upload_dir 代表桶下的目录, 无法到达文件)
        old_image_list = minio_client.list_objects(
            bucket_name=MinioConfig.minio_bucket_name,
            prefix=upload_dir,  # prefix=upload_dir 表示列出指定对象前缀下的所有文件
            recursive=True
        )

        # 第三步：转换批量删除参数
        # 2.调用api批量删除旧图片,
        # 因为 MinIO 的批量删除接口要求参数是 DeleteObject 对象列表, 所以需要把上面的图片列表强制转化成DeleteObject对象
        delete_image_list = [
            DeleteObject(obj.object_name)
            for obj in old_image_list
        ]

        # 第四步：删除旧对象
        errors = minio_client.remove_objects(
            bucket_name=MinioConfig.minio_bucket_name,
            delete_object_list=delete_image_list,
        )

        for error in errors:
            logger.error("error occurred when deleting object", error)

        # 第五步：上传当前图片
        image_with_summary_and_url_list = []

        for image_with_summary in image_with_summary_list:
            minio_client.fput_object(
                bucket_name=MinioConfig.minio_bucket_name,  # 上传到哪个 bucket
                object_name=upload_dir + "/" + image_with_summary.get("image_name"),  # 图片在 bucket 中的对象名称
                file_path=image_with_summary.get("image_path"),  # 本地图片路径
            )

            # 第六步：构造图片 URL
            url = f"http://{MinioConfig.minio_endpoint}/{MinioConfig.minio_bucket_name}/{upload_dir}/{image_with_summary.get("image_name")}"

            # 通过字典展开保留之前的字段，再加入 url
            image_with_summary_and_url_list.append({
                **image_with_summary,
                "url": url
            })

        return image_with_summary_and_url_list

    # 第五步: 把 Markdown 中原来的图片标签替换成新的图片标签
    def replace_md_image(self, md_content, image_with_summary_and_url_list, md_path_obj):
        for image_with_summary_and_url in image_with_summary_and_url_list:

            # 第一步：重新定位图片标签
            pattern = re.compile(r"!\[.*?\]\(.*?" + re.escape(image_with_summary_and_url.get("image_name")) + r"\)")

            # 第二步：替换图片标签
            # md_content = pattern.sub(f"![{image_with_summary_and_url.get("summary")}]({image_with_summary_and_url.get("url")})", md_content)
            # lambda 匿名函数，让生成的摘要和 URL 直接作为普通字符串进入结果，避免替换字符串中的特殊字符被 re.sub 按分组引用或转义字符解释
            md_content = pattern.sub(
                lambda _: f"![{image_with_summary_and_url.get("summary")}]({image_with_summary_and_url.get("url")})",
                md_content)

        # 第三步：生成新 Markdown 文件
        new_md_path_obj = md_path_obj.parent / str(md_path_obj.stem + "_new.md")

        # 第四步：写入新内容
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
            "md_content": md_content,  # 替换图片后的 Markdown 全文
            "md_path": str(new_md_path_obj)  # 指向新生成的 *_new.md
        }

if __name__ == "__main__":
    node = NodeMDImg()
    init_state = {
        "md_path": r"E:\260515\knowledge_base\outputs\hak180产品安全手册\hak180产品安全手册.md"
    }
    result = node(init_state)
    logger.info(json_format(result))


'''
# 概括: 
  - node_md_img.py 实现了 RAG 知识库导入流程中的 Markdown 图片多模态处理节点 。
它负责读取 Markdown 及其同级 images 目录中的图片，调用视觉大模型理解图片内容，把图片转换为简短的中文语义摘要，
再将图片上传到 MinIO，最后把 Markdown 原来的本地图片引用替换为：![图片语义摘要](MinIO图片URL)

  - 解决的是一个核心问题： 传统文本 RAG 无法直接理解和检索 图片内容

  - 经过这个节点处理后：
    - 图片内容被转换成文字摘要，可以进入文本切片。
    - 图片摘要可以生成稠密向量和稀疏向量。
    - 用户问题可以通过图片摘要召回相关知识。
    - 图片 URL 会保留在召回文本中，查询端可以提取并展示图片。
    - 本地图片地址转换为 MinIO 地址，不再依赖导入机器的本地文件系统。
    

# 举例:
- 如果原 Markdown 是：

    ## 安全注意事项
    ![设备安全示意图](images/safe.jpg)

- 图片本身无法直接交给当前项目中的文本 Embedding 模型处理, 经过该节点处理后，Markdown 文件中的图片将被替换为：

    ## 安全注意事项
    ![设备应放置在平稳通风处，操作时避免接触高温区域](http://minio/bucket/images/safe.jpg)
    
- 处理后：
  - “平稳”“通风”“高温区域”等图片语义会进入 chunk。
  - 用户询问“设备应该放在哪里”时，可以召回这个 chunk。
  - 图片 URL 也保留在 chunk 中，可以跟随检索结果返回。

- 形成了如下多模态闭环：
  图片  ->  视觉大模型理解  ->  中文摘要  ->  文本切片  ->  向量化和入库  ->  语义召回  ->  返回图片 URL


# get_md_content
  - 从 state 中获取 Markdown 文件路径, 检查路径和文件内容是否有效, 读取全文, 最后返回 "文件内容" md_content 和 "路径对象" md_path_obj
  
  - 返回值：
      - md_content ：Markdown 原始全文。
      - md_path_obj ：Markdown 的 Path 对象。
    这里同时返回内容和路径，是因为后续既要在内容里定位图片，又要根据路径定位同级 images 目录和生成新文件。


# 滑动窗口

- 使用 deque 是因为它适合：
    - 在右侧追加新请求时间。
    - 从左侧移除最早的请求时间。
    - 保持时间戳从旧到新的顺序。
    
- 使用的是基于时间戳队列的滑动窗口限流。
它通过 deque 保存最近最多 30 次请求的时间戳。每次发送大模型请求前，先清理 60 秒之前的过期记录。
如果最近 60 秒内已经有 30 次请求，就计算最早一次请求, 距离窗口结束还需要等待的时间，通过 sleep 阻塞等待，等最早记录过期后再发送当前请求。
因此它实现的是“任意连续 60 秒最多 30 次请求”，能够避免固定窗口在时间边界处出现突发流量。


state
  ↓
读取和校验 Markdown
  ↓
定位同级 images 目录
  ↓
判断 images 是否存在、是否为空
  ↓
找出 Markdown 实际引用的图片
  ↓
截取每张图片的前后文
  ↓
调用视觉模型生成摘要
  ↓
清理 MinIO 旧图片
  ↓
上传当前图片并生成 URL
  ↓
替换 Markdown 图片标签
  ↓
生成 *_new.md
  ↓
返回 md_content 和新 md_path

   
# 单例函数
  - 单例 主要是指某个类只有一个实例: 如果是函数只执行一次, 则更接近函数缓存或记忆化. 
  - 实际开发中, 模块级对象通常是最简单 / 最 Pythonic 的单例实现方式.
  - 确保某个类只有一个实例, 并提供一个全局访问点.
'''
