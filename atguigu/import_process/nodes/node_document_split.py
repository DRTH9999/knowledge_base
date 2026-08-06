# atguigu/import_process/nodes/node_document_split.py
import re  # 用于正则表达式匹配, 使用正则表达式识别标题和代码块

from charset_normalizer import md
from langchain_text_splitters import RecursiveCharacterTextSplitter  # 导入langchain 提供的递归字符文本切分器, 对过长文本进行递归切分
from pathlib import Path  # 用于操作文件路径, 进行跨平台路径处理
from atguigu.import_process.base import NodeBase  # 导入流程节点的基类
from atguigu.import_process.state import ImportGraphState  # 导入流程状态类型定义
from atguigu.tool.json_format_tool import json_format  # 导入 JSON 格式化函数
from atguigu.tool.logger import logger  # 导入项目统一日志对象


class NodeDocumentSplit(NodeBase):
    """
    文档切分节点：智能文档切片
    """

    name = "node_document_split"  # name是类属性, 该子类必须重写name, 否则父类NodeBase会抛出异常.

    def get_md_content(self, state: ImportGraphState):  # 读取 Markdown 文件，并准备后续处理所需的基础信息
        '''
        - 作用: - 从状态中读取 md_path; - 检查路径是否存在; - 获取文件标题; - 读取并规范化 Markdown 内容.
        - :param
            self: 当前NodeDocumentSplit对象
            state: 预期类型 -> ImportGraphState
        - :return: md_content: md文档全部内容, file_title: md文档标题, md_path_obj: md文档路径 Path对象
                  即返回一个三元组 tuple[str, str, Path]
        - 调用时使用元组解包:
            md_content, file_title, md_path_obj = self.get_md_content(state)
        '''
        md_path = state.get("md_path", '')  # .get 的优点是: 当键不存在时不会抛出 KeyError , 而是返回默认值 ''
        if not md_path:
            logger.error("未提供md_path")
            raise ValueError("未提供md_path")

        md_path_obj = Path(md_path)  # 创建路径对象, 将字符串路径转换为 Path 对象, 得到一个可以进行路径操作的对象
        if not md_path_obj.exists():  # 检查文件是否存在
            logger.error(f"文件不存在: {md_path}")
            raise FileNotFoundError(f"md_path不存在: {md_path}")

        file_title = state.get("file_title", '')  # 读取文件标题
        if not file_title:  # 优先从状态中获取文件标题
            file_title = md_path_obj.stem  # 如果状态中没有标题, 则使用 文件名 作为标题

        with open(md_path_obj, 'r', encoding="utf-8") as f:  # 以 UTF-8 编码 / 只读模式打开 Markdown 文件.
            md_content = f.read()  # 读取全部内容, f.read()返回 str 字符串,

        # 判断内容是否为空
        if not md_content:
            logger.error(f"文件内容为空: {md_path}")
            raise ValueError(f"文件内容为空: {md_path}")

        # 统一不同操作系统的换行符格式, 把不同操作系统使用的换行符统一转换成 Unix/Linux 常用的 \n
        md_content = md_content.replace("\r\n", "\n").replace("\r", "\n")
        '''
        - 这句代码分两步执行: 1. md_content.replace("\r\n", "\n") 先把 Windows 换行转换成 Unix 换行格式,
                         2. .replace("\r", "\n") 处理剩余的单独 "\r" 
                         
        - 为什么要先替换 "\r\n" 再替换 "\r"
          因为 Windows 换行符 \r\n 是由两个字符组成的, 如果先执行: md_content.replace("\r", "\n")
          那么 "\r\n" 会变成 "\n\n", 这样就会产生多余的空行.
          
        - 系统            换行符 
        Windows          \r\n 
        Linux/macOS       \n 
        老版本 macOS       \r
        '''

        return md_content, file_title, md_path_obj

    def get_section_list(self, md_content, file_title):
        """
        - 作用: 按照 Markdown 标题, 把整篇文档划分成多个章节.
        - :param
            self: 当前 NodeDocumentSplit对象
            md_content: md文档全部内容
            file_title: md文档标题
        - :return: section_list: 切分后的章节列表
        - 调用时使用元组解包:
            section_list = self.get_section_list(md_content, file_title)
        """

        # 按照换行切分
        md_line_list = md_content.split("\n")  # 将全文拆分为 行列表, 返回一个列表 list[str]

        # 定义代码块的正则表达式
        code_pattern = r"^(`{3,}|~{3,})"  # 定义 Markdown 文档中代码块的正则表达式
        '''
        为什么要识别代码块?
          - 因为代码中有注释'#', 如果不判断代码块, 程序会把代码中的 '#'行, 当作章节标题.
        '''

        is_in_block = False  # 定义是否在代码块中的状态变量标志, 表示当前是否处于代码块内部; 初始值为 False, 表示还没有进入代码块.
        marker = None  # 保存当前代码块使用的标记类型, 可能是'```'或者'~~~', 保存标记的目的是让结束标记和开始标记保持一致.
        title_pattern = r'^\s*#{1,6}\s+.+'  # 定义 Markdown 文档标题的正则表达式
        current_index = 0  # 表示当前章节开始位置的下标

        section_list = []  # 创建结果列表, 用于保存所有章节字典. 最终返回list[str]

        # 核心目标: 按 Markdown 标题对文档进行分段, 同时忽略代码块里的“伪标题”.
        # 遍历所有行
        for index, line in enumerate(
                md_line_list):  # 使用 enumerate() 遍历 Markdown 行列表, 同时得到: index: 当前行的下标, line: 当前行的内容.
            # 为什么需要 index ? - 后续使用列表切片时, 需要知道当前行是第几行, 所以必须知道当前标题所在的下标.
            line = line.strip()  # 去除当前行的行首和行尾的空白字符(空格, 制表符, 换行符), "   # 标题   " --> "# 标题", 能够提高正则匹配的成功率.
            # 这里只改变了用于判断的局部变量 line , 没有改变原始的 md_line_list , 所以后面保存的内容仍然保留原始格式.

            # 判断当前行是否是代码围栏
            match = re.match(code_pattern, line)  # 判断代码块标记, 如果匹配成功, 返回一个 re.Match 对象; 如果匹配失败, 返回: None
            # line 是当前行的内容, 是需要正则匹配的对象
            if match:  # 如果 match 不是None, 说明当前行看起来是代码块围栏, 接下来需要判断: 是否是代码块开始标记, 还是代码块结束标记.
                # 当前不在代码块中, 说明这是代码块开始
                if not is_in_block:  # 判断当前是否在代码块外, 如果当前不在代码块中, 又遇到了代码围栏,一般认为当前行是代码块的开始.
                    is_in_block = True  # 设置进入代码块状态, 表示从当前行开始, 后续内容位于代码块内部.
                    # 设置后, 后面的标题判断 " if not is_in_block and re.match(title_pattern, line): ",
                    # 将不会对代码块中的行进行标题识别.
                    marker = match.group(1)  # 取得正则表达式第一个捕获组匹配到的内容, 并保存到 marker 中,
                    # code_pattern = r"^(`{3,}|~{3,})", line的内容是" ```python ", 则marker = " ``` "
                    # 为什么要保存 marker? - 开始标记和结束标记应该使用相同类型, 避免不同类型的标记错误配对.
                    logger.info(f"开始代码块: {marker}")  # 记录程序已经进入代码块, 以及当前代码块使用的围栏标记.
                # 当前已经在代码块当中, 当前行又匹配到了代码围栏, 可能是代码块的结束标记
                else:  # 当再次遇到代码块标记时, 判断它是否和开始标记一致, 只有一致时才结束代码块
                    if marker == match.group(1):  # 判断结束围栏是否和开始围栏一致, marker: 进入代码块时记录的围栏标记, match.group(1): 当前行匹配到的围栏标记
                        is_in_block = False  # 设置离开代码块, 表示当前代码块结束. 后续再次遇到Markdown标题时, 不会进入代码块, 可以正常进行标题识别.
                        marker = None  # 清除代码围栏标记, 代码块已经结束, 不再需要保存原来的围栏标记, 所以将其重置. 可以避免后面误用旧值
                        logger.info("结束代码块")

            # 标题判断逻辑. 现在不在代码块中, 就可以判断是不是标题.
            if not is_in_block and re.match(title_pattern, line):  # 只有同时满足以下两个条件, 才认为当前行是章节标题:
                # 1. not is_in_block: 当前不在代码块中;  2. re.match(title_pattern, line): 当前行符合标题格式的正则表达式.

                # 取出上一个 section 的所有行
                temp_list = md_line_list[current_index:index]  # 使用列表切片, 取出从 `current_index` 到 `index` 之前的内容.
                # 当前遇到的这个新标题不会被放进上一个 section

                content = "\n".join(temp_list)  # 把多行内容重新拼接为字符串, 将行列表重新组合成 Markdown 文本. 使用 \n 可以保留行之间的换行关系

                # 构造分段结果, 生成一个字典, 用来描述当前section
                section_dict = {
                    "title": temp_list[0] if content.startswith('#') else "无标题",
                    # 如果这一段内容以 # 开头, 则认为第一行是标题; 否则将标题设置成 "无标题".
                    "content": content,  # 保存当前 section 的完整 Markdown 内容, 包括标题和正文.
                    "file_title": file_title  # 保存当前 section 所属的文件, 这样将多个Markdown文件拆分后, 仍然知道每个section来自哪个文件.
                }
                section_list.append(section_dict)  # 将 section 保存到结果列表, 将构造完成的分段字典 添加到最终结果列表section_list 中.

                current_index = index  # 更新下一段的起始位置, 将当前标题的下标, 设置为下一段的起始位置. 时切分逻辑的关键
        # 添加最后一个章节
        '''
        为什么循环结束后还要额外添加一次？
        - 因为程序只有遇到“下一个标题”时, 才能知道“上一个章节在哪里结束”. 最后一个章节后面没有下一个标题, 所以它不会在循环内部被添加.
        所以循环结束后, 必须手动把最后一段保存下来.
        '''
        section_list.append({
            "title": md_line_list[current_index],  # 直接把最后一个 section 的第一行当作标题
            "content": '\n'.join(md_line_list[current_index:]),  # 这里省略了切片结束位置, 表示从 ' current_index ' 一直到列表末尾.
            "file_title": file_title
        })

        return section_list

    def get_final_section_list(self, section_list, md_path_obj, file_title):
        '''
              - 这个方法负责把章节列表处理成最终的文本切片列表.
              - 主要完成:
                  1.短章节直接保留.
                  2.包含 HTML 表格的章节不切分.
                  3.其他过长章节使用文本切分器切成多个小片段chunk.
                  4.每个 chunk 前面加上原章节标题
                  5.给每个 chunk 标记 part 编号
                  6.最终把所有结果保存到 chunks.json 文件中

              - 这样做通常是为了: 适配大模型上下文长度; 做向量化和知识库检索; 将长文档拆成多个独立文本块; 保留章节标题，增强检索结果的上下文信息
              :param section_list: 由 get_section_list 返回的章节列表; 类型: list[dict]
                     md_path_obj : Markdown 文件的路径对象, 主要在实例方法中确定 chunks.json的保存目录, 类型: pathlib.Path
                     file_title: 整个 Markdown 文件的文件名, 最终每个切片都会保存该字段, 类型: str
              :return: final_section_list 列表
              '''
        max_length = 300  # 正文长度阈值. 如果正文长度小于 300: 直接保留, 不切分; 如果正文长度达到或超过 300: 进入进一步切分逻辑.
        # 这里统计的是字符数量, 不是Token数 / 字节数 / 模型实际上下文长度
        over_lap = 30  # 相邻切片chunk之间的重叠长度, 防止语义被截断, 可以保留相邻切片之间的上下文联系.

        final_section_list = []  # 初始化最终结果列表, 用于存储最终处理后的章节或者chunk, 之后所有的结果都会追加到该列表中.

        # 创建递归文本切分器
        spliter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ";", " "],  # separators 是切分时使用的分隔符列表, 顺序代表优先级.
            # 设计目的: 尽量在自然语义边界处切分, 而不是简单地每 300 个字符硬切.
            chunk_size=max_length,  # 表示每个文本块目标长度约为 300 个字符. 注意: 这里通常是目标长度, 不一定保证每个chunk 严格不超过300.
            chunk_overlap=over_lap  # 从表示相邻 chunk 尽可能共享 30 个字符. 注意: overlap 也不是任何情况下都能精确达到 30 个字符, 它取决于切分边界.
        )
        # 遍历所有章节
        for section in section_list:
            title = section.get("title")  # 从章节字典中读取标题
            content = section.get("content")  # 从章节字典中读取章节内容

            # 去除章节标题, 获取正文
            '''
            - 设计意图是:
                - 原始 content 里面可能包含标题
                - 切分时不希望标题参与正文切分
                - 先把标题从正文中去除
                - 切分完成后，再把标题重新加到每个 chunk 前面
            - 为什么先去掉标题? 
                - 因为后面只对正文进行长度判断和切分, 标题不应该重复参与正文切分.
            - content.startswith('#') : 判断章节内容是否以 # 开始. 
                - 如果内容以 # 开始: 
                    content[len(title):]
                从标题长度之后开始截取, 去掉标题.
                - 如果内容不以 # 开始: 
                    real_content = content
                表示该章节可能是没有标题的文档开头内容, 直接保留全部内容.
            '''
            real_content = content[len(title):] if content.startswith(title) else content  # 得到不包含章节标题的正文

            # 判断章节是否过短, 短内容直接保留.
            if len(real_content) < max_length:
                final_section_list.append({
                    **section,  # 字典展开语法, 把原章节字典中的所有字段复制过来, 它的优点是保留原章节中的其他字段.
                    "part": 0  # 这里使用 part = 0, 表示该章节没有被拆分, 或者是完整章节.
                })
                continue

            # 判断是否包含 HTML 表格
            if "<table" in real_content:  # 用于判断正文中是否出现 <table 字符串
                final_section_list.append({
                    **section,
                    "part": 0
                })
                continue

            # 真正切分正文
            split_chunk_list = spliter.split_text(real_content)  # 调用递归切分器的 split_text 方法, 将正文拆成多个字符串, 返回值类型是: list[str]
            # 遍历每个 chunk , 给切片编号
            for index, splite_chunk in enumerate(split_chunk_list, start=1):
                final_section_list.append({  # 构造切分后的章节对象
                    "title": title,  # 保存原始章节标题
                    "file_title": file_title,  # 保存所属文件标题
                    "content": title + "\n\n" + splite_chunk,  # 切分之前, 代码先去除了标题; 切分后, 再把标题加回到每个 chunk 前面.
                    "part": index  # 表示当前 chunk 是该章节的第几部分
                })

            # 备份 chunks列表 到 json文件, 用于后续流程使用
            # 打开 Markdown 文件所在目录下的 chunks.json.
            with open(md_path_obj.parent / "chunk.json", "w", encoding="utf-8") as f:  # "w" : 覆盖写入模式, 如果文件已经存在, 会覆盖原文件.
                f.write(json_format(final_section_list))  # 将 最终列表 序列化为 JSON 字符串, 然后写入文件.

            return final_section_list

    def process(self, state: ImportGraphState):

        # 获取 Markdown 内容, 该方法返回 md_content / file_title / md_path_obj, 通过元组解包分别保存.
        md_content, file_title, ma_path_obj = self.get_md_content(state)

        # 获取章节列表, 返回：按标题划分的章节列表.
        section_list = self.get_section_list(md_content, file_title)

        # 获取最终切片列表
        final_section_list = self.get_final_section_list(section_list, ma_path_obj, file_title)

        # 返回节点结果, 最终返回一个字典. 返回值类型可以表示为:dict[str, list[dict]]
        return {
            "chunks": final_section_list
        }

if __name__ == '__main__':
    node = NodeDocumentSplit()
    init_state = {
        "md_path": r"E:\260515\knowledge_base\outputs\hak180产品安全手册\hak180产品安全手册_new.md",
        "file_title": "hak180产品安全手册"
    }
    result = node(init_state)
    logger.info(json_format(result))

'''
# 这个模块实现了一个“文档切分节点”, 主要用于:
    1. 从状态对象中获取 Markdown 文件路径.
    2. 读取 Markdown 文件内容.
    3. 先按照 Markdown 标题划分为多个章节.
    4. 对过长章节进一步切分.
    5. 给每个切片补充标题.
    6. 将最终切片保存为 chunks.json .
    7. 返回切片列表, 供后续流程继续使用.

# 整体流程: 
    ImportGraphState
             │
             ▼
     get_md_content()
     读取 Markdown 内容 / 文件标题 / 路径对象
             │
             ▼
     get_section_list()
     按 Markdown 标题划分章节
             │
             ▼
     get_final_section_list()
     对过长章节进行二次切分
             │
             ├── 写入 chunks.json
             │
             ▼
     process()
     返回 {"chunks": final_section_list}
     
# split() 是字符串分割函数, 用于按照指定的分隔符把字符串拆分成一个 列表list[str]

格式: 字符串.split(sep=None, maxsplit=-1)
参数: - sep: 分隔符, 默认为 None
     - maxsplit:最大分割次数, 默认为 -1, 表示不限制次数.
    
- 当不传参数时, split() 会按照空格 / 制表符'\t' / 换行'\n'等空白字符分割, 并且会自动忽略连续空白.

- 指定分隔符时, 连续的分隔符会产生空字符串; 如果想去掉首尾空白, 可以先使用 strip().

- split() 一次只能使用一个分隔符, 如果需要按照多个不同的分隔符分割, 可以使用正则表达式.

- 如果只是按换行符分割, 推荐使用 splitlines(), 它比 split("\n") 更适合处理不同操作系统的换行格式

    - 例如: text = "第一行\n第二行\r\n第三行"
           print(text.splitlines())
           
    - 输出: ['第一行', '第二行', '第三行']

# enumerate() , 用于在遍历可迭代对象时, 同时获取索引和值. 

- 基本语法: enumerate(iterable, start=0)
  参数:    iterable: 可迭代对象, 例如列表 / 元组 / 字符串等
          start: 索引起始值, 默认为 0, 可以指定任意值.
          
- enumerate() 返回的是一个迭代器对象, 可以转换为列表:

    letters = ["a", "b", "c"]
    result = list(enumerate(letters))
    print(result)

    输出:[(0, 'a'), (1, 'b'), (2, 'c')]

- enumerate() 返回的每一项都是一个二元组, 通常使用元组解包:

    for index, value in enumerate(["a", "b"]):
    print(index, value)
    
- for index, value in enumerate(iterable):
    ...
Python 中同时获取元素索引和值的推荐写法.

# 
| 变量                        | 作用 |

| md_line_list | Markdown 文件按行拆分后的列表 |
| code_pattern | 判断当前行是否是代码围栏, 例如 " ``` " 或 " ~~~ " |
| title_pattern | 判断当前行是否是 Markdown 的 ATX 标题 |
| is_in_block | 当前是否位于代码块中 |
| marker | 当前代码块使用的围栏标记 |
| current_index | 当前待切分段落的起始位置 |
| section_list | 保存切分结果 |
| file_title | 当前 Markdown 文件的文件标题或文件名 |

# 整体处理思路:
    - 一行一行遍历 Markdown 文档.
    - 判断当前行是不是代码块开始或结束标记.
    - 标记当前是否在代码块中的状态.
    - 只有不在代码块中时, 才判断当前行是不是标题.
    - 遇到新标题时, 把"上一个标题到当前标题之前"的内容保存为一个 section.
    - 循环结束后, 手动保存最后一个 section.
    
- 这里最重要的一点是:
    当遍历到一个新标题时, 代码保存的不是这个新标题对应的内容, 而是新标题之前的那一段内容.
    因为当前标题对应的内容还没有遍历完, 所以只能先保存上一段.
'''
