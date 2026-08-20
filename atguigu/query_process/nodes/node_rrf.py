# atguigu/query_process/nodes/node_rrf.py

from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.json_format_tool import json_format
from atguigu.tool.logger import logger

class NodeRrf(NodeBase):
    """
    - 节点功能：Reciprocal Rank Fusion
    - 将多路召回的结果（向量、HyDE、Web）进行加权融合排序。
    - 把普通向量召回和 HyDE 召回的两个排名列表，根据名次而不是原始相似度进行统一融合，提升两路共同认可文档的优先级，
    并为后续精排提供最多 10 个高质量本地候选切片。
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_rrf"

    def process(self, state: QueryGraphState):

        # 获取普通向量检索的 chunks
        embedding_chunks = state.get("embedding_chunks")  # 字典.get(key, default), key: 要查找的键, default: 如果键不存在, 则返回 default 值
                                                          # 使用 get() 后可以统一在后面的 if 中处理空值, 并输出更清晰的业务错误消息
        # 调用日志对象的 info() 方法, 输出普通信息日志
        if not embedding_chunks:
            logger.info("embedding_chunks 不能为空! ")
            raise Exception("embedding_chunks 不能为空! ")

        # 获取 HyDE 向量检索的 chunks
        hyde_embedding_chunks = state.get("hyde_embedding_chunks")

        # 检查 HyDE 结果
        if not hyde_embedding_chunks:
            logger.info("hyde_embedding_chunks 不能为空! ")
            raise Exception("hyde_embedding_chunks 不能为空! ")
        # 只要其中一路为空, 整个 RRF 节点都会失败, 目前不支持"某一路无结果时, 仅使用另一条检索路".

        # 检索路线及权重
        # 创建带权检索路线, 给每一路设置权重
        weight_embedding = [
            (embedding_chunks, 1),  # 普通向量检索结果, 权重: 1; 权重的意义: 当前两路权重都是 1 , 表示这两路地位完全相同.
            (hyde_embedding_chunks, 1),  # HyDE 向量检索结果, 权重: 1; 如果 hyde 向量检索更可靠, 可以设为: 1.5, 那么在同一排名下, 它贡献的 RRF 分数会更高
        ]  # 列表list 中包含两个元素, 每个元素是一个元组tuple, 包含检索结果和权重, 即二元组(检索结果列表, 权重)
           # 使用 列表 + 元组: 后续可以使用同意循环, 无需为每一路重复写相同的逻辑; 而且未来可以添加新的检索路线及权重.

        # RRF 融合算法会在每一路都会生成一个排名, 即每一路都有自己的 1 - 10 的排名
        # 根据每路当中的排名, 计算每一个切片在这一路当中的 RRF 分数

        # 创建最终的检索结果列表
        # 该字典同时承担两个职责: 根据 id 去重; 保存每个切片累加后的 RRF 分数
        final_chunks_dict = {}  # 使用字典代替列表, 字典能够根据 chunk_id 快速判断切片是否已经出现; 如果使用列表判断重复, 就需要反复遍历列表, 效率更低.

        # 遍历每一条检索路线
        for chunks, weight in weight_embedding:  # 循环会自动进行元组解包 chunks = embedding_chunks, , weight = 1
            # 遍历当前路线中的切片
            for idx, chunk in enumerate(chunks, start=1):
                chunk_id = chunk.get("id")  # 取得切片 ID, chunk 是一个字典. chunk_id 是跨检索路线识别同一知识切片的唯一标识.
                chunk_score = weight / (60 + idx)  # 计算当前路线的 RRF 分数

                # 去重与分数累加, 如果两路有重复的 chunk_id, 则分数需要相加

                # 需要判断 final_chunks_dict 当中 是否已经存在这个 chunk_id?
                # - 如果已经存在, 代表之前的那一路检索结果已经存在这个 chunk_id, 需要将当前的 chunk_score 累加到之前已经存在的分数中;
                # - 如果不存在, 则新建一个键值对, 以chunk_id为键, 以chunk为值.
                if chunk_id in final_chunks_dict:  # # 若为 True, 表示当前切片已经在之前的检索路线或当前路线中出现过
                    final_chunks_dict.get(chunk_id)["score"] += chunk_score  # 累加重复切片的得分
                    # 主要意味着: 同一个切片同时被普通向量检索和 HyDE 检索召回

                else :  # 如果 chunk_id 尚未存在于 final_chunks_dict 中, 则执行这个分支
                    chunk["score"] = chunk_score  # 把当前切片的 "score" 字段设置为刚计算的 RRF 分数
                    final_chunks_dict[chunk_id] = chunk  # 保存切片

            # 从 final_chunks_dict 中取出所有文档，读取每条文档的 score 字段，按照分数从高到低排序，并返回一个新的文档列表。
        rrf_chunks = sorted(
            final_chunks_dict.values(),  # 取得字典内所有的文档值, 返回 dict_values 视图对象, 严格来说，values() 返回的不是普通列表，而是一个 dict_values 视图对象
            key=lambda x: x["score"],  # 指定排序依据是每个文档字典的 score; 即排序时, 不直接比较整个文档字典, 而是比较每个文档的 score 字段。
             reverse=True,
        )  # rrf_chunks 的类型是 list[dict]

        # 返回当前节点的输出状态片段, 返回值类型: dict[str, list[dict]]
        return {
            "rrf_chunks": rrf_chunks[:10]
        }


if __name__ == '__main__':
    mock_state = {
        "embedding_chunks": [
            {
                "content": "## 设备\n\n![设备需放置于平稳通风处，避免震动；搬运时双手托底，勿触危险区域；使用后断电，注意纸张边缘锋利。](http://192.168.100.88:9000/knowledge-base/upload-images/5067b2891ca4f761e2874921e0eb433aa742afbf38ca8dc509afecbf0aa6a6b5.jpg)",
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788527,
                "title": "## 设备",
                "file_title": "hak180产品安全手册",
                "score": 0.8365353345870972,
                "source": "local"
            },
            {
                "content": "## 设备\n\n![设备使用需注意防火、防触电，避免儿童接触塑料袋，使用后待冷却再开盖，防止烧伤。](http://192.168.100.88:9000/knowledge-base/upload-images/f3349cded08d6686a93d0a81b9a64ec1e50d9a82cbb88541b37027f085813a15.jpg)  \n儎⑟ഴḽ䆜઀ᛞ࠽व䀜᪮儎⑟Ⲻ䇴༽䜞ԬȾ",
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788521,
                "title": "## 设备",
                "file_title": "hak180产品安全手册",
                "score": 0.8357506990432739,
                "source": "local"
            },
            {
                "content": "## HAK 180 烫金机\n\n产品安全手册（简体中文）\n\n感谢您购买 HAK 180 烫金机。\n\n在使用本设备之前，请先阅读本手册，包括所有预防措施。阅读本手册后，请妥善保管。\n\n有关使用本设备的更多信息，请参阅使用说明书，其可在兄弟 (中国)商业有限公司技术服务支持网站 http://www.95105369.com/Web/Manuals.aspx 上找到。建议您先通读使用说明书，再使用本设备。\n\n如需获得常见问题解答、故障排除和说明书，请访问\n\nhttp://www.95105369.com。\n\n对于本设备所有者不遵守本指南中规定的说明操作而导致的损害，Brother 不承担任何责任。",
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788513,
                "title": "## HAK 180 烫金机",
                "file_title": "hak180产品安全手册",
                "score": 0.8348144292831421,
                "source": "local"
            },
            {
                "content": "## 设备\n\n•\t将本设备放置在平整、水平且稳定的表面上（如桌面），避免震动和冲击。\n\n•\t将本设备放置在通风良好的环境中。\n\n•\t为了防止人员受伤，请谨慎操作，避免将手指放置在图中所示的区域中。\n\n![本设备需接地使用，放置于平稳通风处，避免灰尘堆积和手指误入危险区域，搬运时用双手抓稳。](http://192.168.100.88:9000/knowledge-base/upload-images/c61a7f4e923881679f747508ae309c39dc221685344b068009256b1b3a40cc00.jpg)",
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788526,
                "title": "## 设备",
                "file_title": "hak180产品安全手册",
                "score": 0.8334813117980957,
                "source": "local"
            },
            {
                "content": "## HAK 180 烫金机\n\n•\t对于保养、调整或维修事宜，请联系 Brother 呼叫中心或您当地的Brother 经销商。\n\n•\t如果本设备工作不正常或发生任何错误，请关闭本设备，拔下所有电缆，然后联系 Brother 呼叫中心或您当地的 Brother 经销商。\n\n•\t本文档中提供的信息可能会随时更改，恕不另行通知。\n\n•\t严禁未经授权擅自复制或重制本文档的任何部分或全部内容。\n\n•\t请注意，对于使用通过本设备制作的产品造成的任何损坏或利润损失，或者故障、维修导致的数据消失或更改，或者第三方提出的任何索赔，我们不承担任何责任。",
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788514,
                "title": "## HAK 180 烫金机",
                "file_title": "hak180产品安全手册",
                "score": 0.8282943367958069,
                "source": "local"
            },
            {
                "content": "## 为设备选择一个安全的位置\n\n![确保设备放置平稳，远离边缘，使用时勿将手伸入纸张边缘，搬运需双手托底，避免跌落造成伤害或损坏。](http://192.168.100.88:9000/knowledge-base/upload-images/cc5ee1ac24ebb2707d40dc7a234a8b243f55f5bf08fabc683859be6fdf096ffa.jpg)  \n确保本设备的任何部位均未伸出设备所在的桌面或支架。特别是当本设备位于桌面、支架等边缘时，请勿让出纸盒打开。确保本设备位于平整、水平且稳定的表面上，避免震动。不遵守这些预防措施可能导致设备跌落，从而导致用户的人身伤害以及设备严重损坏。",
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788530,
                "title": "## 为设备选择一个安全的位置",
                "file_title": "hak180产品安全手册",
                "score": 0.821736216545105,
                "source": "local"
            },
            {
                "content": "## 设备\n\n•\t请勿拆解本设备。拆解本设备可能会导致火灾或触电。\n\n•\t请勿尝试自行维修本设备。打开或拆下盖子可能使您接触到危险电压点以及带来其他风险，并且可能使您的保修失效。对于所有维修事宜，请联系 Brother 呼叫中心或您当地的 Brother 经销商。\n\n•\t请在以下环境使用本设备：温度保持在 10 °C 和 32 °C 之间，湿度保持在 20% 和 80% 之间，无冷凝。\n\n•\t请勿使本设备受到阳光直射、过热、接触明火、腐蚀性气体、湿气或灰尘。否则可能产生触电、短路或火灾的风险，从而导致损坏设备和/或导致设备无法运行。\n\n•\t请勿将设备放在加热器、空调、电风扇或水附近。",
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788517,
                "title": "## 设备",
                "file_title": "hak180产品安全手册",
                "score": 0.8214781284332275,
                "source": "local"
            },
            {
                "content": "![HAK 180烫金机产品安全手册，含使用前须知、安全提示及获取说明书的官方网址。](http://192.168.100.88:9000/knowledge-base/upload-images/677a08ee041965bbbdb6b483d6c17d5aaa36a26b6dc96870a2019f0307b8616f.jpg)  \nD01WD7001-00\n\nSCHN\n",
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788512,
                "title": "无标题",
                "file_title": "hak180产品安全手册",
                "score": 0.8197594881057739,
                "source": "local"
            },
            {
                "content": "## 设备\n\n•\t请先阅读这本手册，再尝试操作本设备或尝试进行任何维护。不按照这些说明操作可能会提高发生人员受伤或财产损坏（包括火灾、触电、烧伤或窒息所致）的风险。对于本设备所有者不遵守本指南中规定的说明操作而导致的损害，Brother 不承担任何责任。\n\n•\t请勿在未去除所有包装材料的情况下使用本设备，包括本设备内部的任何附加的包装材料。否则可能会产生火灾的风险。\n\n•\t请勿拆解本设备。拆解本设备可能会导致火灾或触电。",
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788516,
                "title": "## 设备",
                "file_title": "hak180产品安全手册",
                "score": 0.8149991631507874,
                "source": "local"
            },
            {
                "content": "## 设备\n\n![使用起搏器者需远离设备，注意高温部件防烫伤；设备须接220-240V交流电，禁用直流电源，防止触电或火灾。](http://192.168.100.88:9000/knowledge-base/upload-images/501bb8d2d681e4502d87badb15a68939eadfa086d309c3599f1c36b0bc559177.jpg)",
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788522,
                "title": "## 设备",
                "file_title": "hak180产品安全手册",
                "score": 0.8141647577285767,
                "source": "local"
            }
        ],
        "hyde_embedding_chunks": [
            {
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788521,
                "title": "## 设备",
                "file_title": "hak180产品安全手册",
                "content": "## 设备\n\n![设备使用需注意防火、防触电，避免儿童接触塑料袋，使用后待冷却再开盖，防止烧伤。](http://192.168.100.88:9000/knowledge-base/upload-images/f3349cded08d6686a93d0a81b9a64ec1e50d9a82cbb88541b37027f085813a15.jpg)  \n儎⑟ഴḽ䆜઀ᛞ࠽व䀜᪮儎⑟Ⲻ䇴༽䜞ԬȾ",
                "score": 0.8589839935302734,
                "source": "local"
            },
            {
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788527,
                "title": "## 设备",
                "file_title": "hak180产品安全手册",
                "content": "## 设备\n\n![设备需放置于平稳通风处，避免震动；搬运时双手托底，勿触危险区域；使用后断电，注意纸张边缘锋利。](http://192.168.100.88:9000/knowledge-base/upload-images/5067b2891ca4f761e2874921e0eb433aa742afbf38ca8dc509afecbf0aa6a6b5.jpg)",
                "score": 0.8577708005905151,
                "source": "local"
            },
            {
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788526,
                "title": "## 设备",
                "file_title": "hak180产品安全手册",
                "content": "## 设备\n\n•\t将本设备放置在平整、水平且稳定的表面上（如桌面），避免震动和冲击。\n\n•\t将本设备放置在通风良好的环境中。\n\n•\t为了防止人员受伤，请谨慎操作，避免将手指放置在图中所示的区域中。\n\n![本设备需接地使用，放置于平稳通风处，避免灰尘堆积和手指误入危险区域，搬运时用双手抓稳。](http://192.168.100.88:9000/knowledge-base/upload-images/c61a7f4e923881679f747508ae309c39dc221685344b068009256b1b3a40cc00.jpg)",
                "score": 0.848399817943573,
                "source": "local"
            },
            {
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788514,
                "title": "## HAK 180 烫金机",
                "file_title": "hak180产品安全手册",
                "content": "## HAK 180 烫金机\n\n•\t对于保养、调整或维修事宜，请联系 Brother 呼叫中心或您当地的Brother 经销商。\n\n•\t如果本设备工作不正常或发生任何错误，请关闭本设备，拔下所有电缆，然后联系 Brother 呼叫中心或您当地的 Brother 经销商。\n\n•\t本文档中提供的信息可能会随时更改，恕不另行通知。\n\n•\t严禁未经授权擅自复制或重制本文档的任何部分或全部内容。\n\n•\t请注意，对于使用通过本设备制作的产品造成的任何损坏或利润损失，或者故障、维修导致的数据消失或更改，或者第三方提出的任何索赔，我们不承担任何责任。",
                "score": 0.8472815752029419,
                "source": "local"
            },
            {
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788522,
                "title": "## 设备",
                "file_title": "hak180产品安全手册",
                "content": "## 设备\n\n![使用起搏器者需远离设备，注意高温部件防烫伤；设备须接220-240V交流电，禁用直流电源，防止触电或火灾。](http://192.168.100.88:9000/knowledge-base/upload-images/501bb8d2d681e4502d87badb15a68939eadfa086d309c3599f1c36b0bc559177.jpg)",
                "score": 0.8405383229255676,
                "source": "local"
            },
            {
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788517,
                "title": "## 设备",
                "file_title": "hak180产品安全手册",
                "content": "## 设备\n\n•\t请勿拆解本设备。拆解本设备可能会导致火灾或触电。\n\n•\t请勿尝试自行维修本设备。打开或拆下盖子可能使您接触到危险电压点以及带来其他风险，并且可能使您的保修失效。对于所有维修事宜，请联系 Brother 呼叫中心或您当地的 Brother 经销商。\n\n•\t请在以下环境使用本设备：温度保持在 10 °C 和 32 °C 之间，湿度保持在 20% 和 80% 之间，无冷凝。\n\n•\t请勿使本设备受到阳光直射、过热、接触明火、腐蚀性气体、湿气或灰尘。否则可能产生触电、短路或火灾的风险，从而导致损坏设备和/或导致设备无法运行。\n\n•\t请勿将设备放在加热器、空调、电风扇或水附近。",
                "score": 0.8397265672683716,
                "source": "local"
            },
            {
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788516,
                "title": "## 设备",
                "file_title": "hak180产品安全手册",
                "content": "## 设备\n\n•\t请先阅读这本手册，再尝试操作本设备或尝试进行任何维护。不按照这些说明操作可能会提高发生人员受伤或财产损坏（包括火灾、触电、烧伤或窒息所致）的风险。对于本设备所有者不遵守本指南中规定的说明操作而导致的损害，Brother 不承担任何责任。\n\n•\t请勿在未去除所有包装材料的情况下使用本设备，包括本设备内部的任何附加的包装材料。否则可能会产生火灾的风险。\n\n•\t请勿拆解本设备。拆解本设备可能会导致火灾或触电。",
                "score": 0.8373287916183472,
                "source": "local"
            },
            {
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788513,
                "title": "## HAK 180 烫金机",
                "file_title": "hak180产品安全手册",
                "content": "## HAK 180 烫金机\n\n产品安全手册（简体中文）\n\n感谢您购买 HAK 180 烫金机。\n\n在使用本设备之前，请先阅读本手册，包括所有预防措施。阅读本手册后，请妥善保管。\n\n有关使用本设备的更多信息，请参阅使用说明书，其可在兄弟 (中国)商业有限公司技术服务支持网站 http://www.95105369.com/Web/Manuals.aspx 上找到。建议您先通读使用说明书，再使用本设备。\n\n如需获得常见问题解答、故障排除和说明书，请访问\n\nhttp://www.95105369.com。\n\n对于本设备所有者不遵守本指南中规定的说明操作而导致的损害，Brother 不承担任何责任。",
                "score": 0.7339262962341309,
                "source": "local"
            },
            {
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788512,
                "title": "无标题",
                "file_title": "hak180产品安全手册",
                "content": "![HAK 180烫金机产品安全手册，含使用前须知、安全提示及获取说明书的官方网址。](http://192.168.100.88:9000/knowledge-base/upload-images/677a08ee041965bbbdb6b483d6c17d5aaa36a26b6dc96870a2019f0307b8616f.jpg)  \nD01WD7001-00\n\nSCHN\n",
                "score": 0.7225326895713806,
                "source": "local"
            },
            {
                "item_name": "BrotherHAK180烫金机",
                "id": 468273558621788530,
                "title": "## 为设备选择一个安全的位置",
                "file_title": "hak180产品安全手册",
                "content": "## 为设备选择一个安全的位置\n\n![确保设备放置平稳，远离边缘，使用时勿将手伸入纸张边缘，搬运需双手托底，避免跌落造成伤害或损坏。](http://192.168.100.88:9000/knowledge-base/upload-images/cc5ee1ac24ebb2707d40dc7a234a8b243f55f5bf08fabc683859be6fdf096ffa.jpg)  \n确保本设备的任何部位均未伸出设备所在的桌面或支架。特别是当本设备位于桌面、支架等边缘时，请勿让出纸盒打开。确保本设备位于平整、水平且稳定的表面上，避免震动。不遵守这些预防措施可能导致设备跌落，从而导致用户的人身伤害以及设备严重损坏。",
                "score": 0.7127029299736023,
                "source": "local"
            }
        ]
    }
    node_rrf = NodeRrf()
    result = node_rrf(mock_state)
    logger.info(json_format(result))



"""
这个文件实现的是 RAG 查询链路中的 RRF 多路召回融合节点。
它接收普通向量检索结果和 HyDE 检索结果，
先校验两路数据是否存在，然后分别根据文档在各自结果列表中的排名计算 weight / (rank + 60) 的倒数排名分数。
对于两路结果中重复出现的文档，使用文档唯一 ID 作为 key，将它在不同召回路径中的分数累加。
最后按照融合分数倒序排列，截取前 10 条，以 rrf_chunks 字段返回给下游重排序节点。
这个节点的价值在于不直接比较不同检索通道的原始分数，而是统一使用排名进行融合，同时能够提升被多路检索共同召回的文档的优先级。


# 核心工作是：
- 接收普通向量检索结果 embedding_chunks 。
- 接收 HyDE 向量检索结果 hyde_embedding_chunks 。
- 分别根据文档在各自召回列表中的排名计算 RRF 分数。
- 如果同一个文档同时出现在两路检索结果中，就把两路分数累加。
- 按最终融合分数从高到低排序。
- 截取前 10 条，传递给下游的重排序节点。


# 常量 60 的作用: 60 是 RRF 中常用的平滑常数 k 。
  公式: score = weight / (rank + k)
  使用平滑常数的目的：
    - 防止第 1 名与后续排名的分差过大。
    - 让多路检索中重复出现的结果得到更稳定的加分。
    - 减少某一路排名略微波动造成的影响。
    
    
# sorted() 函数
- sorted() 是 Python 内置排序函数。

- 基本形式：sorted(iterable, key=None, reverse=False)

- 参数：
    - iterable ：要排序的可迭代对象。
    - key ：用于提取排序依据的函数。
    - reverse ：是否反向排序。默认值为 False，即升序排列。如果设置为 True，则按降序排列。
- 返回值: list
- 注意: 
    - sorted() 创建并返回新列表。
    - 不会修改传入的 dict_values 。
    - 与列表自带的 list.sort() 不同， list.sort() 会原地修改列表并返回 None 。
    - Python 的 sorted() 是稳定排序。如果两条文档分数完全相同，会维持它们进入 final_chunks_dict 时的先后顺序。
    
    
# lambda 匿名函数 : key=lambda x: x["score"]
- 表示: 排序时，不直接比较整个文档字典，而是比较每个文档的 score 字段。

- lambda x: x["score"]等价于:

    def get_score(x):
        return x["score"]

- x 代表 当前正在处理的一条文档。
例如: 排序过程中可能依次执行：x = {"id": 101, "content": "文档A", "score": 0.02}
     执行: x["score"]
     得到: 0.02
     然后: x = {"id": 102, "content": "文档B", "score": 0.04}
     执行: x["score"]
     得到: 0.04


# 假设前面经过融合后，final_chunks_dict 是这样的：
    final_chunks_dict = {
        101: {
            "id": 101,
            "content": "文档A",
            "score": 0.02
        },
        102: {
            "id": 102,
            "content": "文档B",
            "score": 0.04
        },
        103: {
            "id": 103,
            "content": "文档C",
            "score": 0.01
        }
    }
其中:101 / 102 / 103 是字典的键, 文档字典是值.
调用: final_chunks_dict.values() 表示只取字典中的所有值，不要键。
得到的逻辑内容相当于: 
    [
    {"id": 101, "content": "文档A", "score": 0.02},
    {"id": 102, "content": "文档B", "score": 0.04},
    {"id": 103, "content": "文档C", "score": 0.01}
    ]
严格来说，values() 返回的不是普通列表，而是一个 dict_values 视图对象：dict_values([...]), 它是可迭代对象，可以交给 sorted() 遍历.

# final_chunks_dict.values()的例子:
    {
    "content": "## 设备\n\n![设备需放置于平稳通风处，避免震动；搬运时双手托底，勿触危险区域；使用后断电，注意纸张边缘锋利。](http://192.168.100.88:9000/knowledge-base/upload-images/5067b2891ca4f761e2874921e0eb433aa742afbf38ca8dc509afecbf0aa6a6b5.jpg)",
    "item_name": "BrotherHAK180烫金机",
    "id": 468273558621788527,
    "title": "## 设备",
    "file_title": "hak180产品安全手册",
    "score": 0.8365353345870972,
    "source": "local"
    }


# 每个文档字典的字段含义如下：
- 字段	    类型	        作用
id	        int	    文档块唯一 ID，用于跨检索路去重
content	    str	    文档正文或切片内容
title	    str	    文档章节标题
file_title	str	    文件名称
item_name	str	    知识库对象或产品名称
source	    str	    数据来源，例如 local
score	    float	上游检索原始分数；进入该节点后会被 RRF 分数覆盖


# 整体执行流程:
上游向量检索 / HyDE 检索
        ↓
将两路有序文档列表写入 QueryGraphState
        ↓
NodeRrf.process() 读取两路结果
        ↓
检查两路结果是否为空
        ↓
按每路排名计算 weight / (rank + 60)
        ↓
以 id 去重；重复文档累计分数
        ↓
按累计 RRF 分数降序排序
        ↓
截取前 10 条，返回 rrf_chunks
        ↓
交给后续 Rerank 节点进一步精排

- 该设计的核心思想是：单路排名靠前有贡献，多路同时命中的文档会获得多次贡献，因此更容易进入最终前列


# 一次完整的 node_rrf 执行过程:
1. 创建 NodeRrf 实例
2. 父类检查节点是否设置 name = "node_rrf"
3. LangGraph 或测试代码调用 node_rrf(state)
4. 进入 NodeBase.__call__()
5. 输出“node_rrf 开始执行”日志
6. 调用 NodeRrf.process(state)
7. 从 state 读取 embedding_chunks
8. 从 state 读取 hyde_embedding_chunks
9. 检查两路结果是否非空
10. 为普通检索和 HyDE 检索分别设置权重 1
11. 创建以 chunk_id 为键的去重字典
12. 遍历普通向量检索结果
13. 根据排名计算每条结果的 RRF 分数
14. 将切片写入融合字典
15. 遍历 HyDE 检索结果
16. 对重复 ID 累加第二路 RRF 分数
17. 对仅在 HyDE 中出现的切片新增记录
18. 提取融合字典中的所有切片
19. 按累计 score 从高到低排序
20. 截取前 10 条
21. 返回 {"rrf_chunks": [...]}
22. 父类输出“node_rrf 结束执行”日志
23. LangGraph 将 rrf_chunks 合并到共享状态
24. NodeRerank 读取 rrf_chunks 和 web_search_docs
25. 继续执行统一重排序


# 实际执行链
用户问题
  ↓
NodeItemNameConfirm
确认商品名称、改写查询
  ↓
如果已经能直接回答
  └────────────────────→ NodeAnswerOutput → END

如果还需要检索
  ↓
三路并行执行
  ├─ NodeSearchEmbedding
  │    输出 embedding_chunks
  │
  ├─ NodeSearchEmbeddingHyde
  │    输出 hyde_embedding_chunks
  │
  └─ NodeWebSearchMcp
       输出 web_search_docs
  ↓
NodeRrf
  ├─ 融合 embedding_chunks
  ├─ 融合 hyde_embedding_chunks
  └─ 输出 rrf_chunks
  ↓
NodeRerank
  ├─ 合并 rrf_chunks
  ├─ 合并 web_search_docs
  ├─ 使用重排模型重新打分
  └─ 输出 reranked_docs
  ↓
NodeAnswerOutput
  ↓
END
"""




