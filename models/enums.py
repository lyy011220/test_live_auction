"""稳定业务枚举：角色、房间状态、竞拍状态和事件类型。"""


class Role:
    MERCHANT = 1  # 主播
    USER = 2       # 普通用户


class RoomStatus:
    CREATED = 1
    LIVE = 2
    ENDED = 3


class AuctionStatus:
    # 状态码以线上后端为准 (实跑验证): 4=已成交, 3=已流拍
    PENDING = 1    # 待开始
    LIVE = 2       # 竞拍中
    ENDED = 3      # 已流拍
    SOLD = 4       # 已成交
    CANCELLED = 5  # 已取消
    STATUS_DESC = {1: "待开始", 2: "竞拍中", 3: "已流拍", 4: "已成交", 5: "已取消"}


class EventType:
    BID = "BID"
    DELAYED = "DELAYED"
    STARTED = "STARTED"
    SOLD = "SOLD"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"
    OUTBID = "OUTBID"
    ONLINE = "ONLINE"
