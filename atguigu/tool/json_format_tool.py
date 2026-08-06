import json


def json_format(data):
    return json.dumps(data, ensure_ascii=False, indent=4)


"""
# 核心作用: 把 Python 数据转换成中文可读 / 带四空格缩进的 JSON 字符串, 方便记录日志和调试程序.

# json_format_tool 是一个简单的 JSON 格式化工具模块 .
- 它把 Python 数据转换成: - JSON 字符串 / - 支持中文直接显示 / - 带缩进、便于阅读
- 主要用于格式化日志或调试输出.

# 常用方法包括: 
    json.dumps()  # Python 对象 → JSON 字符串, 将 Python 对象转换为 JSON 字符串
    json.loads()  # JSON 字符串 → Python 对象, 从字符串读取 JSON
    json.dump()   # Python 对象 → JSON 文件, 将 Python 对象写入文件
    json.load()   # JSON 文件 → Python 对象, 从文件读取 JSON
    
# 序列化: 程序对象 → 可存储、可传输的数据, python -> json
  反序列化: 可存储、可传输的数据 → 程序对象, json -> python

# json_format 函数作用: 
接收一个 Python 数据对象, 将其序列化成格式美观的 JSON 字符串并返回.

- 函数本身不会: 修改传入的数据 / 打印数据 / 写入文件
它只负责转换并返回字符串.

# 参数说明
- data
    - data 是需要转换成 JSON 字符串的 Python 对象.

- json.dumps() 的作用
    - 将 Python 对象序列化为 JSON 字符串

- 参数: ensure_ascii=False 作用是保留中文, 而不是转换成 Unicode 编码.
    - 控制非 ASCII 字符是否转换为 Unicode 转义形式.
    - 主要作用是让中文内容能够直接显示, 特别适合中文日志.
    - 默认值为 True, 即将非 ASCII 字符转换为 Unicode 转义形式.
    - 可以通过设置 ensure_ascii=False 来保持中文直接显示.
    - 如果不设置或设置为 True : 则非 ASCII 字符会被转换为 Unicode 转义形式, 例如: \u4e2d 表示中文 "中".
    - 例如: json.dumps({"name": "尚硅谷"})
    输出结果可能是: {"name": "\u5c1a\u7845\u8c37"}

- 参数: indent=4
    - 指定 JSON 的缩进空格数.
    - 默认值为 4, 即每个层级缩进 4 个空格.
    - 可以通过设置 indent 来调整缩进宽度.
    - 不设置缩进时, 结果通常显示在一行, 更适合人工阅读和排查问题.

# 返回值
    - json_format 函数返回一个 JSON 格式的 Python 字符串, 即返回值类型为 str.
    - 需要注意: 它返回的不是字典, 而是字典序列化后的字符串.
    
# 注意：
JSON 由键值对组成：
    - 属性名必须使用双引号 "...".
    - 字符串必须使用双引号, 不能使用单引号.
    - 最后一个属性后不能有逗号.
    - JSON 本身不支持注释.
    - JSON 文件通常使用 .json 扩展名.
"""
