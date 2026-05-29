"""
Android Device Module

Handles Android device interactions.
"""

import base64
import logging
import subprocess
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
        self.adb_endpoint = adb_endpoint
        self.d = self._connect_with_retry(adb_endpoint)
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
            "Chrome": "com.android.chrome",
            "telegram": "org.telegram.messenger",
        }

    def _connect_with_retry(self, adb_endpoint=None, retries: int = 3):
        last_exc = None
        for attempt in range(1, max(1, retries) + 1):
            try:
                device = u2.connect(adb_endpoint) if adb_endpoint else u2.connect()
                _ = device.serial
                return device
            except Exception as exc:
                last_exc = exc
                logging.warning(
                    "uiautomator2 connect failed on attempt %s/%s for %s: %s",
                    attempt,
                    retries,
                    adb_endpoint or "default-device",
                    exc,
                )
                self._reset_uiautomator(adb_endpoint)
                time.sleep(1.5 * attempt)
        if last_exc:
            raise last_exc
        raise RuntimeError("failed to connect Android device")

    def _reset_uiautomator(self, adb_endpoint=None) -> None:
        if not adb_endpoint:
            return
        for package_name in ("com.github.uiautomator", "com.github.uiautomator.test", "com.github.uiautomator2", "com.github.uiautomator2.test"):
            try:
                subprocess.run(
                    ["adb", "-s", adb_endpoint, "shell", "am", "force-stop", package_name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            except Exception:
                pass

    @property
    def device_serial(self) -> str:
        """获取设备序列号"""
        if self.adb_endpoint:
            return self.adb_endpoint
        try:
            return self.d.serial
        except Exception:
            return "unknown_device"

    def get_device_info(self) -> dict:
        """
        获取设备元信息

        Returns:
            包含 serial, model, android_version, manufacturer 的字典
        """
        info = {
            "serial": self.device_serial,
            "model": "Unknown",
            "android_version": "Unknown",
            "manufacturer": "Unknown",
        }

        try:
            model = self.d.shell(["getprop", "ro.product.model"]).output.strip()
            if model:
                info["model"] = model
        except Exception:
            pass

        try:
            version = self.d.shell(["getprop", "ro.build.version.release"]).output.strip()
            if version:
                info["android_version"] = version
        except Exception:
            pass

        try:
            manufacturer = self.d.shell(["getprop", "ro.product.manufacturer"]).output.strip()
            if manufacturer:
                info["manufacturer"] = manufacturer
        except Exception:
            pass

        return info

    def start_app(self, app):
        """Start app by name."""
        package_name = self.app_package_names.get(app)
        if not package_name:
            raise ValueError(f"App '{app}' is not registered with a package name.")
        self.app_start(package_name)

    def app_start(self, package_name):
        """Start app by package name."""
        self.d.app_start(package_name, stop=True)
        time.sleep(1)
        if not self.d.app_wait(package_name, timeout=10):
            self._force_launch_package(package_name)
        time.sleep(1)
        if not self._is_foreground_package(package_name):
            self._force_launch_package(package_name)
        time.sleep(1)
        if not self._is_foreground_package(package_name):
            raise RuntimeError(f"Failed to start package '{package_name}'")

    def app_stop(self, package_name):
        """Stop app."""
        self.d.app_stop(package_name)

    def screenshot(self, path):
        """Take screenshot and save to path."""
        self._retry_device_call(lambda: self.d.screenshot(path), "screenshot")

    def click(self, x, y):
        """Click at coordinates."""
        self._retry_device_call(lambda: self.d.click(x, y), "click")
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
        self._retry_device_call(lambda: self.d.swipe_ext(direction=direction, scale=scale), "swipe")

    def keyevent(self, key):
        """Send key event."""
        self._retry_device_call(lambda: self.d.keyevent(key), "keyevent")

    def dump_hierarchy(self):
        """Dump UI hierarchy."""
        return self._retry_device_call(lambda: self.d.dump_hierarchy(), "dump_hierarchy")

    def dump_xml(self, path):
        """Dump UI hierarchy XML to file."""
        xml_content = self.dump_hierarchy()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        return xml_content

    def _retry_device_call(self, func, operation: str, retries: int = 2):
        last_exc = None
        for attempt in range(1, retries + 2):
            try:
                return func()
            except Exception as exc:
                last_exc = exc
                logging.warning(
                    "Android device %s failed on attempt %s/%s: %s",
                    operation,
                    attempt,
                    retries + 1,
                    exc,
                )
                if attempt > retries:
                    break
                self._reset_uiautomator(self.device_serial)
                self.d = self._connect_with_retry(self.adb_endpoint)
                time.sleep(1.0 * attempt)
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Android device operation failed: {operation}")

    def _force_launch_package(self, package_name):
        """Fallback launch path when app_start does not bring the app to foreground."""
        if not self.adb_endpoint:
            try:
                self.d.app_start(package_name, stop=True)
            except Exception:
                pass
            return
        try:
            subprocess.run(
                [
                    "adb",
                    "-s",
                    self.adb_endpoint,
                    "shell",
                    "monkey",
                    "-p",
                    package_name,
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "1",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except Exception as exc:
            logging.warning("Fallback launch failed for %s: %s", package_name, exc)

    def _is_foreground_package(self, package_name):
        try:
            current = self.d.app_current() or {}
        except Exception:
            current = {}
        current_pkg = str(current.get("package") or current.get("packageName") or "")
        if current_pkg == package_name:
            return True
        try:
            xml = self.d.dump_hierarchy()
        except Exception:
            return False
        return package_name in xml
