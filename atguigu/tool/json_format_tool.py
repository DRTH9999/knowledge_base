import json
from bson import ObjectId  # 从 bson 包中导入 ObjectId 类. ObjectId 通常用于 MongoDB 文档的 _id 字段
                           # 如果没有导入 ObjectId, Python 不知道这里的 ObjectId 是什么, 会抛出: NameError: name 'ObjectId' is not defined
                           # # ObjectId 是 MongoDB 中常见的唯一标识符类型.


class ObjectIdEncoder(json.JSONEncoder):  # 定义一个名为 ObjectIdEncoder 的类, 并让它继承 json.JSONEncoder.
                                          # 这样 ObjectIdEncoder 就可以作为 JSON 编码器使用.
    def default(self, obj):
        '''
        # 重写父类的 default() 方法. 当 JSONEncoder 遇到不能直接序列化的对象时, 会调用 default(obj), 让自定义编码器决定如何处理这个对象
        :param obj: 表示当前无法被标准 JSON 编码器直接处理的对象
        :return: 如果 obj 是 ObjectId, 返回: str ; 如果不是 ObjectId, 当前方法调用父类处理, 父类通常会抛出 TypeError, 而不是正常返回.
        '''
        if isinstance(obj, ObjectId):  # 判断 obj 是否为 ObjectId 类型或其子类的实例
            return str(obj)  # 调用 Python 内置的 str() 函数, 把 ObjectId 强制转换成字符串, 并立即从 default() 方法返回.
        # 父类默认处理
        return super().default(obj)  # 如果 obj 不是 ObjectId, 则将它交回父类 json.JSONEncoder 的 default() 方法处理.
                                     # super() 用于访问父类的方法. 当前类继承关系为: ObjectIdEncoder -> json.JSONEncoder
                                     # super().default(obj) : 可以理解为调用父类版本的 json.JSONEncoder 的 default() 方法.
                                     # 如果是我明确支持的 ObjectId, 我来处理; 如果不是, 就交给父类按标准规则处理.

def json_format(data):  # 定义一个名为 json_format 的函数, 用于将传入的 Python 数据转换成格式化 JSON 字符串.
    return json.dumps(
        data,
        ensure_ascii=False,
        indent=4,
        cls=ObjectIdEncoder,  # 告诉 json.dumps() 使用哪个 JSON 编码器类处理 ObjectId
                              # 默认情况下, 相当于使用: cls=json.JSONEncoder, 但是标准编码器不支持 ObjectId , 所以设置cls=ObjectId
                              # 以后, json.dumps() 会创建自定义编码器实例, 并使用它进行编码.
    )


"""
# 核心作用: 把 Python 数据转换成中文可读 / 带四空格缩进的 JSON 字符串, 并额外支持 MongoDB / BSON 的 ObjectId对象 方便记录日志和调试程序.

# 标准 json.JSONEncoder 不支持 BSON 的 ObjectId. 因此继承 json.JSONEncoder 并重写 default() 方法: 
当遇到 ObjectId 时, 将其转换为 JSON 支持的 str; 其他未知类型仍交给父类处理. 
之后，json_format() 通过 json.dumps(..., cls=NumpyEncoder) 使用这个自定义编码器, 最终返回 JSON 字符串.

# 为什么转换成字符串?
    - JSON 不支持 ObjectId 类型, 但支持字符串. 因此需要把 ObjectId 转换成字符串, 才能被 JSON 编码器处理.

# json_format_tool 是一个简单的 JSON 格式化工具模块 .
- 它把 Python 数据转换成: - JSON 字符串 / - 支持中文直接显示 / - 带缩进、便于阅读
- 主要用于格式化日志或调试输出.

# Python 标准库 json 默认只能直接序列化以下常见类型:
    Python 类型	        JSON 类型
    dict	            object
    list / tuple        array
    str	                string
    int / float	        number
    True / False	    true / false
    None	            null

- MongoDB 的 ObjectId 不属于 Python 标准 JSON 编码器支持的类型, 因此需要自定义编码器 NumpyEncoder 来处理.
当前代码通过继承 json.JSONEncoder, 在遇到 ObjectId 时将其转换成字符串, 从而解决这个问题.


# 常用方法包括: 
    json.dumps()  # Python 对象 → JSON 字符串, 将 Python 对象转换为 JSON 字符串
    json.loads()  # JSON 字符串 → Python 对象, 从字符串读取 JSON
    json.dump()   # Python 对象 → JSON 文件, 把 Python 对象转换成 JSON, 并直接写入文件对象.
    json.load()   # JSON 文件 → Python 对象, 从文件对象中读取 JSON 内容, 并转换成 Python 对象.

    
# 序列化: Python 程序对象 → 可存储、可传输的JSON 数据, python -> json
  反序列化: 可存储、可传输的 JSON 数据 →  Python 程序对象, json -> python

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
    
# isinstance(object, classinfo) 语法
    - object:要判断的对象
    - classinfo: 类型 / 类,或者由多个类型组成的元组
    - 返回值:True 或 False

# 为什么要继承 json.JSONEncoder ?
    - json.JSONEncoder 是 Python 标准库 json 模块中定义的 JSON 编码器类, 已经实现了完整的 JSON 编码逻辑, 
    当前需求只是让编码器额外认识 ObjectId , 没有必要重新编写整个 JSON 序列化系统.
    因此采用继承 json.JSONEncoder 的方式, 只需要重写 default 方法, 添加对 ObjectId 的处理逻辑即可.
    
# 为什么方法名必须是 default?
    - 因为这是 json.JSONEncoder 预先定义好的扩展接口. 只有方法名是 default, 才能被 json.JSONEncoder 调用.
    - 父类内部大致会执行类似逻辑:
    
      if 对象是JSON支持的标准类型:
        直接编码
      else:
        调用 self.default(obj)
        
# 为什么需要调用父类?
    - 这能够保留标准编码器的默认错误处理行为. 如果对象既不是标准 JSON 类型, 也不是 ObjectId, 父类的 default() 通常会抛出: TypeError
    
# super().default(obj)的逻辑:
      如果是 ObjectId：转换成字符串;
      如果不是 ObjectId: 交给父类按默认规则处理;
      如果父类也不支持: 抛出 TypeError.
      因此, 这个编码器并不是把所有未知对象都转换成字符串, 而是只对 ObjectId 进行特殊处理.
    
 json_format(data)
     ↓
 json.dumps(data, cls=NumpyEncoder)
     ↓
 NumpyEncoder 开始递归编码 data
     ↓
 遇到 dict、list、str、int 等标准类型
     ↓
 直接序列化
     ↓
 遇到 ObjectId，标准编码器无法处理
    ↓
 调用重写后的 default(obj)
     ↓
 判断 obj 是 ObjectId
     ↓
 通过 str(obj) 转成字符串
     ↓
 字符串是 JSON 支持的类型
     ↓
 编码器继续完成序列化
     ↓
 返回 JSON 字符串
"""
