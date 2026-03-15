"""
Harmony Device Module

Handles Harmony OS device interactions.
"""

import logging
import time
from hmdriver2.driver import Driver


class HarmonyDevice:
    """Harmony OS device controller."""

    def __init__(self):
        """Initialize Harmony device."""
        self.d = Driver()
        self.app_package_names = {
            "携程": "com.ctrip.harmonynext",
            "飞猪": "com.fliggy.hmos",
            "IntelliOS": "ohos.hongmeng.intellios",
            "同城": "com.tongcheng.hmos",
            "携程旅行": "com.ctrip.harmonynext",
            "饿了么": "me.ele.eleme",
            "知乎": "com.zhihu.hmos",
            "哔哩哔哩": "yylx.danmaku.bili",
            "微信": "com.tencent.wechat",
            "小红书": "com.xingin.xhs_hos",
            "QQ音乐": "com.tencent.hm.qqmusic",
            "高德地图": "com.amap.hmapp",
            "淘宝": "com.taobao.taobao4hmos",
            "微博": "com.sina.weibo.stage",
            "京东": "com.jd.hm.mall",
            "飞猪旅行": "com.fliggy.hmos",
            "天气": "com.huawei.hmsapp.totemweather",
            "什么值得买": "com.smzdm.client.hmos",
            "闲鱼": "com.taobao.idlefish4ohos",
            "慧通差旅": "com.smartcom.itravelhm",
            "PowerAgent": "com.example.osagent",
            "航旅纵横": "com.umetrip.hm.app",
            "滴滴出行": "com.sdu.didi.hmos.psnger",
            "电子邮件": "com.huawei.hmos.email",
            "图库": "com.huawei.hmos.photos",
            "日历": "com.huawei.hmos.calendar",
            "心声社区": "com.huawei.it.hmxinsheng",
            "信息": "com.ohos.mms",
            "文件管理": "com.huawei.hmos.files",
            "运动健康": "com.huawei.hmos.health",
            "智慧生活": "com.huawei.hmos.ailife",
            "豆包": "com.larus.nova.hm",
            "WeLink": "com.huawei.it.welink",
            "设置": "com.huawei.hmos.settings",
            "懂车帝": "com.ss.dcar.auto",
            "美团外卖": "com.meituan.takeaway",
            "大众点评": "com.sankuai.dianping",
            "美团": "com.sankuai.hmeituan",
            "浏览器": "com.huawei.hmos.browser",
            "饿了么": "me.ele.eleme",
            "拼多多": "com.xunmeng.pinduoduo.hos"
        }

    def start_app(self, app):
        """Start app by name."""
        package_name = self.app_package_names.get(app)
        if not package_name:
            raise ValueError(f"App '{app}' is not registered with a package name.")
        self.d.start_app(package_name)
        time.sleep(1.5)

    def app_start(self, package_name):
        """Start app by package name."""
        self.d.force_start_app(package_name)
        time.sleep(1.5)

    def app_stop(self, package_name):
        """Stop app."""
        self.d.stop_app(package_name)

    def screenshot(self, path):
        """Take screenshot and save to path."""
        self.d.screenshot(path)

    def click(self, x, y):
        """Click at coordinates."""
        self.d.click(x, y)
        time.sleep(0.5)

    def input(self, text):
        """Input text."""
        self.d.input_text(text)
        logging.info("Sending Enter key after text input for Harmony device using adb shell input keyevent 66")
        self.d.shell(['input', 'keyevent', '66'])  # 66 is Enter key
        time.sleep(0.5)

    def swipe(self, direction, scale=0.5):
        """Swipe in direction."""
        self.d.swipe_ext(direction, scale=scale)

    def keyevent(self, key):
        """Send key event."""
        self.d.press_key(key)

    def dump_hierarchy(self):
        """Dump UI hierarchy."""
        return self.d.dump_hierarchy()
