"""
Android Device Module

Handles Android device interactions.
"""

import base64
import logging
import time
import uiautomator2 as u2


class AndroidDevice:
    """Android device controller using uiautomator2."""

    def __init__(self, adb_endpoint=None):
        """
        Initialize Android device.

        Args:
            adb_endpoint: ADB endpoint (optional, uses default if not specified)
        """
        if adb_endpoint:
            self.d = u2.connect(adb_endpoint)
        else:
            self.d = u2.connect()
        self.app_package_names = {
            "携程": "ctrip.android.view",
            "同城": "com.tongcheng.android",
            "飞猪": "com.taobao.trip",
            "去哪儿": "com.Qunar",
            "华住会": "com.htinns",
            "饿了么": "me.ele",
            "支付宝": "com.eg.android.AlipayGphone",
            "淘宝": "com.taobao.taobao",
            "京东": "com.jingdong.app.mall",
            "美团": "com.sankuai.meituan",
            "滴滴出行": "com.sdu.didi.psnger",
            "微信": "com.tencent.mm",
            "微博": "com.sina.weibo",
            "华为商城": "com.vmall.client",
            "华为视频": "com.huawei.himovie",
            "华为音乐": "com.huawei.music",
            "华为应用市场": "com.huawei.appmarket",
            "拼多多": "com.xunmeng.pinduoduo",
            "大众点评": "com.dianping.v1",
            "小红书": "com.xingin.xhs",
            "浏览器": "com.microsoft.emmx",
            "雷电游戏中心": "com.android.flysilkworm",
            "QQ邮箱": "com.tencent.androidqqmail",
            "百度": "com.baidu.searchbox",
            "WhatsApp": "com.whatsapp",
            "outlook": "com.microsoft.office.outlook",
            "Chrome": "com.android.chrome"
        }

    def start_app(self, app):
        """Start app by name."""
        package_name = self.app_package_names.get(app)
        if not package_name:
            raise ValueError(f"App '{app}' is not registered with a package name.")
        self.d.app_start(package_name, stop=True)
        time.sleep(1)
        if not self.d.app_wait(package_name, timeout=10):
            raise RuntimeError(f"Failed to start app '{app}' with package '{package_name}'")

    def app_start(self, package_name):
        """Start app by package name."""
        self.d.app_start(package_name, stop=True)
        time.sleep(1)
        if not self.d.app_wait(package_name, timeout=10):
            raise RuntimeError(f"Failed to start package '{package_name}'")

    def app_stop(self, package_name):
        """Stop app."""
        self.d.app_stop(package_name)

    def screenshot(self, path):
        """Take screenshot and save to path."""
        self.d.screenshot(path)

    def click(self, x, y):
        """Click at coordinates."""
        self.d.click(x, y)
        time.sleep(0.5)

    def is_input_active(self):
        """Check if input field is active."""
        try:
            current_ime = self.d.current_ime()
            logging.info(f"Current IME: {current_ime}")

            hierarchy = self.d.dump_hierarchy()

            input_indicators = [
                'input', 'edit', 'textfield', 'search', 'keyboard',
                'EditText', 'AutoCompleteTextView', 'SearchView',
                '软键盘', '输入法', '键盘'
            ]

            has_input_elements = any(indicator in hierarchy for indicator in input_indicators)
            logging.info(f"Has input elements in hierarchy: {has_input_elements}")

            try:
                input_method_state = self.d.shell(['dumpsys', 'input_method']).output
                has_keyboard_shown = 'mInputShown=true' in input_method_state or 'mIsInputViewShown=true' in input_method_state
                logging.info(f"Keyboard shown via dumpsys: {has_keyboard_shown}")
            except:
                has_keyboard_shown = False

            is_active = has_input_elements or has_keyboard_shown
            logging.info(f"Input active status: {is_active}")
            return is_active

        except Exception as e:
            logging.warning(f"Failed to check input status: {e}")
            return False

    def input(self, text):
        """Input text."""
        if not self.is_input_active():
            logging.warning("Input field is not active, cannot input text directly")
            raise RuntimeError("Input field is not active. Please click on an input field first.")

        current_ime = self.d.current_ime()
        self.d.shell(['settings', 'put', 'secure', 'default_input_method', 'com.android.adbkeyboard/.AdbIME'])
        time.sleep(0.5)
        charsb64 = base64.b64encode(text.encode('utf-8')).decode('utf-8')
        self.d.shell(['am', 'broadcast', '-a', 'ADB_INPUT_B64', '--es', 'msg', charsb64])
        time.sleep(0.5)

        self.d.shell(['settings', 'put', 'secure', 'default_input_method', current_ime])
        time.sleep(0.5)

    def swipe(self, direction, scale=0.5):
        """Swipe in direction."""
        self.d.swipe_ext(direction=direction, scale=scale)

    def keyevent(self, key):
        """Send key event."""
        self.d.keyevent(key)

    def dump_hierarchy(self):
        """Dump UI hierarchy."""
        return self.d.dump_hierarchy()

    def dump_xml(self, path):
        """Dump UI hierarchy XML to file."""
        xml_content = self.d.dump_hierarchy()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        return xml_content
