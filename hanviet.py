#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chuyen ten rieng pinyin con sot trong ban dich -> am Han Viet co dau, de DONG NHAT.
"""
import re

# Hán tự (CJK) -> âm Hán Việt, dùng làm fallback khi dịch máy thất bại
HANZI_HV: dict[str, str] = {
    # Số đếm
    '一':'Nhất','二':'Nhị','三':'Tam','四':'Tứ','五':'Ngũ',
    '六':'Lục','七':'Thất','八':'Bát','九':'Cửu','十':'Thập',
    '百':'Bách','千':'Thiên','万':'Vạn','萬':'Vạn','零':'Linh',
    # Đại từ/hư từ
    '我':'Ngã','你':'Nễ','他':'Tha','她':'Tha','它':'Tha',
    '的':'Đích','了':'Liễu','是':'Thị','不':'Bất','在':'Tại',
    '有':'Hữu','无':'Vô','無':'Vô','和':'Hòa','与':'Dữ','與':'Dữ',
    '之':'Chi','其':'Kỳ','以':'Dĩ','于':'Vu','於':'Vu','而':'Nhi',
    '为':'Vi','為':'Vi','被':'Bị','让':'Nhượng','讓':'Nhượng',
    '这':'Giá','那':'Na','此':'Thử','也':'Dã','都':'Đô',
    '就':'Tựu','才':'Tài','又':'Hựu','再':'Tái','已':'Dĩ',
    '但':'Đản','如':'Như','若':'Nhược','因':'Nhân','所':'Sở',
    '当':'Đương','當':'Đương','可':'Khả','能':'Năng','会':'Hội','會':'Hội',
    '要':'Yếu','想':'Tưởng','知':'Tri','自':'Tự','己':'Kỷ',
    '还':'Hoàn','還':'Hoàn','从':'Tòng','從':'Tòng','对':'Đối','對':'Đối',
    '向':'Hướng','比':'Tỷ','等':'Đẳng','更':'Canh','最':'Tối',
    '很':'Ngân','非':'Phi','竟':'Cánh','然':'Nhiên','虽':'Tuy','雖':'Tuy',
    '或':'Hoặc','并':'Tính','並':'Tính','且':'Thả','者':'Giả','何':'Hà',
    '已':'Dĩ','却':'Khước','卻':'Khước','只':'Chỉ','便':'Tiện','即':'Tức',
    # Phương vị / không-thời gian
    '上':'Thượng','下':'Hạ','中':'Trung','前':'Tiền','后':'Hậu','後':'Hậu',
    '左':'Tả','右':'Hữu','内':'Nội','外':'Ngoại','间':'Gian','間':'Gian',
    '东':'Đông','東':'Đông','西':'Tây','南':'Nam','北':'Bắc',
    '天':'Thiên','地':'Địa','年':'Niên','月':'Nguyệt','日':'Nhật',
    '时':'Thời','時':'Thời','世':'Thế','界':'Giới','域':'Vực','境':'Cảnh',
    # Con người / gia đình
    '人':'Nhân','男':'Nam','女':'Nữ','子':'Tử','儿':'Nhi','兒':'Nhi',
    '父':'Phụ','母':'Mẫu','妈':'Mã','媽':'Mã','爸':'Bá',
    '兄':'Huynh','弟':'Đệ','姐':'Tỷ','妹':'Muội',
    '夫':'Phu','妻':'Thê','婆':'Bà','翁':'Ông',
    '孙':'Tôn','孫':'Tôn','祖':'Tổ','宗':'Tông','族':'Tộc',
    '岳':'Nhạc','舅':'Cậu','婶':'Thẩm','姑':'Cô','叔':'Thúc',
    '老':'Lão','青':'Thanh','幼':'Ấu','童':'Đồng',
    # Danh xưng / tước vị
    '王':'Vương','帝':'Đế','皇':'Hoàng','公':'Công','侯':'Hầu','伯':'Bá',
    '将':'Tướng','將':'Tướng','军':'Quân','軍':'Quân','士':'Sĩ',
    '官':'Quan','臣':'Thần','主':'Chủ','君':'Quân','令':'Lệnh',
    '师':'Sư','師':'Sư','徒':'Đồ','圣':'Thánh','聖':'Thánh',
    '总':'Tổng','總':'Tổng','长':'Trưởng','長':'Trưởng',
    # Thiên nhiên
    '水':'Thủy','火':'Hỏa','木':'Mộc','金':'Kim','土':'Thổ',
    '风':'Phong','風':'Phong','雷':'Lôi','云':'Vân','雲':'Vân','雨':'Vũ',
    '山':'Sơn','河':'Hà','海':'Hải','湖':'Hồ','江':'Giang','川':'Xuyên',
    '花':'Hoa','草':'Thảo','树':'Thụ','樹':'Thụ','林':'Lâm','森':'Sâm',
    '石':'Thạch','玉':'Ngọc','铁':'Thiết','鐵':'Thiết',
    # Sinh vật
    '龙':'Long','龍':'Long','虎':'Hổ','鱼':'Ngư','魚':'Ngư',
    '鸟':'Điểu','鳥':'Điểu','马':'Mã','馬':'Mã','牛':'Ngưu','羊':'Dương',
    '猫':'Miêu','狗':'Cẩu','狼':'Lang','熊':'Hùng','蛇':'Xà',
    # Thần thánh / tu tiên
    '神':'Thần','魔':'Ma','仙':'Tiên','妖':'Yêu','鬼':'Quỷ','佛':'Phật',
    '道':'Đạo','灵':'Linh','靈':'Linh','魂':'Hồn','气':'Khí','氣':'Khí',
    '法':'Pháp','术':'Thuật','術':'Thuật','技':'Kỹ',
    '功':'Công','力':'Lực','丹':'Đan','药':'Dược','藥':'Dược',
    '炼':'Luyện','煉':'Luyện','器':'Khí','宝':'Bảo','寶':'Bảo',
    '阵':'Trận','陣':'Trận','符':'Phù','咒':'Chú','印':'Ấn',
    '决':'Quyết','訣':'Quyết','诀':'Quyết','悟':'Ngộ','化':'Hóa',
    '凝':'Ngưng','聚':'Tụ','散':'Tản',
    '境':'Cảnh','阶':'Giai','階':'Giai','级':'Cấp','級':'Cấp',
    '层':'Tầng','層':'Tầng','段':'Đoạn','期':'Kỳ','峰':'Phong',
    '修':'Tu','炼':'Luyện','武':'Võ','侠':'Hiệp','俠':'Hiệp',
    '剑':'Kiếm','劍':'Kiếm','刀':'Đao','弓':'Cung','甲':'Giáp',
    '系':'Hệ','统':'Thống','統':'Thống',
    # Cảm xúc / tính chất
    '爱':'Ái','愛':'Ái','情':'Tình','欲':'Dục','色':'Sắc','恨':'Hận',
    '喜':'Hỉ','怒':'Nộ','哀':'Ai','乐':'Lạc','樂':'Lạc',
    '苦':'Khổ','甜':'Điềm','痛':'Thống','怕':'Phạ','恐':'Khủng',
    '冷':'Lãnh','热':'Nhiệt','熱':'Nhiệt','傲':'Ngạo','骄':'Kiêu','驕':'Kiêu',
    '善':'Thiện','恶':'Ác','惡':'Ác','忠':'Trung','义':'Nghĩa','義':'Nghĩa',
    '强':'Cường','強':'Cường','弱':'Nhược',
    '大':'Đại','小':'Tiểu','高':'Cao','低':'Thấp',
    '新':'Tân','旧':'Cựu','舊':'Cựu','美':'Mỹ','丑':'Xú','醜':'Xú',
    '快':'Khoái','慢':'Mạn','多':'Đa','少':'Thiểu',
    '白':'Bạch','黑':'Hắc','红':'Hồng','紅':'Hồng',
    '绿':'Lục','綠':'Lục','蓝':'Lam','藍':'Lam',
    '黄':'Hoàng','黃':'Hoàng','紫':'Tử',
    # Cơ thể
    '心':'Tâm','手':'Thủ','眼':'Nhãn','耳':'Nhĩ','口':'Khẩu',
    '头':'Đầu','頭':'Đầu','身':'Thân','血':'Huyết','骨':'Cốt',
    '胸':'Hung','腰':'Yêu','腿':'Thối','脸':'Kiểm','臉':'Kiểm',
    '臀':'Đồn','乳':'Nhũ','肉':'Nhục',
    # Hành động
    '来':'Lai','來':'Lai','去':'Khứ','到':'Đáo','入':'Nhập','出':'Xuất',
    '走':'Tẩu','行':'Hành','看':'Khán','听':'Thính','聽':'Thính',
    '说':'Thuyết','說':'Thuyết','做':'Tác','用':'Dụng',
    '爱':'Ái','打':'Đả','杀':'Sát','殺':'Sát','救':'Cứu',
    '护':'Hộ','護':'Hộ','守':'Thủ','攻':'Công','逃':'Đào',
    '斗':'Đấu','鬥':'Đấu','战':'Chiến','戰':'Chiến',
    '生':'Sinh','死':'Tử','破':'Phá','胜':'Thắng','勝':'Thắng',
    '败':'Bại','敗':'Bại','逃':'Đào','升':'Thăng','降':'Giáng',
    '进':'Tiến','進':'Tiến','退':'Thoái',
    '变':'Biến','變':'Biến','成':'Thành','至':'Chí','达':'Đạt','達':'Đạt',
    '发':'Phát','發':'Phát','加':'Gia','增':'Tăng',
    '召':'Triệu','唤':'Hoán','喚':'Hoán',
    # Vật phẩm / địa điểm
    '书':'Thư','書':'Thư','车':'Xa','車':'Xa','船':'Thuyền',
    '门':'Môn','門':'Môn','窗':'Song','路':'Lộ','桥':'Kiều','橋':'Kiều',
    '城':'Thành','宫':'Cung','宮':'Cung','楼':'Lâu','樓':'Lâu',
    '国':'Quốc','國':'Quốc','家':'Gia','宅':'Trạch','院':'Viện',
    '学':'Học','學':'Học','校':'Hiệu','堂':'Đường','殿':'Điện',
    # Nội dung truyện 18+
    '淫':'Dâm','春':'Xuân','媚':'Mị','娇':'Kiều','嬌':'Kiều',
    '骚':'Tao','騷':'Tao','浪':'Lãng','荡':'Đãng','蕩':'Đãng',
    '艳':'Diễm','豔':'Diễm','丝':'Ti','絲':'Ti',
    '性':'Tính','欲':'Dục','奴':'Nô','妓':'Kỹ',
    # Bổ sung ký tự hay gặp trong tên truyện
    '亲':'Thân','親':'Thân','怪':'Quái','消':'Tiêu','灭':'Diệt','滅':'Diệt',
    '方':'Phương','完':'Hoàn','任':'Nhậm','务':'Vụ','務':'Vụ','吧':'Ba',
    '泡':'Bào','精':'Tinh','液':'Dịch','熟':'Thục','便':'Tiện','版':'Bản',
    '奇':'Kỳ','玎':'Đinh','刚':'Cương','剛':'Cương','始':'Thủy',
    '终':'Chung','終':'Chung','续':'Tục','續':'Tục','外':'Ngoại',
    '篇':'Thiên','章':'Chương','节':'Tiết','節':'Tiết','回':'Hồi',
    '卷':'Quyển','部':'Bộ','册':'Sách','冊':'Sách','集':'Tập',
    '番':'Phiên','外':'Ngoại','番':'Phiên','后':'Hậu','记':'Ký','記':'Ký',
    '续':'Tục','新':'Tân','番':'Phiên','本':'Bản',
    '绿':'Lục','綠':'Lục','蓝':'Lam',
    '亲':'Thân','親':'Thân','近':'Cận','远':'Viễn','遠':'Viễn',
    '真':'Chân','假':'Giả','实':'Thực','實':'Thực','虚':'Hư','虛':'Hư',
    '全':'Toàn','半':'Bán','双':'Song','雙':'Song',
    '初':'Sơ','末':'Mạt','极':'Cực','極':'Cực','最':'Tối',
    '原':'Nguyên','始':'Thủy','古':'Cổ',
    '同':'Đồng','异':'Dị','異':'Dị',
    '正':'Chính','邪':'Tà','好':'Hảo',
    '特':'Đặc','别':'Biệt','別':'Biệt',
    '第':'Đệ','次':'Thứ',
    '们':'Môn','們':'Môn',
    # Bổ sung ký tự hay gặp trong tags truyện 18+
    '爆':'Bạo','触':'Xúc','孕':'Dựng','奸':'Gian','肛':'Hậu',
    '交':'Giao','群':'Quần','换':'Hoán','換':'Hoán','伴':'Bạn','侣':'Lữ','侶':'Lữ',
    '反':'Phản','差':'Sai','使':'Sứ','文':'Văn','语':'Ngữ','語':'Ngữ',
    '车':'Xa','車':'Xa','拉':'Lạp','马':'Mã','馬':'Mã',
    '太':'Thái','开':'Khai','開':'Khai','孩':'Hài','尻':'Khảo',
    '痴':'Si','宫':'Cung','宮':'Cung','国':'Quốc','國':'Quốc',
    '肥':'Phì','苗':'Miêu',
    '足':'Túc','纯':'Thuần','純':'Thuần','胸':'Hung',
    '正':'Chính','妹':'Muội','哥':'Ca',
    '注':'Chú','意':'Ý','谨':'Cẩn','慎':'Thận','阅':'Duyệt','读':'Độc',
    '包':'Bao','含':'Hàm','请':'Thỉnh',
    '村':'Thôn','乡':'Hương','鄉':'Hương',
    '娘':'Nương','嫂':'Tẩu','婶':'Thẩm','继':'Kế','繼':'Kế',
    '熟':'Thục','妇':'Phụ','婦':'Phụ','嫁':'Giá',
    '禽':'Cầm','兽':'Thú','獸':'Thú',
    '调':'Điều','教':'Giáo','训':'Huấn','练':'Luyện',
    # Từ xuất hiện trong 10 file cần đổi
    '念':'Niệm','禍':'Họa','祸':'Họa','陷':'Hãm','重':'Trọng','度':'Độ',
    '昏':'Hôn','迷':'Mê','代':'Đại','失':'Thất','业':'Nghiệp','業':'Nghiệp',
    '敌':'Địch','敵':'Địch','传':'Truyền','傳':'Truyền','卷':'Quyển',
    '宠':'Sủng','寵':'Sủng','溺':'Nịch','御':'Ngự',
    '歡':'Hoan','歡':'Hoan','迎':'Nghênh','扶':'Phù',
    '穿':'Xuyên','越':'Việt','废':'Phế','廢':'Phế','材':'Tài',
    '逆':'Nghịch','极':'Cực','極':'Cực','品':'Phẩm','炉':'Lô','爐':'Lô',
    '鼎':'Đỉnh','过':'Quá','過':'Quá','经':'Kinh','經':'Kinh',
    '每':'Mỗi','通':'Thông',
    '命':'Mệnh','运':'Vận','運':'Vận','族':'Tộc',
    '系':'Hệ','召':'Triệu','重':'Trọng',
}

_CJK_RE = re.compile(r'[一-鿿㐀-䶿豈-﫿\U00020000-\U0002a6df'
                      r'⺀-⻿⼀-⿟㇀-㇯︰-﹏]')


def hanzi_to_hanviet(text: str) -> str:
    """Chuyển ký tự Hán tự trong text sang âm Hán Việt (fallback khi dịch máy thất bại).
    Ký tự không có trong bảng giữ nguyên."""
    if not text:
        return text
    parts = []
    prev_end = 0
    for m in _CJK_RE.finditer(text):
        parts.append(text[prev_end:m.start()])
        char = m.group(0)
        parts.append(HANZI_HV.get(char, char))
        prev_end = m.end()
    parts.append(text[prev_end:])
    return " ".join(p for p in " ".join(parts).split() if p)


def has_hanzi(text: str) -> bool:
    """Kiểm tra text có chứa chữ Hán tự không."""
    return bool(_CJK_RE.search(text))


KEEP_AS_IS = {
    "Yuko", "Martin", "Lexington", "Blue", "Sky", "Rhapsody", "Nano",
    "Rox", "Airlines", "Ceo", "Cosplayer",
}

# Pinyin -> Han Viet CO DAU day du
PINYIN_HANVIET = {
    # nguyen am dau
    "a": "A", "ai": "Ai", "an": "An", "ang": "Ngang", "ao": "Ao",
    "e": "Ngạc", "ei": "Ê", "en": "Ân", "er": "Nhĩ",
    "o": "O", "ou": "Âu",
    # b
    "ba": "Ba", "bai": "Bạch", "ban": "Ban", "bang": "Bang", "bao": "Bảo",
    "bei": "Bội", "ben": "Bản", "beng": "Bành", "bi": "Bí", "bian": "Biên",
    "biao": "Biểu", "bie": "Biệt", "bin": "Tân", "bing": "Bình", "bo": "Bà",
    "bu": "Bộ",
    # p
    "pa": "Phả", "pai": "Phái", "pan": "Phán", "pang": "Bàng", "pao": "Bảo",
    "pei": "Bội", "pen": "Phun", "peng": "Bành", "pi": "Phi", "pian": "Thiên",
    "piao": "Phiêu", "pie": "Phiết", "pin": "Tần", "ping": "Bình", "po": "Phá",
    "pou": "Phẩu", "pu": "Phổ",
    # m
    "ma": "Ma", "mai": "Mại", "man": "Mãn", "mang": "Mang", "mao": "Mao",
    "mei": "Mỹ", "men": "Môn", "meng": "Mộng", "mi": "Mi", "mian": "Miên",
    "miao": "Miêu", "mie": "Diệt", "min": "Mẫn", "ming": "Minh", "miu": "Mậu",
    "mo": "Mạc", "mou": "Mưu", "mu": "Mục",
    # f
    "fa": "Phát", "fan": "Phán", "fang": "Phương", "fei": "Phi", "fen": "Phần",
    "feng": "Phong", "fo": "Phật", "fou": "Phủ", "fu": "Phú",
    # d
    "da": "Đại", "dai": "Đại", "dan": "Đan", "dang": "Đảng", "dao": "Đạo",
    "de": "Đức", "dei": "Đắc", "deng": "Đặng", "di": "Đệ", "dian": "Điện",
    "diao": "Điêu", "die": "Điệp", "ding": "Đinh", "diu": "Điu", "dong": "Đông",
    "dou": "Đậu", "du": "Độ", "duan": "Đoàn", "dui": "Đội", "dun": "Đôn",
    "duo": "Đa",
    # t
    "ta": "Tha", "tai": "Thái", "tan": "Đàm", "tang": "Đường", "tao": "Đào",
    "te": "Đặc", "teng": "Đằng", "ti": "Thể", "tian": "Thiên", "tiao": "Điêu",
    "tie": "Thiết", "ting": "Đình", "tong": "Thông", "tou": "Đầu", "tu": "Độ",
    "tuan": "Đoàn", "tui": "Thối", "tun": "Đôn", "tuo": "Thác",
    # n
    "na": "Na", "nai": "Nải", "nan": "Nam", "nang": "Nang", "nao": "Não",
    "ne": "Nề", "nei": "Nội", "nen": "Non", "neng": "Năng", "ni": "Nị",
    "nian": "Niên", "niang": "Nương", "niao": "Niểu", "nie": "Niết",
    "nin": "Ninh", "ning": "Ninh", "niu": "Nữu", "nong": "Nông", "nu": "Nô",
    "nuan": "Noản", "nuo": "Noa", "nv": "Nữ",
    # l
    "la": "Lạp", "lai": "Lai", "lan": "Lan", "lang": "Lang", "lao": "Lão",
    "le": "Lạc", "lei": "Lôi", "leng": "Lãnh", "li": "Lý", "lian": "Liên",
    "liang": "Lương", "liao": "Liêu", "lie": "Liệt", "lin": "Lâm",
    "ling": "Linh", "liu": "Lưu", "long": "Long", "lou": "Lâu", "lu": "Lộ",
    "luan": "Loan", "lun": "Luân", "luo": "La", "lv": "Lữ",
    # g
    "ga": "Ca", "gai": "Cái", "gan": "Can", "gang": "Cương", "gao": "Cao",
    "ge": "Cách", "gei": "Cấp", "gen": "Căn", "geng": "Canh", "gong": "Công",
    "gou": "Câu", "gu": "Cổ", "gua": "Qua", "guai": "Quái", "guan": "Quan",
    "guang": "Quảng", "gui": "Quý", "gun": "Côn", "guo": "Quốc",
    # k
    "ka": "Ca", "kai": "Khải", "kan": "Khan", "kang": "Khang", "kao": "Khảo",
    "ke": "Khả", "ken": "Khẩn", "keng": "Khanh", "kong": "Không", "kou": "Khẩu",
    "ku": "Khổ", "kua": "Khoa", "kuai": "Khoái", "kuan": "Khoan",
    "kuang": "Khuông", "kui": "Khê", "kun": "Khôn", "kuo": "Khoát",
    # h
    "ha": "Ha", "hai": "Hải", "han": "Hàn", "hang": "Hàng", "hao": "Hào",
    "he": "Hà", "hei": "Hắc", "hen": "Hận", "heng": "Hằng", "hong": "Hồng",
    "hou": "Hậu", "hu": "Hồ", "hua": "Hoa", "huai": "Hoài", "huan": "Hoàn",
    "huang": "Hoàng", "hui": "Huệ", "hun": "Hôn", "huo": "Hoả",
    # j
    "ji": "Cơ", "jia": "Gia", "jian": "Kiến", "jiang": "Giang", "jiao": "Giao",
    "jie": "Giải", "jin": "Kim", "jing": "Kinh", "jiong": "Quỳnh", "jiu": "Cửu",
    "ju": "Cư", "juan": "Quyên", "jue": "Quyết", "jun": "Quân",
    # q
    "qi": "Kỳ", "qia": "Khạp", "qian": "Thiên", "qiang": "Cường", "qiao": "Kiều",
    "qie": "Thiết", "qin": "Tần", "qing": "Thanh", "qiong": "Quỳnh", "qiu": "Thu",
    "qu": "Khúc", "quan": "Toàn", "que": "Khuyết", "qun": "Quần",
    # x
    "xi": "Hy", "xia": "Hạ", "xian": "Tiên", "xiang": "Hương", "xiao": "Tiểu",
    "xie": "Tạ", "xin": "Tân", "xing": "Hùng", "xiong": "Hùng", "xiu": "Tú",
    "xu": "Từ", "xuan": "Tuyên", "xue": "Tuyết", "xun": "Tuấn",
    # zh
    "zha": "Tra", "zhai": "Trại", "zhan": "Chiến", "zhang": "Trương",
    "zhao": "Triệu", "zhe": "Triết", "zhen": "Trinh", "zheng": "Trịnh",
    "zhi": "Chí", "zhong": "Trung", "zhou": "Châu", "zhu": "Chu", "zhua": "Trảo",
    "zhuan": "Chuyên", "zhuang": "Trang", "zhui": "Truy", "zhun": "Chuẩn",
    "zhuo": "Trác",
    # ch
    "cha": "Sai", "chai": "Sài", "chan": "Sản", "chang": "Trường",
    "chao": "Triều", "che": "Xa", "chen": "Trần", "cheng": "Thành",
    "chi": "Trí", "chong": "Sung", "chou": "Sửu", "chu": "Sở", "chuai": "Suy",
    "chuan": "Xuyên", "chuang": "Sang", "chui": "Thùy", "chun": "Xuân",
    "chuo": "Xước",
    # sh
    "sha": "Sa", "shai": "Sái", "shan": "Sơn", "shang": "Thượng",
    "shao": "Thiếu", "she": "Xã", "shei": "Thuỳ", "shen": "Thẩn",
    "sheng": "Thành", "shi": "Thị", "shou": "Thọ", "shu": "Thư", "shua": "Soát",
    "shuai": "Soái", "shuan": "Soán", "shuang": "Song", "shui": "Thuỷ",
    "shun": "Thuận", "shuo": "Thuyết",
    # r
    "ran": "Nhiên", "rang": "Nhường", "rao": "Nhiêu", "re": "Nhiệt",
    "ren": "Nhân", "reng": "Nhưng", "ri": "Nhật", "rong": "Dung", "rou": "Nhu",
    "ru": "Nhu", "ruan": "Nhuyễn", "rui": "Nhuệ", "run": "Nhuận", "ruo": "Nhược",
    # z
    "za": "Tạp", "zai": "Tái", "zan": "Tán", "zang": "Tang", "zao": "Táo",
    "ze": "Trách", "zei": "Tặc", "zen": "Tang", "zeng": "Tăng", "zi": "Tử",
    "zong": "Tông", "zou": "Tấu", "zu": "Tổ", "zuan": "Toán", "zui": "Tội",
    "zun": "Tôn", "zuo": "Tác",
    # c
    "ca": "Sát", "cai": "Thái", "can": "Thẩm", "cang": "Thương", "cao": "Tào",
    "ce": "Sách", "cen": "Sầm", "ceng": "Tằng", "ci": "Từ", "cong": "Thông",
    "cou": "Thâu", "cu": "Thô", "cuan": "Toán", "cui": "Thôi", "cun": "Thôn",
    "cuo": "Thả",
    # s
    "sa": "Tát", "sai": "Tái", "san": "Tam", "sang": "Tang", "sao": "Tào",
    "se": "Sắc", "sen": "Sầm", "seng": "Tăng", "si": "Tử", "song": "Tống",
    "sou": "Sưu", "su": "Tô", "suan": "Toán", "sui": "Tuỳ", "sun": "Tôn",
    "suo": "Toả",
    # y
    "ya": "Á", "yan": "Yến", "yang": "Dương", "yao": "Diêu", "ye": "Diệp",
    "yi": "Di", "yin": "Âm", "ying": "Anh", "yo": "Yo", "yong": "Vĩnh",
    "you": "Hữu", "yu": "Vũ", "yuan": "Viên", "yue": "Nguyệt", "yun": "Vân",
    # w
    "wa": "Oa", "wai": "Ngoại", "wan": "Vạn", "wang": "Vương", "wei": "Vi",
    "wen": "Văn", "weng": "Ông", "wo": "Ngã", "wu": "Vũ",
}

_SYLLABLES = set(PINYIN_HANVIET.keys())
_MAX_SYL = max(len(s) for s in _SYLLABLES)
_NAME_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b")
_converted: dict = {}


def _segment(word_lower: str) -> list | None:
    syllables, i, n = [], 0, len(word_lower)
    while i < n:
        matched = None
        for length in range(min(_MAX_SYL, n - i), 0, -1):
            cand = word_lower[i:i + length]
            if cand in _SYLLABLES:
                matched = cand
                break
        if not matched:
            return None
        syllables.append(matched)
        i += len(matched)
    return syllables or None


def _convert_word(word: str) -> str:
    if word in KEEP_AS_IS:
        return word
    syls = _segment(word.lower())
    if not syls:
        return word
    return " ".join(PINYIN_HANVIET[s] for s in syls)


def convert_names(text: str) -> str:
    if not text:
        return text

    def _repl(m: re.Match) -> str:
        original = m.group(0)
        words = original.split()
        converted_words = [_convert_word(w) for w in words]
        result = " ".join(converted_words)
        if result != original:
            _converted[original] = result
        return result

    return _NAME_RE.sub(_repl, text)


def pop_converted() -> dict:
    global _converted
    out = _converted
    _converted = {}
    return out
